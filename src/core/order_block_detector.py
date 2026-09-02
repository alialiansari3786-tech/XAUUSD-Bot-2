"""
Order Block Detector Module
Detects volumetric and standard order blocks with fresh/unfresh tracking
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from src.utils.logger import setup_logger
from src.core.structure_detector import Bias, SwingPoint
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


@dataclass
class OrderBlock:
    """Order Block representation"""
    timestamp: pd.Timestamp
    high: float
    low: float
    bias: Bias
    timeframe: str
    fresh: bool = True
    volumetric: bool = False

    # Volumetric data (if available)
    total_volume: Optional[float] = None
    buy_volume: Optional[float] = None
    sell_volume: Optional[float] = None
    relevance_pct: Optional[float] = None

    # Tracking
    tested_count: int = 0
    last_test_time: Optional[pd.Timestamp] = None

    # Location relative to trading range
    in_trading_range: bool = False
    trading_range_low: Optional[float] = None
    trading_range_high: Optional[float] = None


class OrderBlockDetector:
    """Detects order blocks with volumetric analysis"""

    def __init__(self):
        """Initialize OrderBlockDetector"""
        self.tracked_obs: Dict[str, List[OrderBlock]] = {}

    def detect_order_blocks(
        self,
        df: pd.DataFrame,
        timeframe: str,
        structure_events: List = None,
        trading_range: Tuple[float, float] = None
    ) -> List[OrderBlock]:
        """
        Detect order blocks in dataframe

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            structure_events: List of structure events for context
            trading_range: Optional (low, high) tuple defining valid range

        Returns:
            List of detected order blocks
        """

        order_blocks = []

        # Get recent structure to determine bias
        current_bias = self._determine_bias(df)

        # Look for displacement moves (strong directional candles)
        displacement_indices = self._find_displacement_candles(df)

        for disp_idx in displacement_indices:
            if disp_idx == 0:
                continue

            disp_candle = df.iloc[disp_idx]
            prev_candle = df.iloc[disp_idx - 1]

            # Bullish displacement: OB is the candle before strong up move
            if disp_candle['Close'] > disp_candle['Open']:
                # Previous candle becomes demand OB
                ob = OrderBlock(
                    timestamp=df.index[disp_idx - 1],
                    high=prev_candle['High'],
                    low=prev_candle['Low'],
                    bias=Bias.BULLISH,
                    timeframe=timeframe,
                    fresh=True,
                    total_volume=prev_candle.get('Volume', 0)
                )

                # Check if in trading range
                if trading_range:
                    ob.in_trading_range = trading_range[0] <= ob.low <= trading_range[1]
                    ob.trading_range_low = trading_range[0]
                    ob.trading_range_high = trading_range[1]

                order_blocks.append(ob)

            # Bearish displacement: OB is the candle before strong down move
            elif disp_candle['Close'] < disp_candle['Open']:
                # Previous candle becomes supply OB
                ob = OrderBlock(
                    timestamp=df.index[disp_idx - 1],
                    high=prev_candle['High'],
                    low=prev_candle['Low'],
                    bias=Bias.BEARISH,
                    timeframe=timeframe,
                    fresh=True,
                    total_volume=prev_candle.get('Volume', 0)
                )

                if trading_range:
                    ob.in_trading_range = trading_range[0] <= ob.high <= trading_range[1]
                    ob.trading_range_low = trading_range[0]
                    ob.trading_range_high = trading_range[1]

                order_blocks.append(ob)

        # Update freshness for all OBs
        order_blocks = self._update_freshness(order_blocks, df)

        # Store tracked OBs
        self.tracked_obs[timeframe] = order_blocks

        logger.debug(f"Detected {len(order_blocks)} order blocks on {timeframe}")
        return order_blocks

    def detect_volumetric_order_blocks(
        self,
        df: pd.DataFrame,
        timeframe: str,
        structure_events: List = None,
        trading_range: Tuple[float, float] = None
    ) -> List[OrderBlock]:
        """
        Detect volumetric order blocks with internal buy/sell metrics
        Based on Guardeer indicator logic

        Args:
            df: OHLCV DataFrame with Volume
            timeframe: Current timeframe
            structure_events: Structure events for context
            trading_range: Valid trading range

        Returns:
            List of volumetric order blocks
        """

        order_blocks = []

        # Calculate volume metrics
        df = df.copy()
        df['body'] = abs(df['Close'] - df['Open'])
        df['range'] = df['High'] - df['Low']
        df['body_pct'] = df['body'] / df['range'].replace(0, np.nan)

        # Estimate buy/sell volume based on close position
        df['buy_volume'] = df['Volume'] * ((df['Close'] - df['Low']) / df['range'].replace(0, np.nan))
        df['sell_volume'] = df['Volume'] * ((df['High'] - df['Close']) / df['range'].replace(0, np.nan))

        # Find strong displacement candles
        avg_range = df['range'].rolling(20).mean()
        displacement_threshold = avg_range * 1.5

        for i in range(1, len(df)):
            candle = df.iloc[i]

            # Strong bullish displacement
            if candle['range'] > displacement_threshold.iloc[i] and candle['Close'] > candle['Open']:
                prev_candle = df.iloc[i - 1]

                ob = OrderBlock(
                    timestamp=df.index[i - 1],
                    high=prev_candle['High'],
                    low=prev_candle['Low'],
                    bias=Bias.BULLISH,
                    timeframe=timeframe,
                    fresh=True,
                    volumetric=True,
                    total_volume=prev_candle['Volume'],
                    buy_volume=prev_candle['buy_volume'],
                    sell_volume=prev_candle['sell_volume'],
                    relevance_pct=prev_candle['body_pct'] * 100 if not pd.isna(prev_candle['body_pct']) else 0
                )

                if trading_range:
                    ob.in_trading_range = trading_range[0] <= ob.low <= trading_range[1]
                    ob.trading_range_low = trading_range[0]
                    ob.trading_range_high = trading_range[1]

                order_blocks.append(ob)

            # Strong bearish displacement
            elif candle['range'] > displacement_threshold.iloc[i] and candle['Close'] < candle['Open']:
                prev_candle = df.iloc[i - 1]

                ob = OrderBlock(
                    timestamp=df.index[i - 1],
                    high=prev_candle['High'],
                    low=prev_candle['Low'],
                    bias=Bias.BEARISH,
                    timeframe=timeframe,
                    fresh=True,
                    volumetric=True,
                    total_volume=prev_candle['Volume'],
                    buy_volume=prev_candle['buy_volume'],
                    sell_volume=prev_candle['sell_volume'],
                    relevance_pct=prev_candle['body_pct'] * 100 if not pd.isna(prev_candle['body_pct']) else 0
                )

                if trading_range:
                    ob.in_trading_range = trading_range[0] <= ob.high <= trading_range[1]
                    ob.trading_range_low = trading_range[0]
                    ob.trading_range_high = trading_range[1]

                order_blocks.append(ob)

        # Update freshness
        order_blocks = self._update_freshness(order_blocks, df)

        self.tracked_obs[f"{timeframe}_volumetric"] = order_blocks

        logger.debug(f"Detected {len(order_blocks)} volumetric OBs on {timeframe}")
        return order_blocks

    def _find_displacement_candles(self, df: pd.DataFrame) -> List[int]:
        """
        Find candles with strong displacement

        Args:
            df: OHLCV DataFrame

        Returns:
            List of indices with displacement
        """

        displacement_indices = []

        # Calculate average true range
        df = df.copy()
        df['range'] = df['High'] - df['Low']
        avg_range = df['range'].rolling(window=14).mean()

        # Calculate candle body size
        df['body'] = abs(df['Close'] - df['Open'])

        for i in range(14, len(df)):
            candle_range = df['range'].iloc[i]
            candle_body = df['body'].iloc[i]
            avg = avg_range.iloc[i]

            # Strong displacement: range > 1.5x average AND body > 70% of range
            if candle_range > avg * 1.5 and candle_body > candle_range * 0.7:
                displacement_indices.append(i)

        return displacement_indices

    def _update_freshness(
        self,
        order_blocks: List[OrderBlock],
        df: pd.DataFrame
    ) -> List[OrderBlock]:
        """
        Update freshness status of order blocks

        An OB becomes unfresh when:
        - Price closes through it (not just wick)
        - Price taps it and fails to react

        Args:
            order_blocks: List of order blocks
            df: Price dataframe

        Returns:
            Updated order blocks
        """

        for ob in order_blocks:
            if not ob.fresh:
                continue

            # Get price action after OB formation
            future_data = df[df.index > ob.timestamp]

            if future_data.empty:
                continue

            for idx, row in future_data.iterrows():
                # Bullish OB: Check if price closed below OB low
                if ob.bias == Bias.BULLISH:
                    # Wick touch counts as test
                    if row['Low'] <= ob.high:
                        ob.tested_count += 1
                        ob.last_test_time = idx

                    # Close through makes it unfresh
                    if row['Close'] < ob.low:
                        ob.fresh = False
                        break

                # Bearish OB: Check if price closed above OB high
                elif ob.bias == Bias.BEARISH:
                    if row['High'] >= ob.low:
                        ob.tested_count += 1
                        ob.last_test_time = idx

                    if row['Close'] > ob.high:
                        ob.fresh = False
                        break

        return order_blocks

    def _determine_bias(self, df: pd.DataFrame) -> Bias:
        """Determine current market bias from recent price action"""

        if len(df) < 20:
            return Bias.NEUTRAL

        recent = df.tail(20)

        # Simple trend determination
        if recent['Close'].iloc[-1] > recent['Close'].iloc[0]:
            return Bias.BULLISH
        elif recent['Close'].iloc[-1] < recent['Close'].iloc[0]:
            return Bias.BEARISH
        else:
            return Bias.NEUTRAL

    def get_fresh_obs(
        self,
        timeframe: str,
        bias: Optional[Bias] = None,
        in_trading_range_only: bool = False
    ) -> List[OrderBlock]:
        """
        Get fresh order blocks for timeframe

        Args:
            timeframe: Timeframe to query
            bias: Optional filter by bias
            in_trading_range_only: Only return OBs within trading range

        Returns:
            List of fresh order blocks
        """

        all_obs = []

        # Get both standard and volumetric OBs
        if timeframe in self.tracked_obs:
            all_obs.extend(self.tracked_obs[timeframe])

        if f"{timeframe}_volumetric" in self.tracked_obs:
            all_obs.extend(self.tracked_obs[f"{timeframe}_volumetric"])

        # Filter
        fresh_obs = [ob for ob in all_obs if ob.fresh]

        if bias:
            fresh_obs = [ob for ob in fresh_obs if ob.bias == bias]

        if in_trading_range_only:
            fresh_obs = [ob for ob in fresh_obs if ob.in_trading_range]

        return fresh_obs

    def check_ob_alignment(
        self,
        timeframes: List[str],
        price_tolerance: float = 0.001  # 0.1% tolerance
    ) -> List[Dict]:
        """
        Check for order block alignment across timeframes

        Args:
            timeframes: List of timeframes to check
            price_tolerance: Price tolerance as percentage

        Returns:
            List of aligned OB groups
        """

        aligned_groups = []

        # Get all fresh OBs from all timeframes
        all_obs = {}
        for tf in timeframes:
            all_obs[tf] = self.get_fresh_obs(tf)

        # Find overlapping OBs
        for tf1 in timeframes:
            for ob1 in all_obs.get(tf1, []):
                aligned_group = {
                    'timeframes': [tf1],
                    'obs': [ob1],
                    'bias': ob1.bias,
                    'avg_high': ob1.high,
                    'avg_low': ob1.low
                }

                # Check other timeframes
                for tf2 in timeframes:
                    if tf2 == tf1:
                        continue

                    for ob2 in all_obs.get(tf2, []):
                        # Check if OBs overlap and have same bias
                        if ob2.bias == ob1.bias:
                            # Calculate overlap
                            overlap_low = max(ob1.low, ob2.low)
                            overlap_high = min(ob1.high, ob2.high)

                            if overlap_high > overlap_low:
                                # OBs overlap
                                if tf2 not in aligned_group['timeframes']:
                                    aligned_group['timeframes'].append(tf2)
                                    aligned_group['obs'].append(ob2)

                # Only add if multiple timeframes aligned
                if len(aligned_group['timeframes']) >= 2:
                    # Calculate average zone
                    aligned_group['avg_high'] = np.mean([ob.high for ob in aligned_group['obs']])
                    aligned_group['avg_low'] = np.mean([ob.low for ob in aligned_group['obs']])
                    aligned_groups.append(aligned_group)

        # Remove duplicates
        unique_groups = []
        for group in aligned_groups:
            tfs_set = set(group['timeframes'])
            is_duplicate = False

            for existing in unique_groups:
                if set(existing['timeframes']) == tfs_set:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_groups.append(group)

        logger.debug(f"Found {len(unique_groups)} aligned OB groups")
        return unique_groups
