"""
Configuration Settings Module
Manages environment variables and application settings
"""

import os
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = Path(__file__).parent.parent
ENV_PATH = BASE_DIR / 'config' / '.env'

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    # Try to load from template if .env doesn't exist
    load_dotenv(BASE_DIR / 'config' / '.env.template')


class Settings:
    """Application settings"""

    # Base Directory
    BASE_DIR: Path = BASE_DIR

    # Telegram Configuration
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID: str = os.getenv('TELEGRAM_CHAT_ID', '')

    # Claude API
    CLAUDE_API_KEY: str = os.getenv('CLAUDE_API_KEY', '')

    # Bot Configuration
    SCAN_INTERVAL_MINUTES: int = int(os.getenv('SCAN_INTERVAL_MINUTES', '15'))
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    # Data Configuration
    # GC=F = Gold Futures (COMEX) - XAUUSD=X was delisted by yfinance
    YFINANCE_TICKER: str = os.getenv('YFINANCE_TICKER', 'GC=F')
    DATA_STORAGE_PATH: Path = BASE_DIR / os.getenv('DATA_STORAGE_PATH', 'data/')

    # Live spot-basis correction
    # GC=F is a futures contract and can trade at a premium/discount
    # to true physical gold spot (contango/backwardation). To correct
    # for this without a hardcoded/stale offset, the bot computes a
    # live basis each scan cycle against the average of two
    # gold-backed crypto tokens that track spot closely: PAXG-USD
    # and XAUT-USD.
    ENABLE_SPOT_BASIS_CORRECTION: bool = os.getenv('ENABLE_SPOT_BASIS_CORRECTION', 'true').lower() == 'true'
    SPOT_PROXY_TICKERS: List[str] = ['PAXG-USD', 'XAUT-USD']

    # Saxo OpenAPI (primary data source)
    # SIM (simulation) environment by default - switch SAXO_AUTH_BASE_URL
    # and SAXO_API_BASE_URL to the live equivalents once you have a LIVE
    # account and app. One-time setup: run scripts/saxo_bootstrap.py to
    # produce the initial refresh token (see src/core/saxo_client.py).
    SAXO_APP_KEY: str = os.getenv('SAXO_APP_KEY', '')
    SAXO_APP_SECRET: str = os.getenv('SAXO_APP_SECRET', '')
    SAXO_AUTH_BASE_URL: str = os.getenv('SAXO_AUTH_BASE_URL', 'https://sim.logonvalidation.net')
    SAXO_API_BASE_URL: str = os.getenv('SAXO_API_BASE_URL', 'https://gateway.saxobank.com/sim/openapi')
    SAXO_SYMBOL: str = os.getenv('SAXO_SYMBOL', 'XAUUSD')
    SAXO_ASSET_TYPE: str = os.getenv('SAXO_ASSET_TYPE', 'FxSpot')

    # Twelve Data API (Fallback)
    TWELVE_DATA_API_KEY: str = os.getenv('TWELVE_DATA_API_KEY', '')
    TWELVE_DATA_SYMBOL: str = os.getenv('TWELVE_DATA_SYMBOL', 'XAUUSD')
    ENABLE_TWELVE_DATA_FALLBACK: bool = os.getenv('ENABLE_TWELVE_DATA_FALLBACK', 'true').lower() == 'true'

    # CSV Data (Backtesting)
    CSV_DATA_PATH: Path = BASE_DIR / os.getenv('CSV_DATA_PATH', 'data/historical/')

    # Chart Configuration
    CHART_STORAGE_PATH: Path = BASE_DIR / os.getenv('CHART_STORAGE_PATH', 'charts/')
    CHART_DPI: int = int(os.getenv('CHART_DPI', '150'))
    CHART_STYLE: str = os.getenv('CHART_STYLE', 'dark')

    # Trading Configuration - Confluence Scores
    MIN_CONFLUENCE_SCORE_METHOD1: int = int(os.getenv('MIN_CONFLUENCE_SCORE_METHOD1', '6'))
    MIN_CONFLUENCE_SCORE_METHOD2: int = int(os.getenv('MIN_CONFLUENCE_SCORE_METHOD2', '5'))
    MIN_CONFLUENCE_SCORE_METHOD3: int = int(os.getenv('MIN_CONFLUENCE_SCORE_METHOD3', '7'))

    # Risk Parameters (reference only)
    DEFAULT_RISK_PERCENT: float = float(os.getenv('DEFAULT_RISK_PERCENT', '1.0'))
    MAX_TRADES_PER_DAY: int = int(os.getenv('MAX_TRADES_PER_DAY', '5'))

    # Feature Flags
    ENABLE_DAILY_SUMMARY: bool = os.getenv('ENABLE_DAILY_SUMMARY', 'true').lower() == 'true'
    ENABLE_WEEKLY_RECAP: bool = os.getenv('ENABLE_WEEKLY_RECAP', 'true').lower() == 'true'
    ENABLE_SCREENSHOT_ANALYSIS: bool = os.getenv('ENABLE_SCREENSHOT_ANALYSIS', 'false').lower() == 'true'
    ENABLE_ALL_METHODS: bool = os.getenv('ENABLE_ALL_METHODS', 'true').lower() == 'true'

    # Timeframes
    TIMEFRAMES = {
        'W1': '1wk',
        'D1': '1d',
        'H4': '4h',
        'H1': '1h',
        'M30': '30m',
        'M15': '15m',
        'M5': '5m',
        'M3': '3m',
        'M1': '1m'
    }

    # Indicator Parameters
    ATR_PERIOD: int = 200
    EQH_EQL_THRESHOLD_MULTIPLIER: float = 0.1

    # Structure Detection Parameters
    SWING_LOOKBACK: int = 5
    INTERNAL_LOOKBACK: int = 3

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """Validate required settings"""
        errors = []

        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN is not set")

        if not cls.TELEGRAM_CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID is not set")

        # Create directories if they don't exist
        cls.DATA_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
        cls.CHART_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

        return len(errors) == 0, errors

    @classmethod
    def get_yfinance_interval(cls, timeframe: str) -> str:
        """Convert timeframe to yfinance interval"""
        return cls.TIMEFRAMES.get(timeframe, '15m')


# Create singleton instance
settings = Settings()
