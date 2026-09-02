"""
Telegram Bot Integration
Sends trade notifications, charts, daily summaries, and weekly recaps
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import io

from telegram import Bot
from telegram.error import TelegramError

from config.settings import settings
from src.utils.logger import setup_logger


logger = setup_logger(__name__, settings.LOG_LEVEL)


class TelegramNotifier:
    """Telegram bot for sending notifications"""

    def __init__(self):
        """Initialize Telegram bot"""
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.bot = None

        if self.token and self.chat_id:
            self.bot = Bot(token=self.token)
            logger.info("Telegram bot initialized")
        else:
            logger.warning("Telegram credentials not configured")

    async def send_message(self, text: str, parse_mode: str = 'Markdown') -> bool:
        """
        Send text message

        Args:
            text: Message text
            parse_mode: Formatting mode ('Markdown' or 'HTML')

        Returns:
            True if sent successfully
        """

        if not self.bot:
            logger.warning("Telegram bot not configured")
            return False

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode
            )
            logger.debug("Message sent successfully")
            return True

        except TelegramError as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def send_photo(
        self,
        photo_path: str,
        caption: Optional[str] = None
    ) -> bool:
        """
        Send photo/chart

        Args:
            photo_path: Path to image file
            caption: Optional caption

        Returns:
            True if sent successfully
        """

        if not self.bot:
            return False

        try:
            with open(photo_path, 'rb') as photo:
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode='Markdown'
                )
            logger.debug(f"Photo sent: {photo_path}")
            return True

        except TelegramError as e:
            logger.error(f"Failed to send photo: {e}")
            return False
        except FileNotFoundError:
            logger.error(f"Photo not found: {photo_path}")
            return False

    async def send_trade_alert(
        self,
        signal: Any,
        chart_path: Optional[str] = None
    ) -> bool:
        """
        Send trade alert with full setup details

        Args:
            signal: Trade signal object
            chart_path: Optional path to chart image (DISABLED - not sent)

        Returns:
            True if sent successfully
        """

        # Build message
        message = self._format_trade_alert(signal)

        # Send message only (chart feature disabled)
        success = await self.send_message(message)

        # Chart sending is disabled
        # if success and chart_path:
        #     await self.send_photo(chart_path, caption=f"{signal.method} Chart")

        return success

    def _format_trade_alert(self, signal: Any) -> str:
        """Format trade signal as Telegram message"""

        # Header
        icon = "🟢" if signal.bias.value == "Bullish" else "🔴"
        message = f"{icon} *{signal.method}* - *{signal.bias.value}* Signal\n"
        message += f"━━━━━━━━━━━━━━━━━\n\n"

        # Entry details
        message += f"📍 *Entry:* `{signal.entry_price:.2f}`\n"
        message += f"🛑 *Stop Loss:* `{signal.stop_loss:.2f}`\n"
        message += f"🎯 *Take Profit:* `{signal.take_profit:.2f}`\n"
        message += f"⏰ *Timeframe:* {signal.entry_timeframe}\n\n"

        # Risk/Reward
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        rr_ratio = reward / risk if risk > 0 else 0
        message += f"📊 *Risk:Reward:* 1:{rr_ratio:.2f}\n\n"

        # Confluence
        message += f"⭐ *Confluence Score:* {signal.confluence_score}\n"
        if signal.confluence_details:
            message += f"*Details:*\n"
            for detail in signal.confluence_details[:5]:  # Limit to 5 details
                message += f"  • {detail}\n"
        message += f"\n"

        # Method-specific details
        if signal.method == "Combined Method":
            if signal.aligned_timeframes:
                message += f"🔄 *Aligned TFs:* {', '.join(signal.aligned_timeframes)}\n"
            if signal.idm_present:
                message += f"✓ IDM Present\n"
            if signal.weekly_pullback:
                message += f"✓ Weekly Pullback Trade\n"

        elif signal.method == "Percentage Method":
            message += f"📐 *Daily Pullback:* {signal.daily_pullback_pct:.1f}%\n"
            message += f"📐 *H1 Pullback:* {signal.h1_pullback_pct:.1f}%\n"
            message += f"🎯 *Zone:* {signal.zone_type.title()}\n"

        elif signal.method == "Liquidity SAR Method":
            if signal.liquidity_swept:
                message += f"💧 *Liquidity:* {', '.join(signal.liquidity_swept)}\n"
            message += f"🎯 *SAR Level:* `{signal.fresh_sar_level:.2f}`\n"
            if signal.pattern_type:
                message += f"📈 *Pattern:* {signal.pattern_type.value} ({signal.pattern_strength})\n"
            message += f"🔹 *Entry Model:* {signal.entry_model}\n"

        # Timestamp
        message += f"\n⏱ {signal.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

        return message

    async def send_daily_summary(
        self,
        signals: List[Any],
        date: datetime
    ) -> bool:
        """
        Send daily summary

        Args:
            signals: List of signals from the day
            date: Summary date

        Returns:
            True if sent successfully
        """

        message = f"📅 *Daily Summary* - {date.strftime('%Y-%m-%d')}\n"
        message += f"━━━━━━━━━━━━━━━━━\n\n"

        if not signals:
            message += "No signals generated today.\n"
        else:
            # Group by method
            by_method = {}
            for signal in signals:
                method = signal.method
                if method not in by_method:
                    by_method[method] = []
                by_method[method].append(signal)

            message += f"*Total Signals:* {len(signals)}\n\n"

            for method, method_signals in by_method.items():
                message += f"*{method}:* {len(method_signals)} signals\n"

                bullish = sum(1 for s in method_signals if s.bias.value == "Bullish")
                bearish = len(method_signals) - bullish

                message += f"  🟢 Bullish: {bullish}\n"
                message += f"  🔴 Bearish: {bearish}\n\n"

            # Key levels for tomorrow
            message += f"\n*Key Levels for Tomorrow:*\n"
            message += f"(Update with current support/resistance)\n"

        return await self.send_message(message)

    async def send_weekly_recap(
        self,
        weekly_data: Dict[str, Any]
    ) -> bool:
        """
        Send weekly recap

        Args:
            weekly_data: Dictionary with weekly statistics

        Returns:
            True if sent successfully
        """

        message = f"📊 *Weekly Recap* - Week of {weekly_data.get('start_date', 'N/A')}\n"
        message += f"━━━━━━━━━━━━━━━━━\n\n"

        total_signals = weekly_data.get('total_signals', 0)
        message += f"*Total Signals:* {total_signals}\n\n"

        # By method
        if 'by_method' in weekly_data:
            message += f"*By Method:*\n"
            for method, count in weekly_data['by_method'].items():
                message += f"  • {method}: {count}\n"
            message += f"\n"

        # Performance metrics (if tracking)
        if 'win_rate' in weekly_data:
            message += f"*Performance:*\n"
            message += f"  • Win Rate: {weekly_data['win_rate']:.1f}%\n"
            message += f"  • Avg RR: 1:{weekly_data.get('avg_rr', 0):.2f}\n\n"

        # Major structure shifts
        if 'major_events' in weekly_data:
            message += f"*Major Structure Events:*\n"
            for event in weekly_data['major_events'][:3]:
                message += f"  • {event}\n"
            message += f"\n"

        # Key levels for next week
        message += f"*Key Levels for Next Week:*\n"
        message += f"(Weekly/Daily High-Low updates)\n"

        return await self.send_message(message)

    async def send_status_update(self, status: str) -> bool:
        """Send bot status update"""

        message = f"🤖 *Bot Status Update*\n\n{status}"
        return await self.send_message(message)

    async def send_error_alert(self, error: str) -> bool:
        """Send error alert"""

        message = f"⚠️ *Error Alert*\n\n```\n{error}\n```"
        return await self.send_message(message)

    def run_async(self, coro):
        """
        Run async coroutine in sync context

        Args:
            coro: Coroutine to run

        Returns:
            Result of coroutine
        """

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in an async context — create a new thread to run it
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=30)  # 30 second timeout
        else:
            # Create new event loop, run coroutine, and close it properly
            result = asyncio.run(coro)
            # Give time for cleanup
            import time
            time.sleep(0.1)
            return result

    def close(self):
        """Close Telegram bot connection"""
        try:
            if self.bot:
                # Close any pending HTTP connections
                import asyncio
                asyncio.run(self.bot.close())
        except Exception as e:
            logger.debug(f"Error closing bot: {e}")

    # Sync wrappers for convenience
    def send_message_sync(self, text: str) -> bool:
        """Sync wrapper for send_message"""
        return self.run_async(self.send_message(text))

    def send_trade_alert_sync(self, signal: Any, chart_path: Optional[str] = None) -> bool:
        """Sync wrapper for send_trade_alert"""
        return self.run_async(self.send_trade_alert(signal, chart_path))

    def send_daily_summary_sync(self, signals: List[Any], date: datetime) -> bool:
        """Sync wrapper for send_daily_summary"""
        return self.run_async(self.send_daily_summary(signals, date))

    def send_weekly_recap_sync(self, weekly_data: Dict[str, Any]) -> bool:
        """Sync wrapper for send_weekly_recap"""
        return self.run_async(self.send_weekly_recap(weekly_data))

    def send_status_update_sync(self, status: str) -> bool:
        """Sync wrapper for send_status_update"""
        return self.run_async(self.send_status_update(status))

    def send_error_alert_sync(self, error: str) -> bool:
        """Sync wrapper for send_error_alert"""
        return self.run_async(self.send_error_alert(error))
