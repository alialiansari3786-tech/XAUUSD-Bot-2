"""
Data Source Alert Tracker
Detects transitions in which data source is actually serving data
(saxo / twelve_data / yfinance) and reports when a Telegram alert
should fire - specifically:

  - Saxo fails, Twelve Data takes over -> alert once, telling you to
    check the Saxo developer portal
  - Twelve Data ALSO fails, yfinance (tertiary) takes over -> a
    separate, more urgent alert once, naming both failed sources
  - Recovery back to Saxo -> a brief "back to normal" note

This is edge-triggered (persisted via the same state/ git-commit
mechanism as everything else): without this, a multi-hour Saxo outage
would otherwise re-alert every single 15-minute cycle, which is noise
rather than signal.
"""

import json
from typing import Optional, Tuple

from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

STATE_FILE = settings.BASE_DIR / 'state' / 'data_source_alert_state.json'


def _load_last_source() -> Optional[str]:
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f).get('last_source')
    except (json.JSONDecodeError, OSError):
        return None


def _save_last_source(source: str) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump({'last_source': source}, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not persist data source alert state: {e}")


def check_for_alert(current_source: str) -> Optional[Tuple[str, str]]:
    """
    Call once per cycle with the "worst" (lowest-priority) source that
    was actually used this cycle across all timeframe fetches - i.e.
    if even one timeframe fell all the way back to yfinance, pass
    'yfinance'; else if any fell back to twelve_data, pass
    'twelve_data'; else pass 'saxo'.

    Returns (severity, message) if this represents a CHANGE from last
    cycle's recorded source worth alerting on, else None.
    """

    last_source = _load_last_source()

    if current_source == last_source:
        return None  # no change - don't re-alert

    _save_last_source(current_source)

    if last_source is None:
        # First run ever - just record the baseline, don't alert
        return None

    if current_source == 'yfinance':
        return (
            'critical',
            "⚠️ Both Saxo and Twelve Data have failed. "
            "Falling back to tertiary source: Yahoo Finance (GC=F futures, "
            "delayed) with PAXG-USD/XAUT-USD spot-basis correction. "
            "Please check both the Saxo developer portal and your Twelve Data "
            "account when possible."
        )

    if current_source == 'twelve_data':
        return (
            'warning',
            "⚠️ Saxo data source failed. Falling back to secondary source: "
            "Twelve Data. Please check the Saxo developer portal - your "
            "OAuth token may need re-authorization (run scripts/saxo_bootstrap.py)."
        )

    if current_source == 'saxo':
        return (
            'info',
            f"✅ Back to normal: Saxo is working again (was using {last_source})."
        )

    return None
