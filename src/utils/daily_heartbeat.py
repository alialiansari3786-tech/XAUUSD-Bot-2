"""
Daily Heartbeat
Sends one Telegram status message per UTC calendar day (market open
or closed) so you can confirm the bot actually ran and Telegram
delivery works - independent of whether any method found a signal.

Without this, "no Telegram message" is ambiguous: it could mean
"ran fine, found nothing" or "something's broken and it never even
tried to send." The heartbeat rules that out every day regardless.

Like signal_state.py, this persists a tiny state file across the
otherwise-stateless GitHub Actions runs (see
.github/workflows/live-bot.yml's "Persist signal state" step, which
also commits this file back to the repo).
"""

import json
from datetime import datetime, timezone

from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

STATE_FILE = settings.BASE_DIR / 'state' / 'daily_heartbeat.json'


def _load_last_date() -> str:
    if not STATE_FILE.exists():
        return ''
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f).get('last_heartbeat_date', '')
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read heartbeat state file, starting fresh: {e}")
        return ''


def _save_last_date(date_str: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump({'last_heartbeat_date': date_str}, f, indent=2)


def should_send_heartbeat() -> bool:
    """True if today (UTC) hasn't had a heartbeat sent yet."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return _load_last_date() != today


def record_heartbeat_sent() -> None:
    """Mark today (UTC) as having had its heartbeat sent."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    _save_last_date(today)
