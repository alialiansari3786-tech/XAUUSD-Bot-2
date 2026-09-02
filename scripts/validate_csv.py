"""
CSV Validator
Validates CSV data quality before backtesting
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.data_fetcher import DataFetcher
from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, 'INFO')


def validate_all_csvs():
    """Validate all CSV files"""

    csv_dir = settings.CSV_DATA_PATH
    csv_files = list(csv_dir.glob("XAUUSD_*.csv"))

    if not csv_files:
        logger.error(f"No CSV files found in {csv_dir}")
        return False

    logger.info(f"Found {len(csv_files)} CSV files to validate\n")

    all_valid = True
    fetcher = DataFetcher(use_csv=True)

    for csv_file in csv_files:
        timeframe = csv_file.stem.split('_')[1]  # Extract M15, H1, etc.

        logger.info(f"Validating {csv_file.name}:")

        # Load CSV
        df = fetcher.fetch_data(timeframe)

        if df is None:
            logger.error(f"  ✗ Failed to load CSV")
            all_valid = False
            continue

        # Validate data quality
        validation = fetcher.validate_data_quality(df)

        logger.info(f"  Rows: {validation['total_rows']}")

        if validation['valid']:
            logger.info(f"  ✓ All checks passed")
        else:
            logger.error(f"  ✗ Validation failed:")
            for issue in validation['issues']:
                logger.error(f"    - {issue}")
            all_valid = False

        print()

    if all_valid:
        logger.info("=" * 50)
        logger.info("✓ All CSV files validated successfully!")
        logger.info("=" * 50)
    else:
        logger.error("=" * 50)
        logger.error("✗ Some CSV files have issues")
        logger.error("=" * 50)

    return all_valid


if __name__ == "__main__":
    success = validate_all_csvs()
    sys.exit(0 if success else 1)
