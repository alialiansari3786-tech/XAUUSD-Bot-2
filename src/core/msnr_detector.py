"""
MSNR Detector Module
Malaysian Support and Resistance (MSNR): A&V/OCL levels, Quasimodo
(QM) levels, and the shared Fresh/Unfresh/Flip state machine that
governs all of them.

Reference: "The Alchemist - MSNR x SMC x ICT" (Yanu Emmanuel F).

LEVEL TYPES
-----------
A&V level: drawn from one candle's close to the next candle's open,
ignoring wicks. A bullish-candle-close -> bearish-candle-open forms an
'A' shape = resistance. A bearish-candle-close -> bullish-candle-open
forms a 'V' shape = support. This is the base SNR level.

OCL (Open-Close / Gap level): the SAME construction as an A&V level,
but specifically when the two prices don't overlap at all - a genuine
price gap, not just a close/open boundary. Every OCL is an A&V level;
not every A&V level is an OCL. Flagged via `is_ocl`.

QM level (Quasimodo): a head-and-shoulders-style swing sequence (Left
Shoulder -> Head beyond LS -> Right Shoulder back near LS) - the QML
is drawn at the Right Shoulder's level, which is what price is
expected to retest for entry.

FRESH / UNFRESH / FLIP (SBR / RBS)
-----------------------------------
1. A level starts fresh.
2. A wick-only touch (price enters the zone but candle closes back
   outside it) -> unfresh. Role unchanged.
3. A full-body close THROUGH the level -> it flips role (a broken
   support becomes resistance = SBR; a broken resistance becomes
   support = RBS). Not yet tradeable.
4. Price returns and touches the flipped level with only a wick (no
   second break) -> fresh again, now in its flipped role.

This mirrors the same touch/reject/break/re-fresh state machine
already used in sar_detector.py - extended here rather than
reimplemented, since it's the same underlying pattern.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from src.core.structure_detector import Bias, SwingPoint
from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger(__name__, settings.LOG_LEVEL)


class MSNRSource(Enum):
    """Where a level came from"""
    AV = "A&V"
    OCL = "OCL"
    QM = "QM"


@dataclass
class MSNRLevel:
    """A single MSNR level (A&V, OCL, or QM) with fresh/unfresh/flip tracking"""
    timestamp: pd.Timestamp
    timeframe: str
    source: MSNRSource
    level_type: str  # 'support' or 'resistance' (can flip)

    # Price zone - for a flat A&V level bottom==top; a true OCL gap has a range
    bottom: float
    top: float

    fresh: bool = True
    broken: bool = False
    is_ocl: bool = False

    touches: int = 0
    last_touch_time: Optional[pd.Timestamp] = None
    broken_time: Optional[pd.Timestamp] = None
    flip_count: int = 0

    @property
    def price(self) -> float:
        """Reference price for confluence/distance checks - midpoint of the zone"""
        return (self.bottom + self.top) / 2


class MSNRDetector:
    """Detects A&V/OCL and QM levels, and tracks fresh/unfresh/flip state"""

    def __init__(self):
        self.tracked_levels: Dict[str, List[MSNRLevel]] = {}

    # ------------------------------------------------------------------
    # A&V / OCL levels
    # ------------------------------------------------------------------

    def detect_av_levels(self, df: pd.DataFrame, timeframe: str) -> List[MSNRLevel]:
        """
        Detect A&V levels (and flag the OCL subset) from consecutive
        candle close-to-open pairs, then run the fresh/unfresh/flip
        state machine forward through the rest of the data.
        """

        levels = []

        for i in range(1, len(df)):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]

            prev_bullish = prev['Close'] > prev['Open']
            prev_bearish = prev['Close'] < prev['Open']

            if prev_bullish and curr['Close'] < curr['Open']:
                # bullish candle close -> bearish candle open = 'A' shape = resistance
                bottom = min(prev['Close'], curr['Open'])
                top = max(prev['Close'], curr['Open'])
                is_ocl = curr['Open'] > prev['Close']  # genuine gap up over this zone

                levels.append(MSNRLevel(
                    timestamp=df.index[i],
                    timeframe=timeframe,
                    source=MSNRSource.OCL if is_ocl else MSNRSource.AV,
                    level_type='resistance',
                    bottom=bottom,
                    top=top,
                    is_ocl=is_ocl
                ))

            elif prev_bearish and curr['Close'] > curr['Open']:
                # bearish candle close -> bullish candle open = 'V' shape = support
                bottom = min(prev['Close'], curr['Open'])
                top = max(prev['Close'], curr['Open'])
                is_ocl = curr['Open'] < prev['Close']  # genuine gap down over this zone

                levels.append(MSNRLevel(
                    timestamp=df.index[i],
                    timeframe=timeframe,
                    source=MSNRSource.OCL if is_ocl else MSNRSource.AV,
                    level_type='support',
                    bottom=bottom,
                    top=top,
                    is_ocl=is_ocl
                ))

        levels = self._update_freshness(levels, df)
        self.tracked_levels[f"{timeframe}_AV"] = levels

        logger.debug(f"Detected {len(levels)} A&V levels on {timeframe} ({sum(l.is_ocl for l in levels)} OCL)")
        return levels

    # ------------------------------------------------------------------
    # QM (Quasimodo) levels
    # ------------------------------------------------------------------

    def detect_qm_levels(
        self,
        df: pd.DataFrame,
        timeframe: str,
        lookback: int = 5
    ) -> List[MSNRLevel]:
        """
        Detect Quasimodo levels: a Left Shoulder -> Head (beyond LS) ->
        Right Shoulder (back near LS) swing sequence. The QML is drawn
        at the Right Shoulder's price - the retest zone for entry.
        """

        levels = []

        swing_highs = self._find_swing_points(df, lookback, 'high')
        swing_lows = self._find_swing_points(df, lookback, 'low')

        # Bearish QM: LS(high) -> Head(higher high) -> RS(lower high, near LS) -> sell
        for i in range(len(swing_highs) - 2):
            ls, head, rs = swing_highs[i], swing_highs[i + 1], swing_highs[i + 2]
            if head.price > ls.price and rs.price < head.price:
                # RS should be roughly back near LS level (within a loose band),
                # confirming the head-and-shoulders shape
                if abs(rs.price - ls.price) / ls.price * 100 <= 2.0:
                    levels.append(MSNRLevel(
                        timestamp=rs.timestamp,
                        timeframe=timeframe,
                        source=MSNRSource.QM,
                        level_type='resistance',
                        bottom=rs.price,
                        top=rs.price
                    ))

        # Bullish QM: LS(low) -> Head(lower low) -> RS(higher low, near LS) -> buy
        for i in range(len(swing_lows) - 2):
            ls, head, rs = swing_lows[i], swing_lows[i + 1], swing_lows[i + 2]
            if head.price < ls.price and rs.price > head.price:
                if abs(rs.price - ls.price) / ls.price * 100 <= 2.0:
                    levels.append(MSNRLevel(
                        timestamp=rs.timestamp,
                        timeframe=timeframe,
                        source=MSNRSource.QM,
                        level_type='support',
                        bottom=rs.price,
                        top=rs.price
                    ))

        levels = self._update_freshness(levels, df)
        self.tracked_levels[f"{timeframe}_QM"] = levels

        logger.debug(f"Detected {len(levels)} QM levels on {timeframe}")
        return levels

    def _find_swing_points(self, df: pd.DataFrame, lookback: int, point_type: str) -> List[SwingPoint]:
        """Shared swing-point finder (same pattern as structure_detector/pattern_detector)"""
        points = []
        col = 'High' if point_type == 'high' else 'Low'

        for i in range(lookback, len(df) - lookback):
            val = df[col].iloc[i]
            is_swing = True
            for j in range(1, lookback + 1):
                left = df[col].iloc[i - j]
                right = df[col].iloc[i + j]
                if point_type == 'high':
                    if left >= val or right >= val:
                        is_swing = False
                        break
                else:
                    if left <= val or right <= val:
                        is_swing = False
                        break
            if is_swing:
                points.append(SwingPoint(index=i, timestamp=df.index[i], price=val, is_high=(point_type == 'high')))

        return points

    # ------------------------------------------------------------------
    # Fresh / Unfresh / Flip state machine
    # ------------------------------------------------------------------

    def _update_freshness(self, levels: List[MSNRLevel], df: pd.DataFrame) -> List[MSNRLevel]:
        """
        Walk forward through price action after each level's formation:
        - wick-only touch -> unfresh
        - full-body close through -> broken, flips role
        - after a flip, a clean wick-only re-touch -> fresh again, in
          the new (flipped) role
        """

        for level in levels:
            future = df[df.index > level.timestamp]
            if future.empty:
                continue

            for idx, row in future.iterrows():
                touches_zone = row['Low'] <= level.top and row['High'] >= level.bottom

                if level.level_type == 'support':
                    if touches_zone:
                        level.touches += 1
                        level.last_touch_time = idx

                    # full body close below -> broken, flips to resistance
                    if row['Close'] < level.bottom and not level.broken:
                        level.fresh = False
                        level.broken = True
                        level.broken_time = idx
                        level.level_type = 'resistance'
                        level.flip_count += 1
                        continue

                    # after a flip, a clean wick-only re-touch makes it fresh again
                    if level.broken and touches_zone and row['Close'] >= level.bottom:
                        level.fresh = True
                    elif not level.broken and touches_zone:
                        level.fresh = False

                elif level.level_type == 'resistance':
                    if touches_zone:
                        level.touches += 1
                        level.last_touch_time = idx

                    if row['Close'] > level.top and not level.broken:
                        level.fresh = False
                        level.broken = True
                        level.broken_time = idx
                        level.level_type = 'support'
                        level.flip_count += 1
                        continue

                    if level.broken and touches_zone and row['Close'] <= level.top:
                        level.fresh = True
                    elif not level.broken and touches_zone:
                        level.fresh = False

        return levels

    def get_fresh_levels(
        self,
        timeframe: str,
        level_type: Optional[str] = None,
        source: Optional[MSNRSource] = None
    ) -> List[MSNRLevel]:
        """Get fresh MSNR levels (A&V/OCL + QM combined) for a timeframe"""

        all_levels = []
        for key in (f"{timeframe}_AV", f"{timeframe}_QM"):
            all_levels.extend(self.tracked_levels.get(key, []))

        fresh = [lv for lv in all_levels if lv.fresh]

        if level_type:
            fresh = [lv for lv in fresh if lv.level_type == level_type]
        if source:
            fresh = [lv for lv in fresh if lv.source == source]

        return fresh
