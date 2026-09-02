"""
Enhanced Data Fetcher with Twelve Data Fallback and CSV Support
Fetches XAUUSD market data with multiple source redundancy
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from pathlib import Path
import pickle
import requests
from twelvedata import TDClient

from config.settings import settings
from src.utils.logger import setup_logger
from src.utils.timeframe_utils import TIMEFRAME_MINUTES, resample_to_timeframe


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

        # Initialize Twelve Data client
        self.twelve_data_client = None
        if settings.TWELVE_DATA_API_KEY and settings.ENABLE_TWELVE_DATA_FALLBACK:
            try:
                self.twelve_data_client = TDClient(apikey=settings.TWELVE_DATA_API_KEY)
                logger.info("Twelve Data client initialized as fallback")
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
        2. yfinance
        3. Twelve Data (fallback)

        Args:
            timeframe: Timeframe code (M1, M5, M15, M30, H1, H4, D1, W1)
            period: yfinance period (e.g., '1d', '5d', '1mo', '3mo', '1y', 'max')
            force_refresh: Force refresh from API even if cached

        Returns:
            DataFrame with OHLCV data or None if error
        """

        # Check cache first
        cache_key = f"{timeframe}_{period}"
        if not force_refresh and cache_key in self.data_cache:
            cached_data = self.data_cache[cache_key]
            if not cached_data.empty:
                last_timestamp = cached_data.index[-1]

                # Handle timezone-aware timestamps from yfinance
                now = datetime.now()
                if hasattr(last_timestamp, 'tz') and last_timestamp.tz is not None:
                    # Convert timezone-aware to UTC then to naive for comparison
                    import pytz
                    last_timestamp_utc = last_timestamp.astimezone(pytz.UTC)
                    now_utc = pytz.UTC.localize(now)
                    age_minutes = (now_utc - last_timestamp_utc).total_seconds() / 60
                else:
                    # Both naive
                    age_minutes = (now - last_timestamp).total_seconds() / 60

                if age_minutes < settings.SCAN_INTERVAL_MINUTES:
                    logger.debug(f"Using cached data for {timeframe} (age: {age_minutes:.1f} min)")
                    return cached_data

        # CSV mode (backtesting)
        if self.use_csv:
            return self._fetch_from_csv(timeframe)

        # Try yfinance first
        try:
            data = self._fetch_from_yfinance(timeframe, period)
            if data is not None and not data.empty:
                self.data_cache[cache_key] = data
                return data
        except Exception as e:
            logger.warning(f"yfinance failed for {timeframe}: {e}")

        # Fallback to Twelve Data
        if self.twelve_data_client and settings.ENABLE_TWELVE_DATA_FALLBACK:
            logger.info(f"Falling back to Twelve Data for {timeframe}")
            try:
                data = self._fetch_from_twelve_data(timeframe, period)
                if data is not None and not data.empty:
                    self.data_cache[cache_key] = data
                    return data
            except Exception as e:
                logger.error(f"Twelve Data also failed for {timeframe}: {e}")

        logger.error(f"All data sources failed for {timeframe}")
        return None

    def _fetch_from_yfinance(
        self,
        timeframe: str,
        period: str = None
    ) -> Optional[pd.DataFrame]:
        """Fetch data from yfinance"""

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

        ticker_obj = yf.Ticker(self.ticker)
        df = ticker_obj.history(period=period, interval=interval)

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

    def _fetch_from_twelve_data(
        self,
        timeframe: str,
        period: str = None
    ) -> Optional[pd.DataFrame]:
        """
        Fetch data from Twelve Data API

        Free tier limits:
        - 8 API calls/minute
        - 800 API calls/day
        - Historical data available
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

        # Calculate outputsize based on period
        outputsize = self._period_to_outputsize(period, timeframe)

        logger.info(f"Fetching from Twelve Data: {timeframe} (interval={interval}, size={outputsize})")

        # Debug: Log what we're sending to Twelve Data
        logger.debug(f"Twelve Data params: symbol={settings.TWELVE_DATA_SYMBOL}, interval={interval}, outputsize={outputsize}")

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

    def _period_to_outputsize(self, period: str, timeframe: str) -> int:
        """Convert period string to outputsize for Twelve Data"""

        if period is None:
            period = self._get_default_period(timeframe)

        # Rough conversion
        period_map = {
            '1d': 96,    # 1 day at 15min
            '5d': 480,
            '7d': 672,
            '1mo': 2000,
            '2mo': 4000,
            '3mo': 5000,
            '6mo': 5000,
            '1y': 5000,
            '2y': 5000,
            '5y': 5000,
            'max': 5000
        }

        return period_map.get(period, 5000)

    def _get_default_period(self, timeframe: str) -> str:
        """Get appropriate default period for timeframe"""

        period_map = {
            'M1': '7d',
            'M3': '7d',
            'M5': '60d',
            'M15': '60d',
            'M30': '60d',
            'H1': '1y',
            'H4': '1y',
            'D1': '2y',
            'W1': '5y',
            'MN': '10y'
        }

        return period_map.get(timeframe, '60d')

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

    def get_latest_price(self) -> Optional[float]:
        """Get latest market price"""

        try:
            # Try yfinance first
            ticker_obj = yf.Ticker(self.ticker)
            data = ticker_obj.history(period='1d', interval='1m')

            if not data.empty:
                return float(data['Close'].iloc[-1])

            # Fallback to Twelve Data
            if self.twelve_data_client:
                quote = self.twelve_data_client.quote(symbol=settings.TWELVE_DATA_SYMBOL)
                if quote and 'close' in quote:
                    return float(quote['close'])

            return None

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
