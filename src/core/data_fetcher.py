"""
Enhanced Data Fetcher with Twelve Data Fallback and CSV Support
Fetches XAUUSD market data with multiple source redundancy
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
from pathlib import Path
import pickle
import requests
from twelvedata import TDClient

from config.settings import settings
from src.utils.logger import setup_logger
from src.utils.timeframe_utils import TIMEFRAME_MINUTES, resample_to_timeframe
from src.utils.monthly_data_cache import load_cached_monthly_data, save_monthly_data_cache


logger = setup_logger(__name__, settings.LOG_LEVEL)


class DataFetcher:
    """Fetches and manages XAUUSD market data from multiple sources"""

    def __init__(self, ticker: str = None, use_csv: bool = False):
        """
        Initialize DataFetcher

        Args:
            ticker: yfinance ticker symbol (default: XAUUSD=X)
            use_csv: Use CSV data instead of API (for backtesting)
        """
        self.ticker = ticker or settings.YFINANCE_TICKER
        self.use_csv = use_csv
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.cache_file = settings.DATA_STORAGE_PATH / f"{self.ticker.replace('=', '_')}_cache.pkl"

        # Live spot-basis correction cache (see _get_live_basis) - avoids
        # re-fetching PAXG-USD/XAUT-USD for every single timeframe
        # within one scan cycle
        self._basis_cache: Optional[float] = None
        self._basis_cache_time: Optional[datetime] = None

        # Initialize Twelve Data client - now the PRIMARY source (genuine
        # spot XAUUSD pricing with minimal delay), with yfinance GC=F as
        # a fallback if Twelve Data fails (delayed futures data, needs
        # the spot-basis correction below).
        self.twelve_data_client = None
        if settings.TWELVE_DATA_API_KEY:
            try:
                self.twelve_data_client = TDClient(apikey=settings.TWELVE_DATA_API_KEY)
                logger.info("Twelve Data client initialized as primary data source")
            except Exception as e:
                logger.warning(f"Failed to initialize Twelve Data: {e}")

        logger.info(f"DataFetcher initialized for {self.ticker} (CSV mode: {use_csv})")

    def fetch_data(
        self,
        timeframe: str,
        period: str = None,
        force_refresh: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for specified timeframe with automatic fallback

        Priority order:
        1. CSV data (if use_csv=True)
        2. Monthly cache (MN timeframe only - fetched once per calendar month)
        3. Twelve Data (primary - genuine spot XAUUSD, minimal delay)
        4. yfinance GC=F (fallback - delayed futures, spot-basis corrected)

        Args:
            timeframe: Timeframe code (M1, M5, M15, M30, H1, H4, D1, W1, MN)
            period: yfinance period, used only if the yfinance fallback
                is reached (e.g., '1mo', '6mo', '1y', 'max')
            force_refresh: Force refresh from API even if cached

        Returns:
            DataFrame with OHLCV data or None if error
        """

        # Check in-memory cache first (per-run, shared across methods)
        cache_key = f"{timeframe}_{period}"
        if not force_refresh and cache_key in self.data_cache:
            cached_data = self.data_cache[cache_key]
            if not cached_data.empty:
                last_timestamp = cached_data.index[-1]

                # Handle timezone-aware timestamps
                now = datetime.now()
                if hasattr(last_timestamp, 'tz') and last_timestamp.tz is not None:
                    import pytz
                    last_timestamp_utc = last_timestamp.astimezone(pytz.UTC)
                    now_utc = pytz.UTC.localize(now)
                    age_minutes = (now_utc - last_timestamp_utc).total_seconds() / 60
                else:
                    age_minutes = (now - last_timestamp).total_seconds() / 60

                if age_minutes < settings.SCAN_INTERVAL_MINUTES:
                    logger.debug(f"Using cached data for {timeframe} (age: {age_minutes:.1f} min)")
                    return cached_data

        # CSV mode (backtesting)
        if self.use_csv:
            return self._fetch_from_csv(timeframe)

        # Monthly timeframe: only fetch once per calendar month across
        # ALL runs (persisted to disk, not just this process's memory),
        # since re-fetching the full Monthly history every 15-minute
        # cycle would burn through Twelve Data's rate limit for data
        # that essentially never changes within a month.
        if timeframe == 'MN' and not force_refresh:
            cached_monthly = load_cached_monthly_data()
            if cached_monthly is not None:
                logger.debug(f"Using this month's cached Monthly data ({len(cached_monthly)} candles) - not re-fetching")
                self.data_cache[cache_key] = cached_monthly
                return cached_monthly

        # Try Twelve Data first (primary source)
        if self.twelve_data_client:
            try:
                data = self._fetch_from_twelve_data(timeframe, period)
                if data is not None and not data.empty:
                    self.data_cache[cache_key] = data
                    if timeframe == 'MN':
                        save_monthly_data_cache(data)
                    return data
            except Exception as e:
                logger.warning(f"Twelve Data failed for {timeframe}: {e}")

        # Fallback to yfinance (GC=F futures - delayed, needs spot-basis
        # correction). Logged clearly since falling back here means
        # you're temporarily back on delayed data.
        logger.warning(f"Falling back to yfinance (GC=F futures, delayed) for {timeframe}")
        try:
            data = self._fetch_from_yfinance(timeframe, period)
            if data is not None and not data.empty:
                data = self._apply_spot_basis(data)
                self.data_cache[cache_key] = data
                if timeframe == 'MN':
                    save_monthly_data_cache(data)
                return data
        except Exception as e:
            logger.warning(f"yfinance also failed for {timeframe}: {e}")

        logger.error(f"All data sources failed for {timeframe}")
        return None

    def _fetch_from_yfinance(
        self,
        timeframe: str,
        period: str = None
    ) -> Optional[pd.DataFrame]:
        """Fetch data from yfinance with 15-second timeout"""

        if period is None:
            period = self._get_default_period(timeframe)

        # Map timeframe to yfinance interval
        interval_map = {
            'M1': '1m',
            'M3': '2m',
            'M5': '5m',
            'M15': '15m',
            'M30': '30m',
            'H1': '1h',
            'H4': '1h',
            'D1': '1d',
            'W1': '1wk',
            'MN': '1mo'
        }

        interval = interval_map.get(timeframe, '15m')

        logger.info(f"Fetching from yfinance: {timeframe} (interval={interval}, period={period})")

        try:
            import signal
            import platform

            # Only use timeout on Unix-like systems
            use_timeout = platform.system() != 'Windows' and hasattr(signal, 'SIGALRM')

            if use_timeout:
                def timeout_handler(signum, frame):
                    raise TimeoutError(f"yfinance fetch timed out for {timeframe}")

                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(15)  # 15-second timeout

            ticker_obj = yf.Ticker(self.ticker)
            df = ticker_obj.history(period=period, interval=interval)

            if use_timeout:
                signal.alarm(0)  # Cancel timeout

            if df.empty:
                return None

            # Standardize column names - handle varying yfinance column formats
            # yfinance may return: Open/High/Low/Close/Volume/Dividends/Stock Splits
            # or lowercase variants depending on version
            col_map = {}
            for col in df.columns:
                col_lower = col.lower().replace(' ', '_')
                if col_lower == 'open':
                    col_map[col] = 'Open'
                elif col_lower == 'high':
                    col_map[col] = 'High'
                elif col_lower == 'low':
                    col_map[col] = 'Low'
                elif col_lower == 'close':
                    col_map[col] = 'Close'
                elif col_lower in ('volume', 'vol'):
                    col_map[col] = 'Volume'

            df = df.rename(columns=col_map)

            # Keep only OHLCV columns
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            available_cols = [c for c in required_cols if c in df.columns]

            if len(available_cols) < 4:  # Need at least OHLC
                logger.error(f"yfinance missing required columns. Got: {list(df.columns)}")
                return None

            # Add Volume column if missing (some forex pairs don't have volume)
            if 'Volume' not in df.columns:
                df['Volume'] = 0

            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

            # Handle H4 resampling
            if timeframe == 'H4' and interval == '1h':
                df = resample_to_timeframe(df, 'H4')

            logger.info(f"✓ yfinance: {len(df)} candles for {timeframe}")
            return df

        except TimeoutError as e:
            logger.warning(f"yfinance timed out for {timeframe}")
            return None
        except Exception as e:
            logger.warning(f"yfinance error for {timeframe}: {e}")
            return None

    def _fetch_from_twelve_data(
        self,
        timeframe: str,
        period: str = None
    ) -> Optional[pd.DataFrame]:
        """
        Fetch data from Twelve Data API (primary source)

        Free tier limits:
        - 8 API calls/minute
        - 800 API calls/day
        - 5,000 data points max per request (hard cap, all tiers)
        """

        # Map timeframe to Twelve Data interval
        interval_map = {
            'M1': '1min',
            'M3': '3min',
            'M5': '5min',
            'M15': '15min',
            'M30': '30min',
            'H1': '1h',
            'H4': '4h',
            'D1': '1day',
            'W1': '1week',
            'MN': '1month'
        }

        interval = interval_map.get(timeframe, '15min')
        outputsize = self._get_twelvedata_outputsize(timeframe)

        logger.info(f"Fetching from Twelve Data: {timeframe} (interval={interval}, size={outputsize})")

        # Validate symbol before making API call
        if not settings.TWELVE_DATA_SYMBOL or settings.TWELVE_DATA_SYMBOL.strip() == '':
            logger.error("TWELVE_DATA_SYMBOL is empty - check environment variables")
            return None

        try:
            # Use time_series endpoint
            ts = self.twelve_data_client.time_series(
                symbol=settings.TWELVE_DATA_SYMBOL,
                interval=interval,
                outputsize=outputsize,
                timezone="UTC"
            )

            # Fetch data
            data = ts.as_pandas()

            if data.empty:
                return None

            # Standardize column names
            data = data.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })

            # Ensure datetime index
            if not isinstance(data.index, pd.DatetimeIndex):
                data.index = pd.to_datetime(data.index)

            # Sort by date (Twelve Data returns newest first)
            data = data.sort_index()

            # Select only OHLCV columns
            data = data[['Open', 'High', 'Low', 'Close', 'Volume']]

            logger.info(f"✓ Twelve Data: {len(data)} candles for {timeframe}")
            return data

        except Exception as e:
            logger.error(f"Twelve Data fetch error: {e}")
            return None

    def _get_twelvedata_outputsize(self, timeframe: str) -> int:
        """
        Candle count to request per timeframe, sized to the confirmed
        lookback windows below - each comfortably under Twelve Data's
        hard 5,000-points-per-request cap (verified against real
        candle counts from this bot's own logs):

            MN  (Monthly): since 2003          -> ~280 candles
            W1  (Weekly):  5 years              -> ~261 candles
            D1  (Daily):   3 years               -> ~758 candles
            H4  (4-hour):  1 year                -> ~1,553 candles
            H1  (1-hour):  6 months              -> ~2,871 candles
            M15 (15-min):  30 days               -> ~2,301 candles
            M5  (5-min):   10 days               -> ~2,296 candles

        Values below include headroom over these estimates.
        """
        outputsize_map = {
            'MN': 300,     # since 2003 (~280 candles) - plenty of margin
            'W1': 280,     # 5 years
            'D1': 800,     # 3 years
            'H4': 1600,    # 1 year
            'H1': 3000,    # 6 months
            'M15': 2400,   # 30 days
            'M5': 2400,    # 10 days
        }
        return outputsize_map.get(timeframe, 2400)

    def _fetch_from_csv(self, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Fetch data from CSV files (for backtesting)

        Expected CSV format:
        - Filename: XAUUSD_{timeframe}.csv (e.g., XAUUSD_M15.csv)
        - Columns: datetime, open, high, low, close, volume
        - datetime in ISO format or timestamp

        Args:
            timeframe: Timeframe code

        Returns:
            DataFrame with OHLCV data
        """

        csv_path = settings.CSV_DATA_PATH / f"XAUUSD_{timeframe}.csv"

        if not csv_path.exists():
            logger.error(f"CSV file not found: {csv_path}")
            return None

        try:
            logger.info(f"Loading CSV: {csv_path}")

            # Read CSV
            df = pd.read_csv(csv_path)

            # Standardize column names (case-insensitive)
            df.columns = df.columns.str.lower()

            # Map to standard names
            column_map = {
                'datetime': 'datetime',
                'date': 'datetime',
                'time': 'datetime',
                'timestamp': 'datetime',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }

            df = df.rename(columns=column_map)

            # Set datetime index
            if 'datetime' in df.columns:
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df.set_index('datetime')
            else:
                logger.error("CSV missing datetime column")
                return None

            # Ensure all OHLCV columns exist
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            missing_cols = [col for col in required_cols if col not in df.columns]

            if missing_cols:
                logger.error(f"CSV missing columns: {missing_cols}")
                return None

            # Select only OHLCV
            df = df[required_cols]

            # Sort by date
            df = df.sort_index()

            logger.info(f"✓ CSV loaded: {len(df)} candles for {timeframe}")
            return df

        except Exception as e:
            logger.error(f"CSV read error: {e}")
            return None

    def _get_default_period(self, timeframe: str) -> str:
        """
        Default yfinance period, used only for the GC=F fallback path
        when Twelve Data fails. yfinance's period parameter only
        accepts a fixed set of values (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y,
        5y, 10y, ytd, max) rather than arbitrary day counts, so these
        are the closest valid values that cover at least as much
        history as the primary Twelve Data windows do - it's fine for
        the (rare) fallback path to fetch a bit more than the primary
        path requests, just not less.
        """

        period_map = {
            'M1': '5d',
            'M3': '5d',
            'M5': '1mo',    # primary: 10 days
            'M15': '1mo',   # primary: 30 days
            'M30': '1mo',
            'H1': '6mo',    # primary: 6 months (exact match)
            'H4': '1y',     # primary: 1 year (exact match)
            'D1': '5y',     # primary: 3 years (no '3y' in yfinance's enum)
            'W1': '5y',     # primary: 5 years (exact match)
            'MN': 'max'     # primary: since 2003 - 'max' covers all available history
        }

        return period_map.get(timeframe, '1mo')

    def fetch_multiple_timeframes(
        self,
        timeframes: List[str],
        force_refresh: bool = False
    ) -> Dict[str, pd.DataFrame]:
        """Fetch data for multiple timeframes"""

        results = {}

        for tf in timeframes:
            data = self.fetch_data(tf, force_refresh=force_refresh)
            if data is not None:
                results[tf] = data
            else:
                logger.warning(f"Failed to fetch data for {tf}")

        logger.info(f"Fetched data for {len(results)}/{len(timeframes)} timeframes")
        return results

    def _log_data_staleness(self, ticker: str, data: pd.DataFrame) -> None:
        """
        Log how many minutes old the latest candle is versus current UTC
        time. This is a diagnostic to empirically compare how delayed
        GC=F (a regulated futures contract, typically ~10-20 min
        delayed on free feeds) is against PAXG-USD/XAUT-USD (crypto
        gold tokens, which aren't subject to the same mandated
        exchange-data delay) - rather than assuming which is fresher.
        """
        if data.empty:
            return
        try:
            last_ts = data.index[-1]
            if last_ts.tzinfo is None:
                last_ts = last_ts.tz_localize('UTC')
            else:
                last_ts = last_ts.tz_convert('UTC')
            age_minutes = (datetime.now(timezone.utc) - last_ts.to_pydatetime()).total_seconds() / 60
            logger.info(f"Data freshness: {ticker} latest candle is {age_minutes:.1f} min old")
        except Exception as e:
            logger.debug(f"Could not compute staleness for {ticker}: {e}")

    def _fetch_spot_proxy_price(self, ticker: str) -> Optional[float]:
        """Fetch the latest price for a gold-backed token (PAXG-USD / XAUT-USD)"""
        try:
            obj = yf.Ticker(ticker)
            data = obj.history(period='1d', interval='1m')
            if not data.empty:
                self._log_data_staleness(ticker, data)
                return float(data['Close'].iloc[-1])
        except Exception as e:
            logger.warning(f"Failed to fetch spot proxy price for {ticker}: {e}")
        return None

    def _get_spot_proxy_average(self) -> Optional[float]:
        """
        Average of PAXG-USD and XAUT-USD, used as a live proxy for true
        gold spot price. Both are asset-backed tokens that track physical
        gold closely, unlike GC=F, which is a futures contract and can
        drift from spot due to contango/backwardation.

        Falls back to whichever single ticker succeeds if the other
        fails; returns None only if both fail.
        """
        prices = []
        for ticker in settings.SPOT_PROXY_TICKERS:
            price = self._fetch_spot_proxy_price(ticker)
            if price is not None:
                prices.append(price)
            else:
                logger.warning(f"Spot proxy {ticker} unavailable this cycle")

        if not prices:
            return None

        avg = sum(prices) / len(prices)
        logger.debug(f"Spot proxy average from {len(prices)}/{len(settings.SPOT_PROXY_TICKERS)} source(s): {avg:.2f}")
        return avg

    def _get_live_basis(self) -> float:
        """
        Compute the live futures-to-spot basis: current GC=F price minus
        the PAXG-USD/XAUT-USD average. This is recalculated fresh each
        scan cycle (cached briefly to avoid re-fetching per timeframe)
        instead of using a hardcoded/stale offset, so it tracks whatever
        the real current futures premium/discount actually is.

        Returns 0.0 (no correction applied) if the proxy price can't be
        fetched at all, so the bot degrades gracefully to raw GC=F
        pricing rather than failing.
        """

        if not settings.ENABLE_SPOT_BASIS_CORRECTION:
            return 0.0

        now = datetime.now()
        if (
            self._basis_cache is not None
            and self._basis_cache_time is not None
            and (now - self._basis_cache_time).total_seconds() < settings.SCAN_INTERVAL_MINUTES * 60
        ):
            return self._basis_cache

        try:
            ticker_obj = yf.Ticker(self.ticker)
            gc_data = ticker_obj.history(period='1d', interval='1m')
            if not gc_data.empty:
                self._log_data_staleness(self.ticker, gc_data)
                gc_price = float(gc_data['Close'].iloc[-1])
            else:
                gc_price = None
        except Exception as e:
            logger.warning(f"Could not fetch {self.ticker} price for basis calculation: {e}")
            gc_price = None

        if gc_price is None:
            logger.warning("No futures price available for basis calculation - skipping correction this cycle")
            self._basis_cache = 0.0
            self._basis_cache_time = now
            return 0.0

        proxy_avg = self._get_spot_proxy_average()

        if proxy_avg is None:
            logger.warning(
                f"Both {' and '.join(settings.SPOT_PROXY_TICKERS)} unavailable - "
                f"using raw {self.ticker} futures price uncorrected this cycle"
            )
            basis = 0.0
        else:
            basis = gc_price - proxy_avg
            logger.info(
                f"Live spot basis: {self.ticker}={gc_price:.2f}, "
                f"proxy_avg={proxy_avg:.2f}, basis={basis:+.2f}"
            )

        self._basis_cache = basis
        self._basis_cache_time = now
        return basis

    def _apply_spot_basis(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Shift OHLC prices by the live futures-to-spot basis so all
        downstream detectors, methods, and signal entry/SL/TP levels
        reflect corrected spot pricing rather than raw futures pricing.

        This is a uniform vertical shift of the whole series, so it
        doesn't affect any relative price-action logic (ranges, gaps,
        structure, ATR) - only the absolute price level.
        """

        if not settings.ENABLE_SPOT_BASIS_CORRECTION:
            return df

        basis = self._get_live_basis()

        if basis == 0.0:
            return df

        df = df.copy()
        for col in ('Open', 'High', 'Low', 'Close'):
            if col in df.columns:
                df[col] = df[col] - basis

        return df

    def get_latest_price(self) -> Optional[float]:
        """Get latest market price, corrected toward true spot (see _get_live_basis)"""

        try:
            # Try yfinance first
            ticker_obj = yf.Ticker(self.ticker)
            data = ticker_obj.history(period='1d', interval='1m')

            raw_price = None
            if not data.empty:
                raw_price = float(data['Close'].iloc[-1])
            elif self.twelve_data_client:
                # Fallback to Twelve Data
                quote = self.twelve_data_client.quote(symbol=settings.TWELVE_DATA_SYMBOL)
                if quote and 'close' in quote:
                    raw_price = float(quote['close'])

            if raw_price is None:
                return None

            basis = self._get_live_basis()
            return raw_price - basis

        except Exception as e:
            logger.error(f"Error getting latest price: {e}")
            return None

    def get_current_candle(self, timeframe: str) -> Optional[pd.Series]:
        """Get current (most recent) candle for timeframe"""

        df = self.fetch_data(timeframe, force_refresh=True)

        if df is not None and not df.empty:
            return df.iloc[-1]

        return None

    def save_cache_to_disk(self):
        """Save current cache to disk"""

        try:
            with open(self.cache_file, 'wb') as f:
                pickle.dump(self.data_cache, f)
            logger.info(f"Cache saved to {self.cache_file}")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def load_cache_from_disk(self):
        """Load cache from disk"""

        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'rb') as f:
                    self.data_cache = pickle.load(f)
                logger.info(f"Cache loaded from {self.cache_file}")
            except Exception as e:
                logger.error(f"Error loading cache: {e}")
                self.data_cache = {}
        else:
            logger.debug("No cache file found")

    def clear_cache(self):
        """Clear in-memory and disk cache"""

        self.data_cache = {}
        if self.cache_file.exists():
            self.cache_file.unlink()
        logger.info("Cache cleared")

    def validate_data_quality(self, df: pd.DataFrame) -> Dict[str, any]:
        """Validate data quality"""

        results = {
            'valid': True,
            'issues': [],
            'total_rows': len(df),
            'missing_values': 0,
            'duplicate_timestamps': 0,
            'invalid_ohlc': 0
        }

        if df.empty:
            results['valid'] = False
            results['issues'].append("DataFrame is empty")
            return results

        # Check for missing values
        missing = df.isnull().sum().sum()
        if missing > 0:
            results['missing_values'] = missing
            results['issues'].append(f"{missing} missing values found")

        # Check for duplicate timestamps
        duplicates = df.index.duplicated().sum()
        if duplicates > 0:
            results['duplicate_timestamps'] = duplicates
            results['issues'].append(f"{duplicates} duplicate timestamps found")

        # Check OHLC validity
        invalid_ohlc = (
            (df['High'] < df['Low']) |
            (df['Close'] > df['High']) |
            (df['Close'] < df['Low'])
        ).sum()

        if invalid_ohlc > 0:
            results['invalid_ohlc'] = invalid_ohlc
            results['issues'].append(f"{invalid_ohlc} invalid OHLC relationships")

        if results['issues']:
            results['valid'] = False

        return results
