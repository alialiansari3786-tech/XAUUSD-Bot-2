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

        For Combined Method: Second last swing break with body close preferred
        For Method 2: Valid Swing requires 2 candles liquidity + body close
        """

        events = []
        current_bias = Bias.NEUTRAL

        # Combine and sort all swings
        all_swings = sorted(
            swing_highs + swing_lows,
            key=lambda x: x.timestamp
        )

        for i in range(2, len(all_swings)):
            current_swing = all_swings[i]
            previous_swing = all_swings[i - 1]
            second_last_swing = all_swings[i - 2]

            # Check for bullish MSS (break above previous swing high)
            if not current_swing.is_high and previous_swing.is_high:
                # Find candles that broke above the swing high
                break_candles = df[
                    (df.index > previous_swing.timestamp) &
                    (df.index <= current_swing.timestamp) &
                    (df['Close'] > previous_swing.price)
                ]

                if not break_candles.empty:
                    # MSS confirmed with body close
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

                    current_bias = Bias.BULLISH

            # Check for bearish MSS (break below previous swing low)
            elif current_swing.is_high and not previous_swing.is_high:
                break_candles = df[
                    (df.index > previous_swing.timestamp) &
                    (df.index <= current_swing.timestamp) &
                    (df['Close'] < previous_swing.price)
                ]

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

                    current_bias = Bias.BEARISH

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
