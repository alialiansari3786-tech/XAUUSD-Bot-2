"""
Signal State Store
Persists the last signal sent per trading method so the bot doesn't
re-send an alert for the same setup on every 15-minute scan.

GitHub Actions runners are stateless: every run starts a brand-new
checkout with no memory of the previous run. To dedupe alerts across
runs, the last-sent signal's key fields (bias, entry, stop-loss,
take-profit) are written to a small JSON file. The workflow commits
that file back to the repo at the end of each run (see
.github/workflows/live-bot.yml), and the next run checks it out fresh
before deciding whether a new signal is actually new.
"""

import json
from typing import Any, Dict

from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

STATE_FILE = settings.BASE_DIR / 'state' / 'last_signals.json'

# How close two signals' prices must be (in price units, e.g. USD for
# XAUUSD) to be treated as "the same setup" rather than a new signal.
PRICE_TOLERANCE = 0.50


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read signal state file, starting fresh: {e}")
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def _fingerprint(signal: Any) -> Dict[str, Any]:
    """The fields that define 'the same setup' for a given signal."""
    return {
        'bias': getattr(signal.bias, 'value', str(signal.bias)),
        'entry_price': round(float(signal.entry_price), 2) if signal.entry_price else None,
        'stop_loss': round(float(signal.stop_loss), 2) if signal.stop_loss else None,
        'take_profit': round(float(signal.take_profit), 2) if signal.take_profit else None,
    }


def is_duplicate(signal: Any) -> bool:
    """
    Check whether `signal` is effectively the same setup as the last
    one sent for its method: same bias, and entry/SL/TP all within
    PRICE_TOLERANCE of the last alert.
    """
    state = _load_state()
    last = state.get(signal.method)

    if not last:
        return False

    current = _fingerprint(signal)

    if current['bias'] != last.get('bias'):
        return False

    for key in ('entry_price', 'stop_loss', 'take_profit'):
        cur_val = current.get(key)
        last_val = last.get(key)
        if cur_val is None or last_val is None:
            return False
        if abs(cur_val - last_val) > PRICE_TOLERANCE:
            return False

    return True


def record_sent(signal: Any) -> None:
    """Record `signal` as the most recently sent alert for its method."""
    state = _load_state()
    state[signal.method] = _fingerprint(signal)
    _save_state(state)
