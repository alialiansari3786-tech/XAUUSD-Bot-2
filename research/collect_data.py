"""
Daily data collector: saves M5/M15/H1 bars to data/collected/ as CSV.
Source order: Saxo, then Twelve Data (yfinance is skipped on purpose,
its delayed/basis-corrected futures prices would pollute research data).
Only new bars are added; existing bars are never duplicated.
Sends a Telegram message and exits 1 if anything fails.
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from config.settings import settings
from src.core.data_fetcher import DataFetcher
from src.integrations.telegram_bot import TelegramNotifier
from src.utils.logger import setup_logger

logger = setup_logger(__name__, settings.LOG_LEVEL)

TIMEFRAMES = ['M5', 'M15', 'H1']
OUT_DIR = ROOT / 'data' / 'collected'
COLS = ['Open', 'High', 'Low', 'Close', 'Volume']


def fetch_bars(fetcher: DataFetcher, tf: str):
    """Returns (DataFrame, source_name) or (None, None)."""
    count = fetcher._get_twelvedata_outputsize(tf)

    if fetcher.saxo_client:
        try:
            df = fetcher.saxo_client.fetch_chart(tf, count=count)
            if df is not None and not df.empty:
                return df, 'saxo'
        except Exception as e:
            logger.warning(f"Saxo failed for {tf}: {e}")

    if fetcher.twelve_data_client:
        df = fetcher._fetch_from_twelve_data(tf)
        if df is not None and not df.empty:
            return df, 'twelve_data'

    return None, None


def merge_and_save(tf: str, new: pd.DataFrame) -> int:
    """Merge into data/collected/XAUUSD_<tf>.csv. Returns number of bars added."""
    new = new[COLS].copy()
    new.index = pd.to_datetime(new.index, utc=True)
    new = new.sort_index().iloc[:-1]  # drop the still-forming last bar

    path = OUT_DIR / f'XAUUSD_{tf}.csv'
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if path.exists():
        old = pd.read_csv(path, index_col=0)
        old.index = pd.to_datetime(old.index, utc=True)
        before = len(old)
        combined = pd.concat([old[COLS], new])
    else:
        before = 0
        combined = new

    combined = combined[~combined.index.duplicated(keep='last')].sort_index()
    combined.index.name = 'datetime'
    combined.to_csv(path)
    return len(combined) - before


def notify_failure(message: str) -> None:
    try:
        TelegramNotifier().send_error_alert_sync(f"Data collection failed: {message}")
    except Exception as e:
        logger.error(f"Could not send Telegram failure alert: {e}")


def main() -> int:
    failures = []
    try:
        fetcher = DataFetcher()

        for tf in TIMEFRAMES:
            df, source = fetch_bars(fetcher, tf)
            if df is None:
                failures.append(f"{tf}: no data from Saxo or Twelve Data")
                continue
            added = merge_and_save(tf, df)
            logger.info(f"{tf}: +{added} new bars (source: {source})")

    except Exception as e:
        logger.error(traceback.format_exc())
        failures.append(f"crash: {e}")

    if failures:
        notify_failure("; ".join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
