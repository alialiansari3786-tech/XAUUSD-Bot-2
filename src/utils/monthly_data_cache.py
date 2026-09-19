"""
Monthly Data Cache
Persists the Monthly-timeframe OHLCV data across runs so it's fetched
once per calendar month instead of on every 15-minute scan cycle.
Monthly candles barely change within a month (there's only ever one
still-forming candle, plus history that never changes), so re-fetching
the whole series every cycle is pure waste against Twelve Data's
per-minute rate limit.

GitHub Actions runners are stateless, so "keep using the same data
for the rest of the month" means persisting the actual fetched
DataFrame to a file that gets committed back to the repo (see
.github/workflows/live-bot.yml's "Persist signal state" step, which
commits the whole state/ directory) and reloaded on every subsequent
run within that month.
"""

import json
import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

CACHE_DIR = settings.BASE_DIR / 'state'
DATA_FILE = CACHE_DIR / 'monthly_data_cache.csv'
META_FILE = CACHE_DIR / 'monthly_data_cache_meta.json'


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m')


def load_cached_monthly_data() -> Optional[pd.DataFrame]:
    """
    Return the cached Monthly OHLCV DataFrame if it was fetched during
    the current UTC calendar month, else None (meaning a fresh fetch
    is needed - either it's a new month, or nothing has been cached
    yet).
    """
    if not META_FILE.exists() or not DATA_FILE.exists():
        return None

    try:
        with open(META_FILE, 'r') as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read monthly cache metadata, will re-fetch: {e}")
        return None

    if meta.get('fetched_month') != _current_month_key():
        return None

    try:
        df = pd.read_csv(DATA_FILE, index_col=0, parse_dates=True)
        if df.empty:
            return None
        return df
    except Exception as e:
        logger.warning(f"Could not load cached monthly data, will re-fetch: {e}")
        return None


def save_monthly_data_cache(df: pd.DataFrame) -> None:
    """Persist freshly-fetched Monthly OHLCV data for reuse for the rest of this month."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(DATA_FILE)
        with open(META_FILE, 'w') as f:
            json.dump({'fetched_month': _current_month_key()}, f, indent=2)
        logger.debug(f"Cached {len(df)} Monthly candles for the rest of {_current_month_key()}")
    except Exception as e:
        logger.warning(f"Could not save monthly data cache (will just re-fetch next cycle): {e}")
