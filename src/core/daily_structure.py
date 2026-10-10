"""
Daily Structure (Method 2)
Finds the Daily trend direction and maps its structure.

Downtrend example (an uptrend is the exact mirror):
1. MSS: a body close below the swing low that started the last high.
2. Recent STH = highest point between that swing low and the MSS candle.
3. New STH confirmation point = lowest low since the MSS.
4. Fib: 1 = Recent STH, 0 = confirmation point (0, 0.25, 0.375, 0.5, 1).
5. If price pulls back up to at least 0.25 (a wick touch counts) and then
   body-closes below the confirmation point, the pullback high becomes the
   New Recent STH and the fib is redrawn on the new leg.
6. If price makes a new low before pulling back to 0.25, the confirmation
   point (and fib 0) moves down to that new low.
7. A body close above the Recent STH is the MSS for the upside and flips
   the trend. Then the same steps repeat in the other direction.

Used only for the Daily trend and the Daily zones. It sets no targets.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Optional

from src.core.structure_detector import Bias
from src.utils.timeframe_utils import get_lookback_periods
from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)

PULLBACK_FIB = 0.25
FIB_LEVELS = (0.0, 0.25, 0.375, 0.5, 1.0)


@dataclass
class DailyStructure:
    """Result of the Daily structure mapping"""
    valid: bool = False
    bias: Optional[Bias] = None

    mss_time: Optional[pd.Timestamp] = None

    # Fib "1": Recent STH in a downtrend, Recent STL in an uptrend
    recent_sth: Optional[float] = None
    recent_sth_time: Optional[pd.Timestamp] = None

    # Fib "0": New STH confirmation point (lowest low in a downtrend, highest high in an uptrend)
    confirmation: Optional[float] = None
    confirmation_time: Optional[pd.Timestamp] = None

    fib: Dict[str, float] = field(default_factory=dict)

    pullback_reached: bool = False   # has the current pullback touched 0.25
    pullback_pct: float = 0.0        # how far the pullback went, as a fraction of the leg


def analyze_daily_structure(
    df: pd.DataFrame,
    timeframe: str = 'D1',
    pullback_fib: float = PULLBACK_FIB
) -> DailyStructure:
    """
    Walk through the candles and return the current structure.
    Daily uses the default 0.25 pullback; 1H passes 0.375.
    """

    result = DailyStructure()
    n = len(df)
    if n < 30:
        return result

    lb = get_lookback_periods(timeframe)['swing']

    highs = df['High'].to_numpy(dtype=float)
    lows = df['Low'].to_numpy(dtype=float)
    closes = df['Close'].to_numpy(dtype=float)
    # space 0 = downtrend view; space 1 = the same data mirrored (uptrend view)
    spaces = [(highs, lows, closes), (-lows, -highs, -closes)]

    def swing_idx(arr):
        out = []
        for i in range(lb, n - lb):
            w = arr[i - lb:i + lb + 1]
            if arr[i] == w.max() and (w == arr[i]).sum() == 1:
                out.append(i)
        return out

    def find_seed(s):
        """Earliest MSS in this view: returns (mss_candle, swing_low_start) or None"""
        H, L, C = spaces[s]
        hs = swing_idx(H)
        ls = swing_idx(-L)
        best = None
        for k in range(1, len(hs)):
            h, ph = hs[k], hs[k - 1]
            if H[h] <= H[ph]:
                continue
            cand = [x for x in ls if ph < x < h]
            if not cand:
                continue
            a = min(cand, key=lambda x: L[x])
            broken = np.nonzero(C[a + 1:] < L[a])[0]
            if len(broken) == 0:
                continue
            b = a + 1 + int(broken[0])
            if b <= h:
                continue
            if best is None or b < best[0]:
                best = (b, a)
        return best

    seeds = []
    for s in (0, 1):
        r = find_seed(s)
        if r is not None:
            seeds.append((r[0], r[1], s))
    if not seeds:
        logger.debug("Daily structure: no MSS found in the available Daily candles")
        return result

    b, a, space = min(seeds)
    H, L, C = spaces[space]
    tp_idx = a + int(np.argmax(H[a:b + 1]))   # Recent STH
    mss_idx = b
    conf_idx = b                              # confirmation point (lowest low so far)
    pull_idx = None                           # highest high since the confirmation point

    for i in range(b + 1, n):
        H, L, C = spaces[space]

        # Body close beyond the Recent STH = MSS for the other side
        if C[i] > H[tp_idx]:
            space = 1 - space
            Ho = spaces[space][0]
            tp_idx = tp_idx + int(np.argmax(Ho[tp_idx:i + 1]))
            mss_idx = i
            conf_idx = i
            pull_idx = None
            continue

        if L[i] < L[conf_idx]:
            reached = False
            if pull_idx is not None:
                c = L[conf_idx]
                reached = H[pull_idx] >= c + pullback_fib * (H[tp_idx] - c)

            if reached:
                # Pullback reached 0.25 earlier: a body close below the
                # confirmation point forms the New Recent STH
                if C[i] < L[conf_idx]:
                    tp_idx = pull_idx
                    conf_idx = conf_idx + int(np.argmin(L[conf_idx:i + 1]))
                    pull_idx = None
            else:
                # No 0.25 pullback yet: the confirmation point moves to the new low
                conf_idx = i
                pull_idx = None
        else:
            if i > conf_idx and (pull_idx is None or H[i] > H[pull_idx]):
                pull_idx = i

    H, L, C = spaces[space]
    sign = 1.0 if space == 0 else -1.0
    sth_price = float(sign * H[tp_idx])
    conf_price = float(sign * L[conf_idx])

    result.valid = True
    result.bias = Bias.BEARISH if space == 0 else Bias.BULLISH
    result.mss_time = df.index[mss_idx]
    result.recent_sth = sth_price
    result.recent_sth_time = df.index[tp_idx]
    result.confirmation = conf_price
    result.confirmation_time = df.index[conf_idx]
    result.fib = {
        ('0' if f == 0.0 else '1' if f == 1.0 else str(f)): conf_price + f * (sth_price - conf_price)
        for f in FIB_LEVELS
    }

    if pull_idx is not None:
        leg = H[tp_idx] - L[conf_idx]
        if leg > 0:
            result.pullback_pct = float((H[pull_idx] - L[conf_idx]) / leg)
            result.pullback_reached = result.pullback_pct >= pullback_fib

    logger.info(
        f"{timeframe} structure: {result.bias.value} | MSS {result.mss_time} | "
        f"Recent STH/STL {sth_price:.2f} | Confirmation {conf_price:.2f} | "
        f"Pullback {result.pullback_pct * 100:.0f}%"
    )
    return result
