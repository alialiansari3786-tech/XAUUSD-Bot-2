"""
Bias Scheduler
Method 3 (Liquidity SAR) doesn't compute its own bias - it uses the
agreement between Combined Method's and Percentage Method's current
1H-confirmed bias, recalculated only twice a day (01:00 and 17:45 New
York time) and held constant between those checkpoints.

Persisted across runs the same way as the other state/ files (Monthly
cache, daily heartbeat, signal dedup) - GitHub Actions runners are
stateless, so "hold the same bias until the next checkpoint" means
writing it to a small file that gets committed back to the repo.
"""

import json
from datetime import datetime, timedelta, time as dtime
from typing import Optional, Dict
import pytz
import pandas as pd

from src.core.structure_detector import Bias
from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

STATE_FILE = settings.BASE_DIR / 'state' / 'bias_schedule.json'

NY_TZ = pytz.timezone('America/New_York')
CHECKPOINTS = [dtime(1, 0), dtime(17, 45)]  # 01:00 and 17:45 New York time, ascending


def _current_checkpoint_key(now_utc: Optional[datetime] = None) -> str:
    """
    Identify which checkpoint window 'now' falls into, as a stable
    string key (the most recent checkpoint at or before now, in New
    York time). The bias computed at that checkpoint stays valid until
    the next one.
    """
    if now_utc is None:
        now_utc = datetime.now(pytz.UTC)

    now_ny = now_utc.astimezone(NY_TZ)
    today = now_ny.date()

    checkpoints_today = [NY_TZ.localize(datetime.combine(today, t)) for t in CHECKPOINTS]
    passed = [cp for cp in checkpoints_today if cp <= now_ny]

    if passed:
        current = max(passed)
    else:
        # Before today's first checkpoint (01:00) -> still in yesterday's 17:45 window
        yesterday = today - timedelta(days=1)
        current = NY_TZ.localize(datetime.combine(yesterday, CHECKPOINTS[-1]))

    return current.strftime('%Y-%m-%dT%H:%M')


def _load_state() -> Dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read bias schedule state, will recompute: {e}")
        return {}


def _save_state(checkpoint_key: str, bias: Optional[Bias]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump({
                'checkpoint_key': checkpoint_key,
                'bias': bias.value if bias else None
            }, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not persist bias schedule state: {e}")


def get_shared_bias(
    combined_method,
    percentage_method,
    data: Dict[str, pd.DataFrame]
) -> Optional[Bias]:
    """
    Method 3's shared bias: agreement between Combined Method's and
    Percentage Method's current 1H-confirmed bias, recomputed once per
    checkpoint window (01:00 / 17:45 NY time) and cached for the rest
    of that window.

    Returns None if there's no agreement (methods disagree, or either
    has no current bias) - meaning Method 3 should not trade this window.
    """

    current_key = _current_checkpoint_key()
    state = _load_state()

    if state.get('checkpoint_key') == current_key:
        cached_bias = state.get('bias')
        logger.debug(f"Using cached bias from checkpoint {current_key}: {cached_bias}")
        return Bias(cached_bias) if cached_bias else None

    # New checkpoint window - recompute from both methods
    combined_bias = combined_method.get_current_bias(data)
    percentage_bias = percentage_method.get_current_bias(data)

    agreed_bias = combined_bias if (combined_bias is not None and combined_bias == percentage_bias) else None

    logger.info(
        f"Bias checkpoint {current_key}: Combined={combined_bias}, "
        f"Percentage={percentage_bias} -> agreed={agreed_bias}"
    )

    _save_state(current_key, agreed_bias)
    return agreed_bias
