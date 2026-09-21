"""
Signal State Store
Persists the last signal sent per trading method so the bot doesn't
re-send an alert for the same underlying setup on every 15-minute scan.

DEDUP STRATEGY: exact match on the setup's own founding structural
event, not price or a time window. Both of those were tried first and
broke down: price matching (comparing entry/SL/TP within a tolerance)
missed real duplicates because a genuinely unchanged setup can still
see its entry/SL/TP drift several dollars per cycle - confirmed
directly from real Telegram alerts where ~15 consecutive "signals" for
the same method had identical confluence breakdowns and risk:reward
ratios but drifting prices. A fixed time-window cooldown is better but
still a blunt proxy - it either lets a duplicate through if the setup
outlives the window, or suppresses a genuinely new setup that happens
to form within it.

The actual fix: each method now stamps its signal's `timestamp` field
with the underlying structural event that founded the setup - the MSS
timestamp for Combined Method, the driving order block's own
timestamp for Percentage Method, the swept liquidity level's timestamp
for Liquidity MSNR Method (see each method's signal construction) -
rather than "now". That timestamp is exactly invariant for as long as
it's genuinely the same setup, and changes the instant a real new one
forms. So dedup here is just: same method, same bias, same timestamp
-> duplicate, no tolerance or window needed.

GitHub Actions runners are stateless: every run starts a brand-new
checkout with no memory of the previous run. To dedupe alerts across
runs, the last-sent setup's identity is written to a small JSON file.
The workflow commits that file back to the repo at the end of each run
(see .github/workflows/live-bot.yml), and the next run checks it out
fresh before deciding whether a new signal is actually new.
"""

import json
from typing import Any, Dict

from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

STATE_FILE = settings.BASE_DIR / 'state' / 'last_signals.json'


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


def _setup_key(signal: Any) -> str:
    """String form of the signal's founding-event timestamp, for exact comparison."""
    return str(signal.timestamp)


def is_duplicate(signal: Any) -> bool:
    """
    Check whether an alert for this exact setup (same method, same
    bias, same founding structural-event timestamp) was already sent.
    """
    state = _load_state()
    last = state.get(signal.method)

    if not last:
        return False

    bias = getattr(signal.bias, 'value', str(signal.bias))
    if bias != last.get('bias'):
        return False  # bias flipped - genuinely a different call

    return _setup_key(signal) == last.get('setup_key')


def record_sent(signal: Any) -> None:
    """Record this exact setup as alerted for its method."""
    state = _load_state()
    state[signal.method] = {
        'bias': getattr(signal.bias, 'value', str(signal.bias)),
        'setup_key': _setup_key(signal)
    }
    _save_state(state)


