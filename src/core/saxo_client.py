"""
Saxo OpenAPI Client
Handles OAuth token refresh, instrument UIC lookup, and paginated
historical chart data + live price fetching from Saxo's OpenAPI.

ONE-TIME SETUP REQUIRED: this client cannot bootstrap itself. OAuth
requires an interactive browser login the very first time (Saxo does
not offer a no-human-required flow for individual/retail developers -
see scripts/saxo_bootstrap.py). Run that script once, locally, to
produce an initial refresh token, then store it at
state/saxo_token.json (or paste it in via SAXO_BOOTSTRAP_REFRESH_TOKEN
as described in that script's output). After that, this client
refreshes automatically, every cycle, indefinitely - Saxo issues a
brand new refresh token every time you use one (rotating refresh
tokens), so as long as this runs regularly the chain should never go
idle long enough to break.

If the refresh ever fails (e.g., the token chain did go idle too long,
or Saxo revoked it), this raises SaxoAuthError - the caller (DataFetcher)
catches this, falls back to Twelve Data, and triggers a Telegram alert
telling you to re-run the bootstrap script.
"""

import json
import base64
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

TOKEN_STATE_FILE = settings.BASE_DIR / 'state' / 'saxo_token.json'
UIC_CACHE_FILE = settings.BASE_DIR / 'state' / 'saxo_uic_cache.json'

# Saxo Chart API hard cap - confirmed from their own docs/tutorials
MAX_CANDLES_PER_REQUEST = 1200

# Saxo's Horizon parameter is in minutes
HORIZON_MINUTES = {
    'M1': 1,
    'M5': 5,
    'M15': 15,
    'M30': 30,
    'H1': 60,
    'H4': 240,
    'D1': 1440,
    'W1': 10080,
    'MN': 43200,
}


class SaxoAuthError(Exception):
    """Raised when Saxo's OAuth token refresh fails - needs manual re-bootstrap."""
    pass


class SaxoClient:
    """Saxo OpenAPI client: token refresh, UIC lookup, historical chart + live price."""

    def __init__(self):
        self.app_key = settings.SAXO_APP_KEY
        self.app_secret = settings.SAXO_APP_SECRET
        self.auth_base = settings.SAXO_AUTH_BASE_URL
        self.api_base = settings.SAXO_API_BASE_URL
        self.symbol = settings.SAXO_SYMBOL
        self.asset_type = settings.SAXO_ASSET_TYPE

        self.access_token: Optional[str] = None
        self._uic: Optional[int] = None

    def is_configured(self) -> bool:
        """Whether Saxo credentials are present at all (independent of whether the token still works)."""
        return bool(self.app_key and self.app_secret)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _load_token_state(self) -> Dict:
        if not TOKEN_STATE_FILE.exists():
            return {}
        try:
            with open(TOKEN_STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read Saxo token state: {e}")
            return {}

    def _save_token_state(self, refresh_token: str) -> None:
        try:
            TOKEN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_STATE_FILE, 'w') as f:
                json.dump({
                    'refresh_token': refresh_token,
                    'saved_at': datetime.now(timezone.utc).isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not persist Saxo refresh token: {e}")

    def refresh_access_token(self) -> None:
        """
        Exchange the current refresh token for a new access token AND a
        new refresh token (Saxo rotates refresh tokens on every use),
        persisting the new refresh token immediately.

        Raises SaxoAuthError if there's no stored refresh token yet
        (bootstrap never run) or if the refresh call itself fails
        (token chain broke - needs re-bootstrap).
        """

        if not self.is_configured():
            raise SaxoAuthError("SAXO_APP_KEY/SAXO_APP_SECRET not configured")

        state = self._load_token_state()
        refresh_token = state.get('refresh_token')

        if not refresh_token:
            raise SaxoAuthError(
                "No Saxo refresh token found - run scripts/saxo_bootstrap.py once "
                "to complete the initial interactive login"
            )

        credentials = base64.b64encode(f"{self.app_key}:{self.app_secret}".encode()).decode()

        try:
            response = requests.post(
                f"{self.auth_base}/token",
                headers={
                    'Authorization': f'Basic {credentials}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': refresh_token
                },
                timeout=15
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            raise SaxoAuthError(f"Saxo token refresh failed: {e}")

        self.access_token = payload.get('access_token')
        new_refresh_token = payload.get('refresh_token')

        if not self.access_token or not new_refresh_token:
            raise SaxoAuthError("Saxo token refresh response missing access_token/refresh_token")

        self._save_token_state(new_refresh_token)
        logger.debug("Saxo access token refreshed successfully")

    def _ensure_access_token(self) -> None:
        if not self.access_token:
            self.refresh_access_token()

    def _headers(self) -> Dict[str, str]:
        return {'Authorization': f'Bearer {self.access_token}'}

    # ------------------------------------------------------------------
    # Instrument lookup (cached - the UIC for a symbol never changes)
    # ------------------------------------------------------------------

    def _load_cached_uic(self) -> Optional[int]:
        if not UIC_CACHE_FILE.exists():
            return None
        try:
            with open(UIC_CACHE_FILE, 'r') as f:
                data = json.load(f)
            return data.get(self.symbol)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cached_uic(self, uic: int) -> None:
        try:
            UIC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if UIC_CACHE_FILE.exists():
                try:
                    with open(UIC_CACHE_FILE, 'r') as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass
            existing[self.symbol] = uic
            with open(UIC_CACHE_FILE, 'w') as f:
                json.dump(existing, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not cache Saxo UIC: {e}")

    def get_uic(self) -> int:
        """Resolve self.symbol (e.g. 'XAUUSD') to Saxo's numeric instrument ID, cached across runs."""

        cached = self._load_cached_uic()
        if cached is not None:
            self._uic = cached
            return cached

        self._ensure_access_token()

        response = requests.get(
            f"{self.api_base}/ref/v1/instruments",
            headers=self._headers(),
            params={'Keywords': self.symbol, 'AssetTypes': self.asset_type},
            timeout=15
        )
        response.raise_for_status()
        results = response.json().get('Data', [])

        if not results:
            raise ValueError(f"Saxo instrument lookup found no match for {self.symbol} ({self.asset_type})")

        uic = results[0]['Identifier']
        self._uic = uic
        self._save_cached_uic(uic)
        logger.info(f"Resolved Saxo UIC for {self.symbol}: {uic} (cached for future runs)")
        return uic

    # ------------------------------------------------------------------
    # Chart data (paginated - Saxo caps at 1,200 candles per request)
    # ------------------------------------------------------------------

    def fetch_chart(self, timeframe: str, count: int) -> pd.DataFrame:
        """
        Fetch `count` candles for `timeframe`, paginating across
        multiple requests if count exceeds Saxo's 1,200-per-request cap.
        Pages are stitched oldest-to-newest by walking backward in time
        using Mode='UpTo' + a Time cursor.
        """

        self._ensure_access_token()
        uic = self.get_uic()
        horizon = HORIZON_MINUTES.get(timeframe)

        if horizon is None:
            raise ValueError(f"No Saxo Horizon mapping for timeframe {timeframe}")

        all_frames: List[pd.DataFrame] = []
        remaining = count
        cursor_time = None  # None = "up to now" for the first page

        while remaining > 0:
            page_size = min(remaining, MAX_CANDLES_PER_REQUEST)

            params = {
                'AssetType': self.asset_type,
                'Uic': uic,
                'Horizon': horizon,
                'Count': page_size,
            }
            if cursor_time is not None:
                params['Mode'] = 'UpTo'
                params['Time'] = cursor_time

            response = requests.get(
                f"{self.api_base}/chart/v3/charts",
                headers=self._headers(),
                params=params,
                timeout=20
            )
            response.raise_for_status()
            payload = response.json()
            samples = payload.get('Data', [])

            if not samples:
                break

            page_df = pd.DataFrame(samples)
            page_df['Time'] = pd.to_datetime(page_df['Time'])
            page_df = page_df.set_index('Time').rename(columns={
                'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close'
            })
            if 'Volume' not in page_df.columns:
                page_df['Volume'] = 0

            all_frames.append(page_df[['Open', 'High', 'Low', 'Close', 'Volume']])

            remaining -= len(samples)
            # Next page: walk backward from the oldest sample just fetched
            cursor_time = page_df.index[0].strftime('%Y-%m-%dT%H:%M:%SZ')

            if len(samples) < page_size:
                # Saxo ran out of history before satisfying the full count
                break

        if not all_frames:
            return pd.DataFrame()

        combined = pd.concat(all_frames)
        combined = combined[~combined.index.duplicated(keep='first')]
        combined = combined.sort_index()
        return combined

    # ------------------------------------------------------------------
    # Live price
    # ------------------------------------------------------------------

    def get_latest_price(self) -> Optional[float]:
        """Current mid price via Saxo's info-prices endpoint."""

        self._ensure_access_token()
        uic = self.get_uic()

        response = requests.get(
            f"{self.api_base}/trade/v1/infoprices",
            headers=self._headers(),
            params={'AssetType': self.asset_type, 'Uic': uic},
            timeout=15
        )
        response.raise_for_status()
        quote = response.json().get('Quote', {})
        mid = quote.get('Mid')
        return float(mid) if mid is not None else None
