"""
Main Orchestrator and Scheduler
Coordinates all trading methods and manages 15-minute scanning
"""

import time
import os
import schedule
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import traceback
import pytz

from config.settings import settings
from src.core.data_fetcher import DataFetcher
from src.methods.combined_method import CombinedMethod
from src.methods.percentage_method import PercentageMethod
from src.methods.liquidity_sar_method import LiquiditySARMethod
from src.integrations.telegram_bot import TelegramNotifier
from src.integrations.chart_generator import ChartGenerator
from src.utils.logger import setup_logger


logger = setup_logger(
    __name__,
    settings.LOG_LEVEL,
    log_file=settings.BASE_DIR / 'logs' / 'bot.log'
)


class TradingBot:
    """Main trading bot orchestrator"""

    def __init__(self):
        """Initialize trading bot"""
        logger.info("Initializing XAUUSD Trading Bot")

        # Validate settings
        valid, errors = settings.validate()
        if not valid:
            for error in errors:
                logger.error(error)
            raise ValueError("Invalid configuration")

        # Initialize components
        self.data_fetcher = DataFetcher()
        self.combined_method = CombinedMethod(self.data_fetcher)
        self.percentage_method = PercentageMethod(self.data_fetcher)
        self.liquidity_sar_method = LiquiditySARMethod(self.data_fetcher)
        self.telegram = TelegramNotifier()
        self.chart_generator = ChartGenerator()

        # Track signals
        self.daily_signals: List[Any] = []
        self.weekly_signals: List[Any] = []
        self.last_daily_summary = None
        self.last_weekly_recap = None

        # Market hours tracking
        self.last_market_status_log = None

        logger.info("Trading bot initialized successfully")

    def is_market_open(self) -> tuple[bool, str]:
        """
        Check if Gold (XAUUSD) market is open for trading

        Gold Market Hours (UTC):
        - Opens: Sunday 22:00 UTC (Asia session start)
        - Closes: Friday 22:00 UTC (US session end)
        - Closed: Friday 22:00 - Sunday 22:00

        Returns:
            Tuple of (is_open: bool, reason: str)
        """
        # TEMPORARY TESTING OVERRIDE: lets you verify the timeout fix on a
        # weekend, when the real gold market is closed. Set the
        # FORCE_MARKET_OPEN=true env var / GitHub secret to bypass the
        # weekday check below. Set it back to false (or remove it) once
        # you've confirmed the fix and want normal weekday-only behavior.
        if os.getenv('FORCE_MARKET_OPEN', 'false').lower() == 'true':
            return True, "Market forced open (TESTING MODE - weekend override active)"

        now_utc = datetime.now(pytz.UTC)
        current_hour = now_utc.hour
        current_minute = now_utc.minute
        weekday = now_utc.weekday()  # Monday=0, Sunday=6

        # Weekend closure: Friday 22:00 - Sunday 22:00
        if weekday == 5:  # Saturday
            return False, "Weekend - Market closed (Saturday)"

        elif weekday == 6:  # Sunday
            # Market opens Sunday 22:00 UTC
            if current_hour < 22:
                hours_until_open = 22 - current_hour
                return False, f"Weekend - Market opens in {hours_until_open}h (Sunday 22:00 UTC)"
            else:
                return True, "Market open (Sunday evening - Asia session)"

        elif weekday == 4:  # Friday
            # Market closes Friday 22:00 UTC
            if current_hour >= 22:
                return False, "Weekend starting - Market closed (Friday 22:00+ UTC)"
            else:
                hours_until_close = 22 - current_hour
                return True, f"Market open (Friday - closes in {hours_until_close}h)"

        else:  # Monday-Thursday
            return True, f"Market open ({now_utc.strftime('%A')})"

    def should_analyze(self) -> tuple[bool, str]:
        """
        Determine if analysis should run now

        Returns:
            Tuple of (should_run: bool, reason: str)
        """
        is_open, status = self.is_market_open()

        if not is_open:
            return False, status

        # Market is open - proceed with analysis
        return True, status

    def run_analysis(self):
        """Run complete analysis cycle"""

        try:
            # Check if market is open
            should_run, market_status = self.should_analyze()

            # Log market status periodically (every hour)
            now = datetime.now()
            if (self.last_market_status_log is None or
                (now - self.last_market_status_log).seconds >= 3600):
                logger.info(f"Market Status: {market_status}")
                self.last_market_status_log = now

            if not should_run:
                logger.info(f"Skipping analysis - {market_status}")
                return

            logger.info("=" * 50)
            logger.info("Starting analysis cycle")
            logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"Market Status: {market_status}")

            # Get current price
            current_price = self.data_fetcher.get_latest_price()
            if current_price:
                logger.info(f"Current XAUUSD price: {current_price:.2f}")

            signals = []

            # Run all methods if enabled
            if settings.ENABLE_ALL_METHODS:
                # Method 1: Combined Method
                try:
                    logger.info("Running Combined Method...")
                    signal = self.combined_method.analyze()
                    if signal:
                        signals.append(signal)
                        logger.info(f"✓ Combined Method signal: {signal.bias.value}")
                except Exception as e:
                    logger.error(f"Combined Method error: {e}")
                    logger.debug(traceback.format_exc())

                # Method 2: Percentage Method
                try:
                    logger.info("Running Percentage Method...")
                    signal = self.percentage_method.analyze()
                    if signal:
                        signals.append(signal)
                        logger.info(f"✓ Percentage Method signal: {signal.bias.value}")
                except Exception as e:
                    logger.error(f"Percentage Method error: {e}")
                    logger.debug(traceback.format_exc())

                # Method 3: Liquidity SAR Method
                try:
                    logger.info("Running Liquidity SAR Method...")
                    signal = self.liquidity_sar_method.analyze()
                    if signal:
                        signals.append(signal)
                        logger.info(f"✓ Liquidity SAR Method signal: {signal.bias.value}")
                except Exception as e:
                    logger.error(f"Liquidity SAR Method error: {e}")
                    logger.debug(traceback.format_exc())

            # Process signals
            if signals:
                logger.info(f"Found {len(signals)} signal(s)")
                for signal in signals:
                    self._process_signal(signal)

                    # Add to daily tracking
                    self.daily_signals.append(signal)
                    self.weekly_signals.append(signal)
            else:
                logger.info("No signals found")

            logger.info("Analysis cycle completed")
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"Error in analysis cycle: {e}")
            logger.debug(traceback.format_exc())

            # Send error alert
            try:
                self.telegram.send_error_alert_sync(f"Analysis cycle error: {str(e)}")
            except:
                pass

    def _process_signal(self, signal: Any):
        """
        Process and send signal

        Args:
            signal: Trade signal object
        """

        try:
            logger.info(f"Processing signal: {signal.method}")

            # Chart generation disabled
            # chart_path = None
            # try:
            #     # Get appropriate timeframe data
            #     data = self.data_fetcher.fetch_data(signal.entry_timeframe)
            #     if data is not None:
            #         chart_path = self.chart_generator.generate_signal_chart(
            #             data,
            #             signal
            #         )
            # except Exception as e:
            #     logger.error(f"Chart generation error: {e}")

            # Send to Telegram (without chart)
            success = self.telegram.send_trade_alert_sync(signal, chart_path=None)

            if success:
                logger.info("✓ Signal sent to Telegram")
            else:
                logger.warning("✗ Failed to send signal to Telegram")

        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            logger.debug(traceback.format_exc())

    def send_daily_summary(self):
        """Send daily summary"""

        try:
            logger.info("Generating daily summary")

            today = datetime.now().date()

            if settings.ENABLE_DAILY_SUMMARY:
                success = self.telegram.send_daily_summary_sync(
                    self.daily_signals,
                    datetime.now()
                )

                if success:
                    logger.info("✓ Daily summary sent")
                    self.last_daily_summary = today
                    self.daily_signals = []  # Reset for next day

        except Exception as e:
            logger.error(f"Error sending daily summary: {e}")

    def send_weekly_recap(self):
        """Send weekly recap"""

        try:
            logger.info("Generating weekly recap")

            if settings.ENABLE_WEEKLY_RECAP:
                # Calculate weekly stats
                weekly_data = {
                    'start_date': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
                    'total_signals': len(self.weekly_signals),
                    'by_method': {}
                }

                # Group by method
                for signal in self.weekly_signals:
                    method = signal.method
                    weekly_data['by_method'][method] = weekly_data['by_method'].get(method, 0) + 1

                success = self.telegram.send_weekly_recap_sync(weekly_data)

                if success:
                    logger.info("✓ Weekly recap sent")
                    self.last_weekly_recap = datetime.now().date()
                    self.weekly_signals = []  # Reset

        except Exception as e:
            logger.error(f"Error sending weekly recap: {e}")

    def start(self):
        """Start the bot with scheduled tasks"""

        logger.info("Starting XAUUSD Trading Bot")
        logger.info(f"Scan interval: {settings.SCAN_INTERVAL_MINUTES} minutes")

        # Send startup notification with market status
        is_open, market_status = self.is_market_open()
        try:
            self.telegram.send_status_update_sync(
                f"🚀 Bot started\n"
                f"Scan interval: {settings.SCAN_INTERVAL_MINUTES} minutes\n"
                f"Methods: Combined, Percentage, Liquidity SAR\n"
                f"Market Hours Filter: Enabled ✅\n"
                f"Market Status: {market_status}\n"
                f"Time: {datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
        except:
            pass

        # Schedule analysis every N minutes
        schedule.every(settings.SCAN_INTERVAL_MINUTES).minutes.do(self.run_analysis)

        # Schedule daily summary (at 23:00)
        schedule.every().day.at("23:00").do(self.send_daily_summary)

        # Schedule weekly recap (Sunday at 20:00)
        schedule.every().sunday.at("20:00").do(self.send_weekly_recap)

        # Run initial analysis
        self.run_analysis()

        # Main loop
        logger.info("Entering main loop...")

        try:
            while True:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.stop()

    def stop(self):
        """Stop the bot gracefully"""

        logger.info("Stopping XAUUSD Trading Bot")

        # Send shutdown notification
        try:
            self.telegram.send_status_update_sync(
                f"🛑 Bot stopped\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except:
            pass

        logger.info("Bot stopped successfully")


def main():
    """Main entry point"""

    print("""
    ╔══════════════════════════════════════════════╗
    ║   XAUUSD Automated Trading Analysis Bot     ║
    ║                                              ║
    ║   Three Trading Methods:                    ║
    ║   1. Combined Method (Multi-TF)             ║
    ║   2. Percentage Method (25%/37.5%)          ║
    ║   3. Liquidity SAR Method (8-Layer)         ║
    ║                                              ║
    ║   Press Ctrl+C to stop                      ║
    ╚══════════════════════════════════════════════╝
    """)

    try:
        bot = TradingBot()
        bot.start()

    except KeyboardInterrupt:
        print("\n\nShutdown requested by user")

    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.debug(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
