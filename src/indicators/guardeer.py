"""
Guardeer Indicator Module
Implements advanced volumetric analysis and market structure detection
Features: Volumetric OBs, MSS/CHoCH/CHoCH+, EQH/EQL, FVG/VI/OG, Impulse, Accumulation/Distribution
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import setup_logger
from src.core.structure_detector import StructureDetector, StructureType, Bias
from src.core.order_block_detector import OrderBlockDetector, OrderBlock
from src.core.fvg_detector import FVGDetector
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


class ImpulseType(Enum):
    """Impulse move classification"""
    STRONG_BULLISH = "Strong Bullish"
    BULLISH = "Bullish"
    WEAK_BULLISH = "Weak Bullish"
    STRONG_BEARISH = "Strong Bearish"
    BEARISH = "Bearish"
    WEAK_BEARISH = "Weak Bearish"
    CONSOLIDATION = "Consolidation"


@dataclass
class VolumetricOrderBlock:
    """Enhanced Order Block with volumetric analysis"""
    timestamp: pd.Timestamp
    high: float
    low: float
    bias: Bias
    timeframe: str

    # Volumetric metrics
    total_volume: float
    buy_volume: float
    sell_volume: float
    buy_sell_ratio: float
    volume_imbalance: float  # % difference between buy and sell

    # Relevance
    relevance_pct: float  # Based on recent volume average

    # Classification
    strength: str  # "Strong", "Medium", "Weak"
    fresh: bool = True


@dataclass
class EqualLevelZone:
    """Equal High/Low zone with ATR tolerance"""
    price: float
    tolerance: float  # ATR-based tolerance
    timestamps: List[pd.Timestamp]
    count: int  # Number of times tested
    is_high: bool  # True for EQH, False for EQL
    timeframe: str


@dataclass
class AccumulationZone:
    """Accumulation/Distribution zone detection"""
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    high: float
    low: float
    zone_type: str  # "Accumulation", "Distribution"
    volume_profile: Dict[float, float]  # Price level -> Volume
    breakout_direction: Optional[str] = None  # "Up", "Down", None


class GuardeerIndicator:
    """
    Guardeer Indicator - Advanced Market Analysis

    Combines multiple detection systems:
    - Volumetric Order Blocks with buy/sell metrics
    - MSS/CHoCH/CHoCH+ structure detection
    - EQH/EQL with ATR tolerance
    - FVG/VI/OG gap detection
    - Impulse indicator
    - Accumulation/Distribution zones
    """

    def __init__(self, atr_period: int = 200, atr_multiplier: float = 0.1):
        """
        Initialize Guardeer Indicator

        Args:
            atr_period: Period for ATR calculation (default 200)
            atr_multiplier: Multiplier for EQH/EQL tolerance (default 0.1)
        """
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier

        # Initialize sub-detectors
        self.structure_detector = StructureDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg_detector = FVGDetector()

        logger.info(f"Guardeer Indicator initialized (ATR: {atr_period}, Multiplier: {atr_multiplier})")

    def analyze(
        self,
        df: pd.DataFrame,
        timeframe: str = 'M15'
    ) -> Dict[str, any]:
        """
        Perform complete Guardeer analysis on price data

        Args:
            df: OHLCV DataFrame with columns: Open, High, Low, Close, Volume
            timeframe: Timeframe string (e.g., 'M15', 'H1', 'D1')

        Returns:
            Dictionary containing all analysis results
        """
        logger.info(f"Running Guardeer analysis on {timeframe} ({len(df)} bars)")

        # Calculate ATR for EQH/EQL tolerance
        atr = self._calculate_atr(df)
        tolerance = atr * self.atr_multiplier

        # 1. Detect volumetric order blocks
        vol_obs = self._detect_volumetric_obs(df, timeframe)

        # 2. Detect structure (MSS, CHoCH, CHoCH+)
        structure_events = self.structure_detector.detect_structure(df, timeframe)

        # 3. Detect Equal Highs/Lows
        eqh_zones = self._detect_equal_levels(df, tolerance, is_high=True, timeframe=timeframe)
        eql_zones = self._detect_equal_levels(df, tolerance, is_high=False, timeframe=timeframe)

        # 4. Detect FVGs, VIs, OGs
        fvgs = self.fvg_detector.detect_fvg(df, timeframe)
        vis = self._detect_volume_imbalance(df, timeframe)
        ogs = self._detect_opening_gaps(df, timeframe)

        # 5. Classify impulses
        impulses = self._classify_impulses(df)

        # 6. Detect Accumulation/Distribution zones
        acc_dist_zones = self._detect_accumulation_distribution(df, timeframe)

        results = {
            'volumetric_obs': vol_obs,
            'structure_events': structure_events,
            'eqh_zones': eqh_zones,
            'eql_zones': eql_zones,
            'fvgs': fvgs,
            'volume_imbalances': vis,
            'opening_gaps': ogs,
            'impulses': impulses,
            'accumulation_distribution': acc_dist_zones,
            'current_atr': atr,
            'eq_tolerance': tolerance,
            'timeframe': timeframe,
            'analyzed_bars': len(df)
        }

        logger.info(f"Analysis complete: {len(vol_obs)} Vol OBs, {len(structure_events)} structures, "
                   f"{len(eqh_zones)} EQH, {len(eql_zones)} EQL, {len(fvgs)} FVGs")

        return results

    def _calculate_atr(self, df: pd.DataFrame) -> float:
        """Calculate Average True Range"""
        high = df['High']
        low = df['Low']
        close = df['Close'].shift(1)

        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=self.atr_period).mean().iloc[-1]

        return atr if not np.isnan(atr) else (df['High'].iloc[-1] - df['Low'].iloc[-1])

    def _detect_volumetric_obs(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> List[VolumetricOrderBlock]:
        """
        Detect volumetric order blocks with buy/sell volume analysis

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of volumetric order blocks
        """
        vol_obs = []

        # Calculate average volume for relevance
        avg_volume = df['Volume'].rolling(window=20).mean()

        # Look for displacement candles (strong directional moves)
        for i in range(1, len(df) - 1):
            candle = df.iloc[i]
            prev_candle = df.iloc[i - 1]
            next_candle = df.iloc[i + 1]

            # Calculate body and wick sizes
            body_size = abs(candle['Close'] - candle['Open'])
            total_range = candle['High'] - candle['Low']

            # Skip doji candles
            if total_range == 0 or body_size / total_range < 0.5:
                continue

            # Check for displacement (strong move followed by continuation)
            is_bullish_displacement = (
                candle['Close'] > candle['Open'] and
                body_size > 2 * df['Close'].iloc[max(0, i-10):i].std() and
                next_candle['Close'] > candle['High']
            )

            is_bearish_displacement = (
                candle['Close'] < candle['Open'] and
                body_size > 2 * df['Close'].iloc[max(0, i-10):i].std() and
                next_candle['Close'] < candle['Low']
            )

            if is_bullish_displacement or is_bearish_displacement:
                # Estimate buy/sell volume from candle characteristics
                total_vol = candle['Volume']

                if is_bullish_displacement:
                    # More buying pressure
                    buy_pct = 0.6 + (body_size / total_range) * 0.3  # 60-90% buy
                    buy_vol = total_vol * buy_pct
                    sell_vol = total_vol * (1 - buy_pct)
                    bias = Bias.BULLISH
                else:
                    # More selling pressure
                    sell_pct = 0.6 + (body_size / total_range) * 0.3  # 60-90% sell
                    sell_vol = total_vol * sell_pct
                    buy_vol = total_vol * (1 - sell_pct)
                    bias = Bias.BEARISH

                # Calculate metrics
                buy_sell_ratio = buy_vol / sell_vol if sell_vol > 0 else 10.0
                volume_imbalance = ((buy_vol - sell_vol) / total_vol) * 100
                relevance_pct = (total_vol / avg_volume.iloc[i]) * 100 if not np.isnan(avg_volume.iloc[i]) else 100

                # Classify strength
                if relevance_pct > 200:
                    strength = "Strong"
                elif relevance_pct > 150:
                    strength = "Medium"
                else:
                    strength = "Weak"

                # Previous candle becomes the order block
                vol_ob = VolumetricOrderBlock(
                    timestamp=df.index[i - 1],
                    high=prev_candle['High'],
                    low=prev_candle['Low'],
                    bias=bias,
                    timeframe=timeframe,
                    total_volume=total_vol,
                    buy_volume=buy_vol,
                    sell_volume=sell_vol,
                    buy_sell_ratio=buy_sell_ratio,
                    volume_imbalance=volume_imbalance,
                    relevance_pct=relevance_pct,
                    strength=strength,
                    fresh=True
                )

                vol_obs.append(vol_ob)

        return vol_obs

    def _detect_equal_levels(
        self,
        df: pd.DataFrame,
        tolerance: float,
        is_high: bool,
        timeframe: str
    ) -> List[EqualLevelZone]:
        """
        Detect Equal Highs or Equal Lows using ATR-based tolerance

        Args:
            df: OHLCV DataFrame
            tolerance: ATR * multiplier tolerance
            is_high: True for EQH, False for EQL
            timeframe: Current timeframe

        Returns:
            List of equal level zones
        """
        eq_zones = []
        price_key = 'High' if is_high else 'Low'

        # Find swing points
        swing_window = 5
        swings = []

        for i in range(swing_window, len(df) - swing_window):
            if is_high:
                # Swing high
                if df[price_key].iloc[i] == df[price_key].iloc[i-swing_window:i+swing_window+1].max():
                    swings.append((i, df[price_key].iloc[i]))
            else:
                # Swing low
                if df[price_key].iloc[i] == df[price_key].iloc[i-swing_window:i+swing_window+1].min():
                    swings.append((i, df[price_key].iloc[i]))

        # Group nearby swings
        used = set()
        for i, (idx1, price1) in enumerate(swings):
            if i in used:
                continue

            group = [(idx1, price1)]
            timestamps = [df.index[idx1]]

            for j, (idx2, price2) in enumerate(swings[i+1:], start=i+1):
                if j in used:
                    continue

                # Check if within tolerance
                if abs(price2 - price1) <= tolerance:
                    group.append((idx2, price2))
                    timestamps.append(df.index[idx2])
                    used.add(j)

            # Need at least 2 touches for EQH/EQL
            if len(group) >= 2:
                avg_price = np.mean([p for _, p in group])
                eq_zone = EqualLevelZone(
                    price=avg_price,
                    tolerance=tolerance,
                    timestamps=timestamps,
                    count=len(group),
                    is_high=is_high,
                    timeframe=timeframe
                )
                eq_zones.append(eq_zone)

        return eq_zones

    def _detect_volume_imbalance(self, df: pd.DataFrame, timeframe: str) -> List[Dict]:
        """
        Detect Volume Imbalances (VI) - similar to FVG but volume-focused

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of volume imbalance zones
        """
        vis = []

        for i in range(1, len(df) - 1):
            prev_candle = df.iloc[i - 1]
            curr_candle = df.iloc[i]
            next_candle = df.iloc[i + 1]

            # Bullish VI: gap up with low volume in middle
            bullish_vi = (
                next_candle['Low'] > prev_candle['High'] and
                curr_candle['Volume'] < 0.5 * df['Volume'].iloc[max(0, i-10):i].mean()
            )

            # Bearish VI: gap down with low volume in middle
            bearish_vi = (
                next_candle['High'] < prev_candle['Low'] and
                curr_candle['Volume'] < 0.5 * df['Volume'].iloc[max(0, i-10):i].mean()
            )

            if bullish_vi or bearish_vi:
                vi = {
                    'timestamp': df.index[i],
                    'high': max(prev_candle['High'], next_candle['Low']) if bullish_vi else prev_candle['Low'],
                    'low': min(next_candle['Low'], prev_candle['High']) if bullish_vi else next_candle['High'],
                    'bias': 'Bullish' if bullish_vi else 'Bearish',
                    'volume': curr_candle['Volume'],
                    'timeframe': timeframe
                }
                vis.append(vi)

        return vis

    def _detect_opening_gaps(self, df: pd.DataFrame, timeframe: str) -> List[Dict]:
        """
        Detect Opening Gaps (OG) - gaps between close and next open

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of opening gaps
        """
        ogs = []

        for i in range(1, len(df)):
            prev_close = df['Close'].iloc[i - 1]
            curr_open = df['Open'].iloc[i]

            gap_size = abs(curr_open - prev_close)
            gap_pct = (gap_size / prev_close) * 100

            # Significant gap (>0.1%)
            if gap_pct > 0.1:
                og = {
                    'timestamp': df.index[i],
                    'gap_high': max(prev_close, curr_open),
                    'gap_low': min(prev_close, curr_open),
                    'gap_size': gap_size,
                    'gap_pct': gap_pct,
                    'direction': 'Up' if curr_open > prev_close else 'Down',
                    'timeframe': timeframe
                }
                ogs.append(og)

        return ogs

    def _classify_impulses(self, df: pd.DataFrame) -> List[Dict]:
        """
        Classify impulse moves based on momentum and volume

        Args:
            df: OHLCV DataFrame

        Returns:
            List of impulse classifications
        """
        impulses = []

        # Calculate momentum
        df['momentum'] = df['Close'].diff(5)
        df['vol_sma'] = df['Volume'].rolling(window=20).mean()

        for i in range(5, len(df)):
            momentum = df['momentum'].iloc[i]
            volume_ratio = df['Volume'].iloc[i] / df['vol_sma'].iloc[i] if df['vol_sma'].iloc[i] > 0 else 1

            # Classify based on momentum and volume
            if momentum > 0:
                if volume_ratio > 2 and momentum > df['Close'].iloc[i] * 0.01:
                    impulse_type = ImpulseType.STRONG_BULLISH
                elif volume_ratio > 1.5:
                    impulse_type = ImpulseType.BULLISH
                else:
                    impulse_type = ImpulseType.WEAK_BULLISH
            elif momentum < 0:
                if volume_ratio > 2 and abs(momentum) > df['Close'].iloc[i] * 0.01:
                    impulse_type = ImpulseType.STRONG_BEARISH
                elif volume_ratio > 1.5:
                    impulse_type = ImpulseType.BEARISH
                else:
                    impulse_type = ImpulseType.WEAK_BEARISH
            else:
                impulse_type = ImpulseType.CONSOLIDATION

            impulses.append({
                'timestamp': df.index[i],
                'type': impulse_type,
                'momentum': momentum,
                'volume_ratio': volume_ratio
            })

        return impulses

    def _detect_accumulation_distribution(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> List[AccumulationZone]:
        """
        Detect Accumulation and Distribution zones

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of accumulation/distribution zones
        """
        zones = []

        # Look for consolidation periods with increasing volume
        window = 20

        for i in range(window, len(df) - 5):
            segment = df.iloc[i-window:i]

            # Check for tight range (consolidation)
            price_range = segment['High'].max() - segment['Low'].min()
            avg_range = (segment['High'] - segment['Low']).mean()

            is_consolidation = price_range < avg_range * 3

            if not is_consolidation:
                continue

            # Check volume trend
            first_half_vol = segment['Volume'].iloc[:window//2].mean()
            second_half_vol = segment['Volume'].iloc[window//2:].mean()

            volume_increasing = second_half_vol > first_half_vol * 1.2

            if volume_increasing:
                # Check for breakout
                next_5 = df.iloc[i:i+5]
                broke_high = next_5['Close'].max() > segment['High'].max()
                broke_low = next_5['Close'].min() < segment['Low'].min()

                if broke_high or broke_low:
                    zone = AccumulationZone(
                        start_time=segment.index[0],
                        end_time=segment.index[-1],
                        high=segment['High'].max(),
                        low=segment['Low'].min(),
                        zone_type="Accumulation" if broke_high else "Distribution",
                        volume_profile={},  # Simplified for now
                        breakout_direction="Up" if broke_high else "Down"
                    )
                    zones.append(zone)

        return zones


def get_guardeer_summary(analysis: Dict) -> str:
    """
    Generate human-readable summary of Guardeer analysis

    Args:
        analysis: Results from GuardeerIndicator.analyze()

    Returns:
        Formatted summary string
    """
    summary = f"=== Guardeer Analysis ({analysis['timeframe']}) ===\n\n"

    # Volumetric OBs
    vol_obs = analysis['volumetric_obs']
    summary += f"Volumetric Order Blocks: {len(vol_obs)}\n"
    for ob in vol_obs[-3:]:  # Last 3
        summary += f"  - {ob.bias.value} OB @ {ob.low:.2f}-{ob.high:.2f} " \
                  f"(Vol Imb: {ob.volume_imbalance:+.1f}%, {ob.strength})\n"

    # Structure
    structures = analysis['structure_events']
    summary += f"\nStructure Events: {len(structures)}\n"
    for struct in structures[-3:]:
        summary += f"  - {struct.type.value} ({struct.bias.value}) @ {struct.price:.2f}\n"

    # Equal levels
    eqh = analysis['eqh_zones']
    eql = analysis['eql_zones']
    summary += f"\nEqual Levels: {len(eqh)} EQH, {len(eql)} EQL\n"

    # FVGs
    fvgs = analysis['fvgs']
    summary += f"Fair Value Gaps: {len(fvgs)}\n"

    # Acc/Dist
    acc_dist = analysis['accumulation_distribution']
    summary += f"Accumulation/Distribution Zones: {len(acc_dist)}\n"

    summary += f"\nATR: {analysis['current_atr']:.2f} | EQ Tolerance: {analysis['eq_tolerance']:.2f}\n"

    return summary
