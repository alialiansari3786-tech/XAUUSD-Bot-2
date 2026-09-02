"""
Smart Money Concepts Indicator Module
Implements ICT-style smart money concepts with premium/discount zones
Features: Standard OBs, FVG with auto-threshold, Premium/Discount zones, Strong/Weak High/Low labels
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import setup_logger
from src.core.structure_detector import StructureDetector, Bias, StructureType
from src.core.order_block_detector import OrderBlockDetector
from src.core.fvg_detector import FVGDetector
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


class ZoneType(Enum):
    """Premium/Discount zone types"""
    PREMIUM = "Premium"  # 95-100%
    EQUILIBRIUM = "Equilibrium"  # 47.5-52.5%
    DISCOUNT = "Discount"  # 0-5%
    NEUTRAL = "Neutral"  # Everything else


class SwingStrength(Enum):
    """Swing high/low strength classification"""
    STRONG_HIGH = "Strong High"
    WEAK_HIGH = "Weak High"
    STRONG_LOW = "Strong Low"
    WEAK_LOW = "Weak Low"


@dataclass
class PremiumDiscountZone:
    """Premium/Discount zone representation"""
    zone_type: ZoneType
    high: float
    low: float
    range_high: float  # Full range high
    range_low: float   # Full range low
    percentage: float  # Position in range (0-100%)


@dataclass
class SwingLabel:
    """Labeled swing high/low with strength classification"""
    timestamp: pd.Timestamp
    price: float
    strength: SwingStrength
    is_high: bool
    confirmation_bars: int  # How many bars confirmed this swing


@dataclass
class SmartMoneyOrderBlock:
    """Standard ICT-style Order Block"""
    timestamp: pd.Timestamp
    high: float
    low: float
    bias: Bias
    timeframe: str
    candle_type: str  # "Last down before up" or "Last up before down"
    tested: bool = False
    strength_score: float = 0.0  # Based on volume and displacement


@dataclass
class SmartMoneyFVG:
    """Fair Value Gap with auto-threshold"""
    timestamp: pd.Timestamp
    high: float
    low: float
    bias: Bias
    timeframe: str
    gap_size: float
    gap_percentage: float  # % of bar delta
    mitigated: bool = False
    mitigation_percentage: float = 0.0


class SmartMoneyConcepts:
    """
    Smart Money Concepts Indicator

    Implements ICT-style analysis:
    - Standard Order Blocks (last opposite candle before displacement)
    - FVG with auto-threshold (bar delta percentage)
    - Premium/Discount zones (95-100% / 47.5-52.5% / 0-5%)
    - Structure detection (historical vs present mode)
    - Strong/Weak High/Low labels
    """

    def __init__(
        self,
        fvg_threshold_pct: float = 0.05,
        ob_confirmation_bars: int = 3,
        swing_lookback: int = 5,
        mode: str = 'present'
    ):
        """
        Initialize Smart Money Concepts indicator

        Args:
            fvg_threshold_pct: Minimum FVG size as % of bar range (default 5%)
            ob_confirmation_bars: Bars needed to confirm OB (default 3)
            swing_lookback: Lookback for swing detection (default 5)
            mode: 'historical' or 'present' - affects structure detection sensitivity
        """
        self.fvg_threshold_pct = fvg_threshold_pct
        self.ob_confirmation_bars = ob_confirmation_bars
        self.swing_lookback = swing_lookback
        self.mode = mode

        # Initialize detectors
        self.structure_detector = StructureDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg_detector = FVGDetector()

        logger.info(f"Smart Money Concepts initialized (Mode: {mode}, FVG threshold: {fvg_threshold_pct}%)")

    def analyze(
        self,
        df: pd.DataFrame,
        timeframe: str = 'M15',
        range_high: Optional[float] = None,
        range_low: Optional[float] = None
    ) -> Dict[str, any]:
        """
        Perform complete Smart Money Concepts analysis

        Args:
            df: OHLCV DataFrame
            timeframe: Timeframe string
            range_high: Optional high for premium/discount calculation
            range_low: Optional low for premium/discount calculation

        Returns:
            Dictionary containing all SMC analysis results
        """
        logger.info(f"Running Smart Money Concepts analysis on {timeframe} ({len(df)} bars)")

        # 1. Detect standard order blocks
        order_blocks = self._detect_standard_obs(df, timeframe)

        # 2. Detect FVGs with auto-threshold
        fvgs = self._detect_smart_fvgs(df, timeframe)

        # 3. Calculate Premium/Discount zones
        if range_high is None or range_low is None:
            range_high = df['High'].max()
            range_low = df['Low'].min()

        pd_zones = self._calculate_premium_discount_zones(
            df['Close'].iloc[-1],
            range_high,
            range_low
        )

        # 4. Detect structure (with mode consideration)
        structure_events = self._detect_structure_with_mode(df, timeframe)

        # 5. Label swing highs/lows with strength
        swing_labels = self._label_swing_strength(df, timeframe)

        # 6. Determine current market bias
        current_bias = self._determine_current_bias(df, structure_events)

        results = {
            'order_blocks': order_blocks,
            'fvgs': fvgs,
            'premium_discount_zones': pd_zones,
            'structure_events': structure_events,
            'swing_labels': swing_labels,
            'current_bias': current_bias,
            'range_high': range_high,
            'range_low': range_low,
            'current_price': df['Close'].iloc[-1],
            'timeframe': timeframe,
            'mode': self.mode
        }

        logger.info(f"SMC analysis complete: {len(order_blocks)} OBs, {len(fvgs)} FVGs, "
                   f"{len(swing_labels)} swing labels, Bias: {current_bias.value}")

        return results

    def _detect_standard_obs(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> List[SmartMoneyOrderBlock]:
        """
        Detect standard ICT-style order blocks
        Last opposite candle before strong displacement

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of Smart Money order blocks
        """
        obs = []

        for i in range(2, len(df) - 1):
            prev2 = df.iloc[i - 2]
            prev1 = df.iloc[i - 1]
            curr = df.iloc[i]

            # Calculate displacement strength
            prev1_body = abs(prev1['Close'] - prev1['Open'])
            prev1_range = prev1['High'] - prev1['Low']
            curr_body = abs(curr['Close'] - curr['Open'])
            curr_range = curr['High'] - curr['Low']

            # Bullish OB: Last bearish candle before bullish displacement
            is_bullish_ob = (
                prev1['Close'] < prev1['Open'] and  # Previous is bearish
                curr['Close'] > curr['Open'] and    # Current is bullish
                curr_body > 1.5 * prev1_body and    # Strong displacement
                curr['Close'] > prev1['High']       # Breaks previous high
            )

            # Bearish OB: Last bullish candle before bearish displacement
            is_bearish_ob = (
                prev1['Close'] > prev1['Open'] and  # Previous is bullish
                curr['Close'] < curr['Open'] and    # Current is bearish
                curr_body > 1.5 * prev1_body and    # Strong displacement
                curr['Close'] < prev1['Low']        # Breaks previous low
            )

            if is_bullish_ob or is_bearish_ob:
                # Calculate strength score
                volume_ratio = df['Volume'].iloc[i] / df['Volume'].iloc[max(0, i-20):i].mean()
                displacement_ratio = curr_body / prev1_body
                strength_score = min(100, (volume_ratio + displacement_ratio) * 25)

                ob = SmartMoneyOrderBlock(
                    timestamp=df.index[i - 1],
                    high=prev1['High'],
                    low=prev1['Low'],
                    bias=Bias.BULLISH if is_bullish_ob else Bias.BEARISH,
                    timeframe=timeframe,
                    candle_type="Last down before up" if is_bullish_ob else "Last up before down",
                    tested=False,
                    strength_score=strength_score
                )
                obs.append(ob)

        # Check if OBs have been tested
        current_price = df['Close'].iloc[-1]
        for ob in obs:
            if ob.bias == Bias.BULLISH:
                # Bullish OB tested if price revisited the zone
                ob.tested = any(
                    df['Low'].iloc[df.index > ob.timestamp] <= ob.high
                )
            else:
                # Bearish OB tested if price revisited the zone
                ob.tested = any(
                    df['High'].iloc[df.index > ob.timestamp] >= ob.low
                )

        return obs

    def _detect_smart_fvgs(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> List[SmartMoneyFVG]:
        """
        Detect Fair Value Gaps with auto-threshold based on bar delta percentage

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of Smart Money FVGs
        """
        fvgs = []

        for i in range(1, len(df) - 1):
            candle1 = df.iloc[i - 1]
            candle2 = df.iloc[i]
            candle3 = df.iloc[i + 1]

            # Bullish FVG: Gap between candle1 high and candle3 low
            if candle3['Low'] > candle1['High']:
                gap_size = candle3['Low'] - candle1['High']
                bar_range = candle2['High'] - candle2['Low']

                if bar_range > 0:
                    gap_pct = (gap_size / bar_range) * 100

                    # Auto-threshold: gap must be significant relative to middle bar
                    if gap_pct >= self.fvg_threshold_pct * 100:
                        fvg = SmartMoneyFVG(
                            timestamp=df.index[i],
                            high=candle3['Low'],
                            low=candle1['High'],
                            bias=Bias.BULLISH,
                            timeframe=timeframe,
                            gap_size=gap_size,
                            gap_percentage=gap_pct,
                            mitigated=False,
                            mitigation_percentage=0.0
                        )
                        fvgs.append(fvg)

            # Bearish FVG: Gap between candle1 low and candle3 high
            elif candle3['High'] < candle1['Low']:
                gap_size = candle1['Low'] - candle3['High']
                bar_range = candle2['High'] - candle2['Low']

                if bar_range > 0:
                    gap_pct = (gap_size / bar_range) * 100

                    if gap_pct >= self.fvg_threshold_pct * 100:
                        fvg = SmartMoneyFVG(
                            timestamp=df.index[i],
                            high=candle1['Low'],
                            low=candle3['High'],
                            bias=Bias.BEARISH,
                            timeframe=timeframe,
                            gap_size=gap_size,
                            gap_percentage=gap_pct,
                            mitigated=False,
                            mitigation_percentage=0.0
                        )
                        fvgs.append(fvg)

        # Check mitigation
        for fvg in fvgs:
            future_data = df[df.index > fvg.timestamp]
            if len(future_data) > 0:
                if fvg.bias == Bias.BULLISH:
                    # Check if price came back to fill gap
                    lowest_after = future_data['Low'].min()
                    if lowest_after <= fvg.high:
                        penetration = fvg.high - lowest_after
                        fvg.mitigation_percentage = (penetration / fvg.gap_size) * 100
                        fvg.mitigated = fvg.mitigation_percentage >= 50
                else:
                    # Bearish FVG
                    highest_after = future_data['High'].max()
                    if highest_after >= fvg.low:
                        penetration = highest_after - fvg.low
                        fvg.mitigation_percentage = (penetration / fvg.gap_size) * 100
                        fvg.mitigated = fvg.mitigation_percentage >= 50

        return fvgs

    def _calculate_premium_discount_zones(
        self,
        current_price: float,
        range_high: float,
        range_low: float
    ) -> Dict[str, PremiumDiscountZone]:
        """
        Calculate Premium/Discount zones
        Premium: 95-100%, Equilibrium: 47.5-52.5%, Discount: 0-5%

        Args:
            current_price: Current market price
            range_high: Range high (e.g., swing high)
            range_low: Range low (e.g., swing low)

        Returns:
            Dictionary of zones by type
        """
        total_range = range_high - range_low

        if total_range == 0:
            # No range, return neutral
            return {
                'current': PremiumDiscountZone(
                    zone_type=ZoneType.NEUTRAL,
                    high=range_high,
                    low=range_low,
                    range_high=range_high,
                    range_low=range_low,
                    percentage=50.0
                )
            }

        # Calculate percentage in range
        current_pct = ((current_price - range_low) / total_range) * 100

        # Define zones
        zones = {
            'premium': PremiumDiscountZone(
                zone_type=ZoneType.PREMIUM,
                high=range_high,
                low=range_low + (total_range * 0.95),
                range_high=range_high,
                range_low=range_low,
                percentage=97.5  # Mid-point
            ),
            'equilibrium': PremiumDiscountZone(
                zone_type=ZoneType.EQUILIBRIUM,
                high=range_low + (total_range * 0.525),
                low=range_low + (total_range * 0.475),
                range_high=range_high,
                range_low=range_low,
                percentage=50.0
            ),
            'discount': PremiumDiscountZone(
                zone_type=ZoneType.DISCOUNT,
                high=range_low + (total_range * 0.05),
                low=range_low,
                range_high=range_high,
                range_low=range_low,
                percentage=2.5  # Mid-point
            )
        }

        # Determine current zone
        if current_pct >= 95:
            current_zone_type = ZoneType.PREMIUM
        elif 47.5 <= current_pct <= 52.5:
            current_zone_type = ZoneType.EQUILIBRIUM
        elif current_pct <= 5:
            current_zone_type = ZoneType.DISCOUNT
        else:
            current_zone_type = ZoneType.NEUTRAL

        zones['current'] = PremiumDiscountZone(
            zone_type=current_zone_type,
            high=current_price,
            low=current_price,
            range_high=range_high,
            range_low=range_low,
            percentage=current_pct
        )

        return zones

    def _detect_structure_with_mode(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> List:
        """
        Detect structure with consideration for historical vs present mode
        Historical mode: more sensitive, catches more structure
        Present mode: more conservative, only clear breaks

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of structure events
        """
        if self.mode == 'historical':
            # More sensitive - use internal structure
            self.structure_detector.internal_lookback = max(3, self.swing_lookback - 2)
        else:
            # Present mode - use swing structure only
            self.structure_detector.internal_lookback = self.swing_lookback

        return self.structure_detector.detect_structure(df, timeframe)

    def _label_swing_strength(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> List[SwingLabel]:
        """
        Label swing highs and lows as Strong or Weak
        Strong: Clear rejection with volume, multiple confirmations
        Weak: Marginal swing, low volume, few confirmations

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of swing labels with strength classification
        """
        labels = []

        for i in range(self.swing_lookback, len(df) - self.swing_lookback):
            # Check for swing high
            if df['High'].iloc[i] == df['High'].iloc[i-self.swing_lookback:i+self.swing_lookback+1].max():
                # Classify strength
                candle = df.iloc[i]
                upper_wick = candle['High'] - max(candle['Open'], candle['Close'])
                body = abs(candle['Close'] - candle['Open'])
                total_range = candle['High'] - candle['Low']

                # Strong high: large upper wick, high volume, clear rejection
                has_strong_rejection = upper_wick > body and upper_wick > 0.4 * total_range
                has_high_volume = candle['Volume'] > df['Volume'].iloc[max(0, i-20):i].mean() * 1.5
                confirmation_bars = self.swing_lookback * 2

                is_strong = has_strong_rejection and has_high_volume

                label = SwingLabel(
                    timestamp=df.index[i],
                    price=candle['High'],
                    strength=SwingStrength.STRONG_HIGH if is_strong else SwingStrength.WEAK_HIGH,
                    is_high=True,
                    confirmation_bars=confirmation_bars
                )
                labels.append(label)

            # Check for swing low
            if df['Low'].iloc[i] == df['Low'].iloc[i-self.swing_lookback:i+self.swing_lookback+1].min():
                candle = df.iloc[i]
                lower_wick = min(candle['Open'], candle['Close']) - candle['Low']
                body = abs(candle['Close'] - candle['Open'])
                total_range = candle['High'] - candle['Low']

                # Strong low: large lower wick, high volume, clear rejection
                has_strong_rejection = lower_wick > body and lower_wick > 0.4 * total_range
                has_high_volume = candle['Volume'] > df['Volume'].iloc[max(0, i-20):i].mean() * 1.5

                is_strong = has_strong_rejection and has_high_volume

                label = SwingLabel(
                    timestamp=df.index[i],
                    price=candle['Low'],
                    strength=SwingStrength.STRONG_LOW if is_strong else SwingStrength.WEAK_LOW,
                    is_high=False,
                    confirmation_bars=self.swing_lookback * 2
                )
                labels.append(label)

        return labels

    def _determine_current_bias(
        self,
        df: pd.DataFrame,
        structure_events: List
    ) -> Bias:
        """
        Determine current market bias based on recent structure

        Args:
            df: OHLCV DataFrame
            structure_events: List of structure events

        Returns:
            Current market bias
        """
        if not structure_events:
            return Bias.NEUTRAL

        # Look at most recent structure event
        recent_event = structure_events[-1]

        # MSS or BOS determines bias
        if recent_event.type in [StructureType.MSS, StructureType.BOS]:
            return recent_event.bias

        # CHoCH suggests potential reversal - check price action
        if recent_event.type == StructureType.CHOCH:
            # Check if price is making higher highs or lower lows
            recent_highs = df['High'].iloc[-10:]
            recent_lows = df['Low'].iloc[-10:]

            if recent_highs.iloc[-1] > recent_highs.iloc[0]:
                return Bias.BULLISH
            elif recent_lows.iloc[-1] < recent_lows.iloc[0]:
                return Bias.BEARISH

        return Bias.NEUTRAL


def get_smc_summary(analysis: Dict) -> str:
    """
    Generate human-readable summary of Smart Money Concepts analysis

    Args:
        analysis: Results from SmartMoneyConcepts.analyze()

    Returns:
        Formatted summary string
    """
    summary = f"=== Smart Money Concepts ({analysis['timeframe']}) ===\n\n"

    # Current status
    current_zone = analysis['premium_discount_zones']['current']
    summary += f"Current Price: {analysis['current_price']:.2f}\n"
    summary += f"Zone: {current_zone.zone_type.value} ({current_zone.percentage:.1f}%)\n"
    summary += f"Bias: {analysis['current_bias'].value}\n"
    summary += f"Mode: {analysis['mode'].title()}\n\n"

    # Order Blocks
    obs = analysis['order_blocks']
    fresh_obs = [ob for ob in obs if not ob.tested]
    summary += f"Order Blocks: {len(obs)} ({len(fresh_obs)} fresh)\n"
    for ob in fresh_obs[-3:]:
        summary += f"  - {ob.bias.value} OB @ {ob.low:.2f}-{ob.high:.2f} " \
                  f"(Strength: {ob.strength_score:.0f})\n"

    # FVGs
    fvgs = analysis['fvgs']
    unmitigated_fvgs = [fvg for fvg in fvgs if not fvg.mitigated]
    summary += f"\nFair Value Gaps: {len(fvgs)} ({len(unmitigated_fvgs)} unmitigated)\n"
    for fvg in unmitigated_fvgs[-3:]:
        summary += f"  - {fvg.bias.value} FVG @ {fvg.low:.2f}-{fvg.high:.2f} " \
                  f"(Gap: {fvg.gap_percentage:.1f}%)\n"

    # Swing labels
    swings = analysis['swing_labels']
    strong_swings = [s for s in swings if 'Strong' in s.strength.value]
    summary += f"\nSwing Labels: {len(swings)} ({len(strong_swings)} strong)\n"

    # Structure
    structures = analysis['structure_events']
    summary += f"Structure Events: {len(structures)}\n"

    # Premium/Discount zones
    pd_zones = analysis['premium_discount_zones']
    summary += f"\nRange: {analysis['range_low']:.2f} - {analysis['range_high']:.2f}\n"
    summary += f"Premium Zone: {pd_zones['premium'].low:.2f}+\n"
    summary += f"Equilibrium: {pd_zones['equilibrium'].low:.2f}-{pd_zones['equilibrium'].high:.2f}\n"
    summary += f"Discount Zone: {pd_zones['discount'].high:.2f}-\n"

    return summary
