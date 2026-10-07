"""
Structure Detector Module
Detects market structure: MSS, CHoCH, CHoCH+, BOS, STL/STH tracking
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import setup_logger
from src.utils.timeframe_utils import get_lookback_periods
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


class StructureType(Enum):
    """Market structure types"""
    MSS = "MSS"  # Market Structure Shift
    BOS = "BOS"  # Break of Structure
    CHOCH = "CHoCH"  # Change of Character
    CHOCH_PLUS = "CHoCH+"  # Enhanced CHoCH


class Bias(Enum):
    """Market bias"""
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"


@dataclass
class SwingPoint:
    """Swing high/low point"""
    index: int
    timestamp: pd.Timestamp
    price: float
    is_high: bool  # True for swing high, False for swing low


@dataclass
class STLSTHLevel:
    """Short Term Low/High level"""
    stl: Optional[SwingPoint] = None  # Short Term Low
    sth: Optional[SwingPoint] = None  # Short Term High
    idm: Optional[SwingPoint] = None  # Inducement (minor swing)
    new_stl_confirmation: Optional[SwingPoint] = None
    trading_range_start: Optional[float] = None
    trading_range_end: Optional[float] = None
    trend: Optional[Bias] = None


@dataclass
class StructureEvent:
    """Market structure event"""
    type: StructureType
    bias: Bias
    timestamp: pd.Timestamp
    price: float
    broken_level: float
    internal: bool = False  # Internal vs Swing structure
    confirmation_index: Optional[int] = None


class StructureDetector:
    """Detects market structure shifts and patterns"""

    def __init__(self, swing_lookback: int = None, internal_lookback: int = None):
        """
        Initialize StructureDetector

        Args:
            swing_lookback: Lookback period for swing structure
            internal_lookback: Lookback period for internal structure
        """
        self.swing_lookback = swing_lookback or settings.SWING_LOOKBACK
        self.internal_lookback = internal_lookback or settings.INTERNAL_LOOKBACK

    def detect_structure(
        self,
        df: pd.DataFrame,
        timeframe: str = 'M15'
    ) -> List[StructureEvent]:
        """
        Detect all structure events in dataframe

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of structure events
        """

        # Get appropriate lookback periods for timeframe
        lookbacks = get_lookback_periods(timeframe)
        self.swing_lookback = lookbacks['swing']
        self.internal_lookback = lookbacks['internal']

        events = []

        # Detect swing highs and lows
        swing_highs = self._find_swing_highs(df, self.swing_lookback)
        swing_lows = self._find_swing_lows(df, self.swing_lookback)

        # Detect internal highs and lows
        internal_highs = self._find_swing_highs(df, self.internal_lookback)
        internal_lows = self._find_swing_lows(df, self.internal_lookback)

        # Detect MSS on swing structure
        mss_events = self._detect_mss(df, swing_highs, swing_lows, internal=False)
        events.extend(mss_events)

        # Detect CHoCH on swing structure
        choch_events = self._detect_choch(df, swing_highs, swing_lows)
        events.extend(choch_events)

        # Detect BOS on internal structure
        bos_events = self._detect_bos(df, internal_highs, internal_lows)
        events.extend(bos_events)

        # Sort by timestamp
        events.sort(key=lambda x: x.timestamp)

        logger.debug(f"Detected {len(events)} structure events on {timeframe}")
        return events

    def track_stl_sth(
        self,
        df: pd.DataFrame,
        timeframe: str = 'M15'
    ) -> STLSTHLevel:
        """
        Daily STH/STL tracking using the user's rules (downtrend shown,
        uptrend is the exact mirror): MSS swing point -> body close
        through it (MSS) -> Recent STH -> IDM (minor swing high) -> IDM
        taken (wick counts) -> New STH Confirmation Point (lowest low
        between IDM start and IDM taken) -> body close below it -> New
        Recent STH. A body close above the Recent STH = MSS for upside.
        """

        level = STLSTHLevel()
        n = len(df)
        if n < 30:
            return level

        swing_lb = get_lookback_periods(timeframe)['swing']
        minor_lb = 3

        highs = df['High'].to_numpy(dtype=float)
        lows = df['Low'].to_numpy(dtype=float)
        closes = df['Close'].to_numpy(dtype=float)
        # space 0 tracks the STH (downtrend); space 1 is its mirror (negated prices, tracks the STL)
        spaces = [(highs, lows, closes), (-lows, -highs, -closes)]

        def swings(arr, lb):
            out = []
            for i in range(lb, n - lb):
                w = arr[i - lb:i + lb + 1]
                if arr[i] == w.max() and (w == arr[i]).sum() == 1:
                    out.append(i)
            return out

        def find_seed(s):
            H, L, C = spaces[s]
            hs = swings(H, swing_lb)
            ls = swings(-L, swing_lb)
            best = None
            for k in range(1, len(hs)):
                h, ph = hs[k], hs[k - 1]
                if H[h] <= H[ph]:
                    continue
                cand = [x for x in ls if ph < x < h]
                if not cand:
                    continue
                a = min(cand, key=lambda x: L[x])  # leg start = MSS swing point B(a)
                broken = np.nonzero(C[a + 1:] < L[a])[0]
                if len(broken) == 0:
                    continue
                b = a + 1 + int(broken[0])  # MSS candle B(b)
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
            return level

        b, a, space = min(seeds)
        H, L, C = spaces[space]
        tp_idx = a + int(np.argmax(H[a:b + 1]))
        tp = H[tp_idx]
        idm, conf, taken, origin = None, None, False, b

        for i in range(b + 1, n):
            H, L, C = spaces[space]

            if C[i] > tp:  # body close beyond Recent STH = MSS for the other side
                space = 1 - space
                Ho = spaces[space][0]
                tp_idx = tp_idx + int(np.argmax(Ho[tp_idx:i + 1]))
                tp = Ho[tp_idx]
                idm, conf, taken, origin = None, None, False, i
                continue

            if not taken:
                j = i - minor_lb
                if j > origin:
                    w = H[j - minor_lb:j + minor_lb + 1]
                    if H[j] == w.max() and (w == H[j]).sum() == 1:
                        idm = j  # newest IDM wins
                if idm is not None and H[i] > H[idm]:  # wick counts
                    taken = True
                    conf = idm + int(np.argmin(L[idm:i + 1]))
            elif C[i] < L[conf]:  # body close through the confirmation point
                tp_idx = conf + int(np.argmax(H[conf:i + 1]))
                tp = H[tp_idx]
                idm, conf, taken, origin = None, None, False, i

        H, L, C = spaces[space]
        sign = 1.0 if space == 0 else -1.0
        is_hi = (space == 0)
        main = SwingPoint(tp_idx, df.index[tp_idx], float(sign * H[tp_idx]), is_hi)
        idm_pt = SwingPoint(idm, df.index[idm], float(sign * H[idm]), is_hi) if idm is not None else None
        conf_pt = SwingPoint(conf, df.index[conf], float(sign * L[conf]), not is_hi) if conf is not None else None

        if space == 0:
            level.sth = main
            level.trend = Bias.BEARISH
        else:
            level.stl = main
            level.trend = Bias.BULLISH
        level.idm = idm_pt
        level.new_stl_confirmation = conf_pt
        if conf_pt is not None:
            level.trading_range_start = main.price
            level.trading_range_end = conf_pt.price

        idm_txt = f"{idm_pt.price:.2f}" if idm_pt is not None else "none"
        conf_txt = f"{conf_pt.price:.2f}" if conf_pt is not None else "none"
        logger.info(
            f"{timeframe} structure: {level.trend.value} | Recent {'STH' if space == 0 else 'STL'} {main.price:.2f} | "
            f"IDM {idm_txt} | Confirmation point {conf_txt}"
        )
        return level

    def _track_stl_sth_old(
        self,
        df: pd.DataFrame,
        timeframe: str = 'M15'
    ) -> STLSTHLevel:
        """
        Track STL/STH levels with IDM identification (Combined Method)

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            STLSTHLevel with tracked levels
        """

        lookbacks = get_lookback_periods(timeframe)
        swing_lookback = lookbacks['swing']

        # Find swing points
        swing_highs = self._find_swing_highs(df, swing_lookback)
        swing_lows = self._find_swing_lows(df, swing_lookback)

        if not swing_lows or not swing_highs:
            return STLSTHLevel()

        # Get recent trend
        recent_closes = df['Close'].tail(20)
        trend_bullish = recent_closes.iloc[-1] > recent_closes.iloc[0]

        level = STLSTHLevel()

        if trend_bullish:
            # Find STL (most recent significant low)
            level.stl = swing_lows[-1] if swing_lows else None

            # Find IDM (minor swing low after STL, before new high)
            if len(swing_lows) > 1:
                potential_idm = [sl for sl in swing_lows[-5:] if level.stl and sl.price > level.stl.price]
                level.idm = potential_idm[-1] if potential_idm else None

            # Find New STL Confirmation Point (higher low that holds)
            if level.stl and len(swing_lows) > 2:
                confirmation_candidates = [
                    sl for sl in swing_lows
                    if sl.price > level.stl.price and sl.timestamp > level.stl.timestamp
                ]
                level.new_stl_confirmation = confirmation_candidates[-1] if confirmation_candidates else None

            # Define Trading Range
            if level.stl and level.new_stl_confirmation:
                level.trading_range_start = level.stl.price
                level.trading_range_end = level.new_stl_confirmation.price

        else:
            # Bearish: Track STH
            level.sth = swing_highs[-1] if swing_highs else None

            # Find IDM (minor swing high after STH, before new low)
            if len(swing_highs) > 1:
                potential_idm = [sh for sh in swing_highs[-5:] if level.sth and sh.price < level.sth.price]
                level.idm = potential_idm[-1] if potential_idm else None

            # Find New STH Confirmation Point
            if level.sth and len(swing_highs) > 2:
                confirmation_candidates = [
                    sh for sh in swing_highs
                    if sh.price < level.sth.price and sh.timestamp > level.sth.timestamp
                ]
                level.new_stl_confirmation = confirmation_candidates[-1] if confirmation_candidates else None

            # Define Trading Range
            if level.sth and level.new_stl_confirmation:
                level.trading_range_start = level.sth.price
                level.trading_range_end = level.new_stl_confirmation.price

        return level

    def _find_swing_highs(self, df: pd.DataFrame, lookback: int) -> List[SwingPoint]:
        """Find swing high points"""
        swing_highs = []

        for i in range(lookback, len(df) - lookback):
            high = df['High'].iloc[i]
            is_swing_high = True

            # Check left side
            for j in range(1, lookback + 1):
                if df['High'].iloc[i - j] >= high:
                    is_swing_high = False
                    break

            # Check right side
            if is_swing_high:
                for j in range(1, lookback + 1):
                    if df['High'].iloc[i + j] >= high:
                        is_swing_high = False
                        break

            if is_swing_high:
                swing_highs.append(SwingPoint(
                    index=i,
                    timestamp=df.index[i],
                    price=high,
                    is_high=True
                ))

        return swing_highs

    def _find_swing_lows(self, df: pd.DataFrame, lookback: int) -> List[SwingPoint]:
        """Find swing low points"""
        swing_lows = []

        for i in range(lookback, len(df) - lookback):
            low = df['Low'].iloc[i]
            is_swing_low = True

            # Check left side
            for j in range(1, lookback + 1):
                if df['Low'].iloc[i - j] <= low:
                    is_swing_low = False
                    break

            # Check right side
            if is_swing_low:
                for j in range(1, lookback + 1):
                    if df['Low'].iloc[i + j] <= low:
                        is_swing_low = False
                        break

            if is_swing_low:
                swing_lows.append(SwingPoint(
                    index=i,
                    timestamp=df.index[i],
                    price=low,
                    is_high=False
                ))

        return swing_lows

    def _detect_mss(
        self,
        df: pd.DataFrame,
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint],
        internal: bool = False
    ) -> List[StructureEvent]:
        """
        Detect Market Structure Shift (MSS)

        A bullish MSS = after a swing LOW confirms (a lower low during
        a downtrend), price later closes back ABOVE the swing HIGH
        that preceded that low - the last lower high gets broken,
        signalling a reversal. Bearish MSS is the mirror: after a
        swing HIGH confirms, price later closes back BELOW the swing
        LOW that preceded it.

        BUG FIX: this used to search for the break candle in the
        window BETWEEN a swing and the one immediately before it -
        which is the leg leading INTO that swing, before any reversal
        has happened yet, not the leg AFTER it where a genuine break
        would actually occur. That made real MSS events almost
        undetectable: confirmed on a clean synthetic reversal pattern
        (lower high -> lower low -> strong break back above the prior
        high), the old code found zero MSS events. This version
        searches forward from the confirming swing to the end of the
        available data for the first close that breaks the prior
        opposite-type swing's price.
        """

        events = []

        # Combine and sort all swings
        all_swings = sorted(
            swing_highs + swing_lows,
            key=lambda x: x.timestamp
        )

        for i in range(1, len(all_swings)):
            current_swing = all_swings[i]
            previous_swing = all_swings[i - 1]

            # Bullish MSS: swing low confirmed after a swing high ->
            # look forward from the low for a close back above that high
            if not current_swing.is_high and previous_swing.is_high:
                window = df[df.index > current_swing.timestamp]
                break_candles = window[window['Close'] > previous_swing.price]

                if not break_candles.empty:
                    break_index = break_candles.index[0]
                    break_candle = df.loc[break_index]

                    events.append(StructureEvent(
                        type=StructureType.MSS,
                        bias=Bias.BULLISH,
                        timestamp=break_index,
                        price=break_candle['Close'],
                        broken_level=previous_swing.price,
                        internal=internal,
                        confirmation_index=current_swing.index
                    ))

            # Bearish MSS: swing high confirmed after a swing low ->
            # look forward from the high for a close back below that low
            elif current_swing.is_high and not previous_swing.is_high:
                window = df[df.index > current_swing.timestamp]
                break_candles = window[window['Close'] < previous_swing.price]

                if not break_candles.empty:
                    break_index = break_candles.index[0]
                    break_candle = df.loc[break_index]

                    events.append(StructureEvent(
                        type=StructureType.MSS,
                        bias=Bias.BEARISH,
                        timestamp=break_index,
                        price=break_candle['Close'],
                        broken_level=previous_swing.price,
                        internal=internal,
                        confirmation_index=current_swing.index
                    ))

        return events

    def _detect_choch(
        self,
        df: pd.DataFrame,
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint]
    ) -> List[StructureEvent]:
        """Detect Change of Character (CHoCH)"""

        events = []
        current_trend = None

        # Determine initial trend from first few swings
        if len(swing_lows) > 1 and len(swing_highs) > 1:
            if swing_lows[-1].price > swing_lows[-2].price:
                current_trend = Bias.BULLISH
            else:
                current_trend = Bias.BEARISH

        all_swings = sorted(swing_highs + swing_lows, key=lambda x: x.timestamp)

        for i in range(1, len(all_swings)):
            current = all_swings[i]
            previous = all_swings[i - 1]

            # Bullish CHoCH: In downtrend, break above previous swing high
            if current_trend == Bias.BEARISH and current.is_high and not previous.is_high:
                if current.price > max([sh.price for sh in swing_highs[:i] if sh.timestamp < current.timestamp], default=0):
                    # Check if previous swing low was taken (CHoCH+)
                    taken_previous = False
                    if i > 1:
                        prev_low = all_swings[i - 1]
                        if not prev_low.is_high:
                            # Check if price went below this low
                            df_segment = df[(df.index > prev_low.timestamp) & (df.index <= current.timestamp)]
                            if not df_segment.empty and df_segment['Low'].min() < prev_low.price:
                                taken_previous = True

                    event_type = StructureType.CHOCH_PLUS if taken_previous else StructureType.CHOCH

                    events.append(StructureEvent(
                        type=event_type,
                        bias=Bias.BULLISH,
                        timestamp=current.timestamp,
                        price=current.price,
                        broken_level=previous.price,
                        internal=False
                    ))

                    current_trend = Bias.BULLISH

            # Bearish CHoCH: In uptrend, break below previous swing low
            elif current_trend == Bias.BULLISH and not current.is_high and previous.is_high:
                if current.price < min([sl.price for sl in swing_lows[:i] if sl.timestamp < current.timestamp], default=float('inf')):
                    taken_previous = False
                    if i > 1:
                        prev_high = all_swings[i - 1]
                        if prev_high.is_high:
                            df_segment = df[(df.index > prev_high.timestamp) & (df.index <= current.timestamp)]
                            if not df_segment.empty and df_segment['High'].max() > prev_high.price:
                                taken_previous = True

                    event_type = StructureType.CHOCH_PLUS if taken_previous else StructureType.CHOCH

                    events.append(StructureEvent(
                        type=event_type,
                        bias=Bias.BEARISH,
                        timestamp=current.timestamp,
                        price=current.price,
                        broken_level=previous.price,
                        internal=False
                    ))

                    current_trend = Bias.BEARISH

        return events

    def _detect_bos(
        self,
        df: pd.DataFrame,
        internal_highs: List[SwingPoint],
        internal_lows: List[SwingPoint]
    ) -> List[StructureEvent]:
        """Detect Break of Structure (BOS) - continuation pattern"""

        events = []

        # Similar to MSS but indicates continuation
        # Bullish BOS: Break above previous high in uptrend
        # Bearish BOS: Break below previous low in downtrend

        all_swings = sorted(internal_highs + internal_lows, key=lambda x: x.timestamp)

        for i in range(2, len(all_swings)):
            current = all_swings[i]
            previous = all_swings[i - 1]

            # Bullish BOS
            if current.is_high and previous.is_high:
                if current.price > previous.price:
                    events.append(StructureEvent(
                        type=StructureType.BOS,
                        bias=Bias.BULLISH,
                        timestamp=current.timestamp,
                        price=current.price,
                        broken_level=previous.price,
                        internal=True
                    ))

            # Bearish BOS
            elif not current.is_high and not previous.is_high:
                if current.price < previous.price:
                    events.append(StructureEvent(
                        type=StructureType.BOS,
                        bias=Bias.BEARISH,
                        timestamp=current.timestamp,
                        price=current.price,
                        broken_level=previous.price,
                        internal=True
                    ))

        return events

    def get_current_bias(self, events: List[StructureEvent]) -> Bias:
        """Get current market bias from recent structure events"""

        if not events:
            return Bias.NEUTRAL

        # Look at last 3 events
        recent_events = events[-3:]

        bullish_count = sum(1 for e in recent_events if e.bias == Bias.BULLISH)
        bearish_count = sum(1 for e in recent_events if e.bias == Bias.BEARISH)

        if bullish_count > bearish_count:
            return Bias.BULLISH
        elif bearish_count > bullish_count:
            return Bias.BEARISH
        else:
            return Bias.NEUTRAL
