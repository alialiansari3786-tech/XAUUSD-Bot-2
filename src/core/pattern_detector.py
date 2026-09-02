"""
Pattern Detector Module
Detects W/M patterns with Strong vs Weak classification
"""

import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import setup_logger
from src.core.structure_detector import Bias, SwingPoint
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


class PatternType(Enum):
    """Pattern types"""
    STRONG_W = "Strong W"
    WEAK_W = "Weak W"
    STRONG_M = "Strong M"
    WEAK_M = "Weak M"


@dataclass
class Pattern:
    """Chart pattern representation"""
    pattern_type: PatternType
    timestamp: pd.Timestamp
    timeframe: str
    bias: Bias

    # Pattern points
    point_1: float  # First low/high
    point_2: float  # Middle high/low
    point_3: float  # Second low/high
    point_4: Optional[float] = None  # Breakout point

    # Liquidity tracking
    liquidity_taken: bool = False
    liquidity_level: Optional[float] = None

    # Confluence
    at_fresh_level: bool = False
    fresh_level_price: Optional[float] = None


class PatternDetector:
    """Detects W and M patterns with Strong/Weak classification"""

    def __init__(self):
        """Initialize PatternDetector"""
        self.detected_patterns: Dict[str, List[Pattern]] = {}

    def detect_w_patterns(
        self,
        df: pd.DataFrame,
        timeframe: str,
        swing_lookback: int = 5
    ) -> List[Pattern]:
        """
        Detect W patterns (bullish reversal)

        Strong W: Takes liquidity below first low before reversing
        Weak W: Does not take liquidity below first low

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            swing_lookback: Lookback for swing detection

        Returns:
            List of W patterns
        """

        patterns = []

        # Find swing lows and highs
        swing_lows = self._find_swing_points(df, swing_lookback, point_type='low')
        swing_highs = self._find_swing_points(df, swing_lookback, point_type='high')

        if len(swing_lows) < 2 or len(swing_highs) < 1:
            return patterns

        # Look for W pattern formation
        # W pattern: Low1 -> High -> Low2 -> Higher High
        for i in range(len(swing_lows) - 1):
            low1 = swing_lows[i]

            # Find high after low1
            highs_after_low1 = [h for h in swing_highs if h['timestamp'] > low1['timestamp']]
            if not highs_after_low1:
                continue

            middle_high = highs_after_low1[0]

            # Find low2 after middle_high
            lows_after_high = [l for l in swing_lows if l['timestamp'] > middle_high['timestamp']]
            if not lows_after_high:
                continue

            low2 = lows_after_high[0]

            # Check if pattern forms W shape (low2 should be around low1 level)
            # Allow low2 to be slightly lower (for Strong W) or slightly higher
            price_diff_pct = abs(low2['price'] - low1['price']) / low1['price'] * 100

            if price_diff_pct > 2.0:  # More than 2% difference, not a W
                continue

            # Determine if Strong W or Weak W
            # Strong W: low2 takes liquidity below low1
            if low2['price'] < low1['price']:
                pattern_type = PatternType.STRONG_W
                liquidity_taken = True
                liquidity_level = low1['price']
            else:
                pattern_type = PatternType.WEAK_W
                liquidity_taken = False
                liquidity_level = None

            # Check for breakout (price breaking above middle_high)
            breakout_data = df[df.index > low2['timestamp']]
            breakout_point = None

            for idx, row in breakout_data.iterrows():
                if row['Close'] > middle_high['price']:
                    breakout_point = row['Close']
                    break

            # Create pattern
            pattern = Pattern(
                pattern_type=pattern_type,
                timestamp=low2['timestamp'],
                timeframe=timeframe,
                bias=Bias.BULLISH,
                point_1=low1['price'],
                point_2=middle_high['price'],
                point_3=low2['price'],
                point_4=breakout_point,
                liquidity_taken=liquidity_taken,
                liquidity_level=liquidity_level
            )

            patterns.append(pattern)

        logger.debug(f"Detected {len(patterns)} W patterns on {timeframe}")
        return patterns

    def detect_m_patterns(
        self,
        df: pd.DataFrame,
        timeframe: str,
        swing_lookback: int = 5
    ) -> List[Pattern]:
        """
        Detect M patterns (bearish reversal)

        Strong M: Takes liquidity above first high before reversing
        Weak M: Does not take liquidity above first high

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            swing_lookback: Lookback for swing detection

        Returns:
            List of M patterns
        """

        patterns = []

        # Find swing highs and lows
        swing_highs = self._find_swing_points(df, swing_lookback, point_type='high')
        swing_lows = self._find_swing_points(df, swing_lookback, point_type='low')

        if len(swing_highs) < 2 or len(swing_lows) < 1:
            return patterns

        # Look for M pattern formation
        # M pattern: High1 -> Low -> High2 -> Lower Low
        for i in range(len(swing_highs) - 1):
            high1 = swing_highs[i]

            # Find low after high1
            lows_after_high1 = [l for l in swing_lows if l['timestamp'] > high1['timestamp']]
            if not lows_after_high1:
                continue

            middle_low = lows_after_high1[0]

            # Find high2 after middle_low
            highs_after_low = [h for h in swing_highs if h['timestamp'] > middle_low['timestamp']]
            if not highs_after_low:
                continue

            high2 = highs_after_low[0]

            # Check if pattern forms M shape
            price_diff_pct = abs(high2['price'] - high1['price']) / high1['price'] * 100

            if price_diff_pct > 2.0:
                continue

            # Determine if Strong M or Weak M
            # Strong M: high2 takes liquidity above high1
            if high2['price'] > high1['price']:
                pattern_type = PatternType.STRONG_M
                liquidity_taken = True
                liquidity_level = high1['price']
            else:
                pattern_type = PatternType.WEAK_M
                liquidity_taken = False
                liquidity_level = None

            # Check for breakdown (price breaking below middle_low)
            breakdown_data = df[df.index > high2['timestamp']]
            breakdown_point = None

            for idx, row in breakdown_data.iterrows():
                if row['Close'] < middle_low['price']:
                    breakdown_point = row['Close']
                    break

            # Create pattern
            pattern = Pattern(
                pattern_type=pattern_type,
                timestamp=high2['timestamp'],
                timeframe=timeframe,
                bias=Bias.BEARISH,
                point_1=high1['price'],
                point_2=middle_low['price'],
                point_3=high2['price'],
                point_4=breakdown_point,
                liquidity_taken=liquidity_taken,
                liquidity_level=liquidity_level
            )

            patterns.append(pattern)

        logger.debug(f"Detected {len(patterns)} M patterns on {timeframe}")
        return patterns

    def _find_swing_points(
        self,
        df: pd.DataFrame,
        lookback: int,
        point_type: str
    ) -> List[Dict]:
        """
        Find swing points (highs or lows)

        Args:
            df: OHLCV DataFrame
            lookback: Lookback period
            point_type: 'high' or 'low'

        Returns:
            List of swing points with price and timestamp
        """

        points = []

        if point_type == 'high':
            price_col = 'High'
            comparison = lambda i, j: df[price_col].iloc[i - j] < df[price_col].iloc[i] and \
                                      df[price_col].iloc[i + j] < df[price_col].iloc[i]
        else:
            price_col = 'Low'
            comparison = lambda i, j: df[price_col].iloc[i - j] > df[price_col].iloc[i] and \
                                      df[price_col].iloc[i + j] > df[price_col].iloc[i]

        for i in range(lookback, len(df) - lookback):
            is_swing = True

            for j in range(1, lookback + 1):
                if not comparison(i, j):
                    is_swing = False
                    break

            if is_swing:
                points.append({
                    'price': df[price_col].iloc[i],
                    'timestamp': df.index[i],
                    'index': i
                })

        return points

    def check_pattern_at_fresh_level(
        self,
        pattern: Pattern,
        fresh_levels: List,
        tolerance_pct: float = 0.2
    ) -> bool:
        """
        Check if pattern formed at a fresh SAR level

        Args:
            pattern: Pattern to check
            fresh_levels: List of fresh SAR levels
            tolerance_pct: Price tolerance

        Returns:
            True if at fresh level
        """

        # Check the reversal point (point_3 for W, point_3 for M)
        reversal_price = pattern.point_3

        for level in fresh_levels:
            price_diff_pct = abs(reversal_price - level.price) / level.price * 100

            if price_diff_pct <= tolerance_pct:
                # Pattern at fresh level
                pattern.at_fresh_level = True
                pattern.fresh_level_price = level.price
                return True

        return False

    def get_recent_patterns(
        self,
        timeframe: str,
        pattern_type: Optional[PatternType] = None,
        lookback_candles: int = 20
    ) -> List[Pattern]:
        """
        Get recent patterns

        Args:
            timeframe: Timeframe to query
            pattern_type: Optional filter by pattern type
            lookback_candles: How far back to look

        Returns:
            List of recent patterns
        """

        if timeframe not in self.detected_patterns:
            return []

        patterns = self.detected_patterns[timeframe]

        if pattern_type:
            patterns = [p for p in patterns if p.pattern_type == pattern_type]

        # Return most recent patterns
        return patterns[-lookback_candles:]

    def validate_pattern_completion(
        self,
        pattern: Pattern,
        df: pd.DataFrame
    ) -> bool:
        """
        Validate if pattern has completed (breakout occurred)

        Args:
            pattern: Pattern to validate
            df: Current price data

        Returns:
            True if pattern completed
        """

        if pattern.point_4 is not None:
            return True

        # Check current price data for breakout
        recent_data = df[df.index > pattern.timestamp].tail(10)

        if recent_data.empty:
            return False

        if pattern.bias == Bias.BULLISH:
            # W pattern: Check if broke above point_2
            if recent_data['Close'].max() > pattern.point_2:
                return True

        elif pattern.bias == Bias.BEARISH:
            # M pattern: Check if broke below point_2
            if recent_data['Close'].min() < pattern.point_2:
                return True

        return False

    def calculate_pattern_strength(self, pattern: Pattern) -> Dict:
        """
        Calculate pattern strength score

        Args:
            pattern: Pattern to score

        Returns:
            Dictionary with strength metrics
        """

        score = 0
        details = []

        # Strong pattern type
        if pattern.pattern_type in [PatternType.STRONG_W, PatternType.STRONG_M]:
            score += 3
            details.append("Strong pattern (liquidity taken) (+3)")
        else:
            score += 1
            details.append("Weak pattern (+1)")

        # At fresh level
        if pattern.at_fresh_level:
            score += 2
            details.append("At fresh S/R level (+2)")

        # Breakout confirmed
        if pattern.point_4 is not None:
            score += 2
            details.append("Breakout confirmed (+2)")

        # Determine overall strength
        if score >= 6:
            strength = "Very Strong"
        elif score >= 4:
            strength = "Strong"
        elif score >= 2:
            strength = "Moderate"
        else:
            strength = "Weak"

        return {
            'score': score,
            'strength': strength,
            'details': details
        }
