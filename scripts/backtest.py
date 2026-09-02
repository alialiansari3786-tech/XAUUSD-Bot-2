"""
Backtesting Script
Test trading methods against historical CSV data
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.data_fetcher import DataFetcher
from src.methods.combined_method import CombinedMethod
from src.methods.percentage_method import PercentageMethod
from src.methods.liquidity_sar_method import LiquiditySARMethod
from src.utils.logger import setup_logger
from config.settings import settings


logger = setup_logger(__name__, 'INFO')


class Backtester:
    """Backtesting engine for trading methods"""

    def __init__(self, use_csv: bool = True):
        """
        Initialize backtester

        Args:
            use_csv: Use CSV data (True) or live API (False)
        """
        self.data_fetcher = DataFetcher(use_csv=use_csv)
        self.combined_method = CombinedMethod(self.data_fetcher)
        self.percentage_method = PercentageMethod(self.data_fetcher)
        self.liquidity_sar_method = LiquiditySARMethod(self.data_fetcher)

        self.results = {
            'Combined Method': [],
            'Percentage Method': [],
            'Liquidity SAR Method': []
        }

    def run(self, methods: List[str] = None):
        """
        Run backtest

        Args:
            methods: List of methods to test (default: all)
        """

        if methods is None:
            methods = ['combined', 'percentage', 'liquidity_sar']

        logger.info("=" * 60)
        logger.info("BACKTESTING STARTED")
        logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Methods: {', '.join(methods)}")
        logger.info("=" * 60)

        # Run each method
        if 'combined' in methods:
            logger.info("\n--- Testing Combined Method ---")
            signal = self._test_method(self.combined_method, 'Combined Method')
            if signal:
                self.results['Combined Method'].append(signal)

        if 'percentage' in methods:
            logger.info("\n--- Testing Percentage Method ---")
            signal = self._test_method(self.percentage_method, 'Percentage Method')
            if signal:
                self.results['Percentage Method'].append(signal)

        if 'liquidity_sar' in methods:
            logger.info("\n--- Testing Liquidity SAR Method ---")
            signal = self._test_method(self.liquidity_sar_method, 'Liquidity SAR Method')
            if signal:
                self.results['Liquidity SAR Method'].append(signal)

        # Print summary
        self._print_summary()

    def _test_method(self, method, name: str):
        """Test a single method"""

        try:
            signal = method.analyze()

            if signal:
                logger.info(f"✓ Signal found: {signal.bias.value}")
                logger.info(f"  Entry: {signal.entry_price:.2f}")
                logger.info(f"  SL: {signal.stop_loss:.2f}")
                logger.info(f"  TP: {signal.take_profit:.2f}")
                logger.info(f"  Confluence: {signal.confluence_score}")
                return signal
            else:
                logger.info("✗ No signal")
                return None

        except Exception as e:
            logger.error(f"Error in {name}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _print_summary(self):
        """Print backtest summary"""

        logger.info("\n" + "=" * 60)
        logger.info("BACKTEST SUMMARY")
        logger.info("=" * 60)

        total_signals = sum(len(signals) for signals in self.results.values())

        logger.info(f"\nTotal Signals: {total_signals}")

        for method, signals in self.results.items():
            if signals:
                logger.info(f"\n{method}: {len(signals)} signal(s)")

                bullish = sum(1 for s in signals if s.bias.value == "Bullish")
                bearish = len(signals) - bullish

                logger.info(f"  Bullish: {bullish}")
                logger.info(f"  Bearish: {bearish}")

                # Calculate average confluence
                avg_confluence = sum(s.confluence_score for s in signals) / len(signals)
                logger.info(f"  Avg Confluence: {avg_confluence:.1f}")

        logger.info("\n" + "=" * 60)


def main():
    """Main entry point"""

    parser = argparse.ArgumentParser(description="Backtest XAUUSD trading methods")

    parser.add_argument(
        '--csv-data',
        action='store_true',
        help='Use CSV data from data/historical/ directory'
    )

    parser.add_argument(
        '--methods',
        nargs='+',
        choices=['combined', 'percentage', 'liquidity_sar', 'all'],
        default=['all'],
        help='Methods to test (default: all)'
    )

    parser.add_argument(
        '--live-api',
        action='store_true',
        help='Use live API data instead of CSV'
    )

    args = parser.parse_args()

    # Determine data source
    use_csv = args.csv_data or not args.live_api

    if use_csv:
        print("\n📊 Running backtest with CSV data")
        print(f"Data path: {settings.CSV_DATA_PATH}")
    else:
        print("\n🌐 Running backtest with live API data")

    # Parse methods
    if 'all' in args.methods:
        methods = ['combined', 'percentage', 'liquidity_sar']
    else:
        methods = args.methods

    print(f"Methods: {', '.join(methods)}\n")

    # Run backtest
    backtester = Backtester(use_csv=use_csv)
    backtester.run(methods=methods)


if __name__ == "__main__":
    main()
