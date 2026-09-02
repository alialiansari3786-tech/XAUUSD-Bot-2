"""
Support and Resistance (SAR) Detector Module
Implements friend's SAR strategy with Fresh/Unfresh level tracking
"""

import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime

from src.utils.logger import setup_logger
from src.core.structure_detector import Bias
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


@dataclass
class SARLevel:
    """Support/Resistance level"""
    price: float
    timestamp: pd.Timestamp
    level_type: str  # 'support' or 'resistance'
    timeframe: str
    fresh: bool = True

    # Tracking
    touches: int = 0
    rejections: int = 0
    last_touch_time: Optional[pd.Timestamp] = None
    broken: bool = False
    broken_time: Optional[pd.Timestamp] = None

    # Re-freshing tracking
    can_refresh: bool = True
    refresh_count: int = 0


class SARDetector:
    """Detects Support and Resistance levels with Fresh/Unfresh tracking"""

    def __init__(self):
        """Initialize SARDetector"""
        self.tracked_levels: Dict[str, List[SARLevel]] = {}

    def detect_sar_levels(
        self,
        df: pd.DataFrame,
        timeframe: str,
        lookback: int = 20,
        tolerance_pct: float = 0.15
    ) -> List[SARLevel]:
        """
        Detect Support and Resistance levels

        Levels are identified from:
        - Recent swing highs/lows
        - Price rejection zones
        - Consolidation areas

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            lookback: Lookback period for level detection
            tolerance_pct: Price tolerance for clustering (as percentage)

        Returns:
            List of SAR levels
        """

        levels = []

        if len(df) < lookback:
            return levels

        recent_data = df.tail(lookback * 2)

        # Find local highs and lows
        highs = []
        lows = []

        for i in range(3, len(recent_data) - 3):
            # Local high
            if recent_data['High'].iloc[i] == recent_data['High'].iloc[i-3:i+4].max():
                highs.append({
                    'price': recent_data['High'].iloc[i],
                    'timestamp': recent_data.index[i]
                })

            # Local low
            if recent_data['Low'].iloc[i] == recent_data['Low'].iloc[i-3:i+4].min():
                lows.append({
                    'price': recent_data['Low'].iloc[i],
                    'timestamp': recent_data.index[i]
                })

        # Cluster similar levels (resistance)
        clustered_highs = self._cluster_levels(highs, tolerance_pct)
        for cluster in clustered_highs:
            levels.append(SARLevel(
                price=cluster['avg_price'],
                timestamp=cluster['latest_time'],
                level_type='resistance',
                timeframe=timeframe,
                fresh=True,
                touches=cluster['count']
            ))

        # Cluster similar levels (support)
        clustered_lows = self._cluster_levels(lows, tolerance_pct)
        for cluster in clustered_lows:
            levels.append(SARLevel(
                price=cluster['avg_price'],
                timestamp=cluster['latest_time'],
                level_type='support',
                timeframe=timeframe,
                fresh=True,
                touches=cluster['count']
            ))

        # Update with current price action
        levels = self._update_sar_status(levels, df)

        self.tracked_levels[timeframe] = levels

        logger.debug(f"Detected {len(levels)} SAR levels on {timeframe}")
        return levels

    def _cluster_levels(
        self,
        levels: List[Dict],
        tolerance_pct: float
    ) -> List[Dict]:
        """
        Cluster similar price levels together

        Args:
            levels: List of level dictionaries
            tolerance_pct: Clustering tolerance

        Returns:
            List of clustered levels
        """

        if not levels:
            return []

        clusters = []
        used = set()

        for i, level1 in enumerate(levels):
            if i in used:
                continue

            cluster = {
                'prices': [level1['price']],
                'times': [level1['timestamp']],
                'count': 1
            }

            for j, level2 in enumerate(levels[i+1:], start=i+1):
                if j in used:
                    continue

                # Check if within tolerance
                price_diff_pct = abs(level1['price'] - level2['price']) / level1['price'] * 100

                if price_diff_pct <= tolerance_pct:
                    cluster['prices'].append(level2['price'])
                    cluster['times'].append(level2['timestamp'])
                    cluster['count'] += 1
                    used.add(j)

            cluster['avg_price'] = np.mean(cluster['prices'])
            cluster['latest_time'] = max(cluster['times'])

            clusters.append(cluster)
            used.add(i)

        return clusters

    def _update_sar_status(
        self,
        levels: List[SARLevel],
        df: pd.DataFrame
    ) -> List[SARLevel]:
        """
        Update fresh/unfresh status of SAR levels

        Fresh Level Rules:
        - Untouched since formation = Fresh
        - Tapped (wick touch) = Still Fresh if not broken
        - Broken through (body close) = Unfresh
        - Re-freshing: If broken through completely and left behind, can become fresh again

        Args:
            levels: List of SAR levels
            df: Price dataframe

        Returns:
            Updated SAR levels
        """

        for level in levels:
            # Get price action after level formation
            future_data = df[df.index > level.timestamp]

            if future_data.empty:
                continue

            for idx, row in future_data.iterrows():
                if level.level_type == 'support':
                    # Check for touches (wick down to level)
                    if row['Low'] <= level.price <= row['High']:
                        level.touches += 1
                        level.last_touch_time = idx

                        # Check for rejection (close above level)
                        if row['Close'] > level.price:
                            level.rejections += 1

                    # Check for break (body close below)
                    if row['Close'] < level.price and not level.broken:
                        level.fresh = False
                        level.broken = True
                        level.broken_time = idx

                    # Re-freshing logic: If price went significantly below and came back above
                    if level.broken and level.can_refresh:
                        # Check if price went far below (e.g., 0.5% below)
                        if row['Low'] < level.price * 0.995:
                            # Now if price closes back above, level re-freshes
                            if row['Close'] > level.price:
                                level.fresh = True
                                level.broken = False
                                level.refresh_count += 1
                                level.level_type = 'resistance'  # Flips to resistance
                                logger.debug(f"Level {level.price} re-freshed as resistance")

                elif level.level_type == 'resistance':
                    # Check for touches (wick up to level)
                    if row['Low'] <= level.price <= row['High']:
                        level.touches += 1
                        level.last_touch_time = idx

                        # Check for rejection (close below level)
                        if row['Close'] < level.price:
                            level.rejections += 1

                    # Check for break (body close above)
                    if row['Close'] > level.price and not level.broken:
                        level.fresh = False
                        level.broken = True
                        level.broken_time = idx

                    # Re-freshing logic
                    if level.broken and level.can_refresh:
                        if row['High'] > level.price * 1.005:
                            if row['Close'] < level.price:
                                level.fresh = True
                                level.broken = False
                                level.refresh_count += 1
                                level.level_type = 'support'  # Flips to support
                                logger.debug(f"Level {level.price} re-freshed as support")

        return levels

    def get_fresh_levels(
        self,
        timeframe: str,
        level_type: Optional[str] = None
    ) -> List[SARLevel]:
        """
        Get fresh SAR levels

        Args:
            timeframe: Timeframe to query
            level_type: Optional filter ('support' or 'resistance')

        Returns:
            List of fresh SAR levels
        """

        if timeframe not in self.tracked_levels:
            return []

        fresh = [level for level in self.tracked_levels[timeframe] if level.fresh]

        if level_type:
            fresh = [level for level in fresh if level.level_type == level_type]

        return fresh

    def identify_rejection(
        self,
        df: pd.DataFrame,
        sar_level: SARLevel,
        lookback: int = 3
    ) -> bool:
        """
        Check if recent price action shows rejection at SAR level

        Rejection criteria:
        - Price touched level (wick)
        - Strong close in opposite direction
        - Reversal candle pattern

        Args:
            df: OHLCV DataFrame
            sar_level: SAR level to check
            lookback: Recent candles to check

        Returns:
            True if rejection detected
        """

        recent = df.tail(lookback)

        for idx, row in recent.iterrows():
            if sar_level.level_type == 'support':
                # Bullish rejection at support
                # Wick touched support, closed above
                if row['Low'] <= sar_level.price and row['Close'] > sar_level.price:
                    # Strong close (body > 60% of range)
                    body = abs(row['Close'] - row['Open'])
                    candle_range = row['High'] - row['Low']

                    if candle_range > 0 and body / candle_range > 0.6:
                        return True

            elif sar_level.level_type == 'resistance':
                # Bearish rejection at resistance
                if row['High'] >= sar_level.price and row['Close'] < sar_level.price:
                    body = abs(row['Close'] - row['Open'])
                    candle_range = row['High'] - row['Low']

                    if candle_range > 0 and body / candle_range > 0.6:
                        return True

        return False

    def identify_breakout(
        self,
        df: pd.DataFrame,
        sar_level: SARLevel,
        lookback: int = 3
    ) -> bool:
        """
        Check if SAR level was broken out from

        Breakout criteria:
        - Body close through level
        - Strong momentum

        Args:
            df: OHLCV DataFrame
            sar_level: SAR level to check
            lookback: Recent candles to check

        Returns:
            True if breakout detected
        """

        recent = df.tail(lookback)

        for idx, row in recent.iterrows():
            if sar_level.level_type == 'support':
                # Broke below support
                if row['Close'] < sar_level.price:
                    return True

            elif sar_level.level_type == 'resistance':
                # Broke above resistance
                if row['Close'] > sar_level.price:
                    return True

        return False

    def find_sar_clusters(
        self,
        timeframes: List[str],
        tolerance_pct: float = 0.2
    ) -> List[Dict]:
        """
        Find SAR level clusters across multiple timeframes

        Args:
            timeframes: List of timeframes to check
            tolerance_pct: Clustering tolerance

        Returns:
            List of clustered SAR zones
        """

        clusters = []

        # Collect all fresh levels
        all_levels = []
        for tf in timeframes:
            if tf in self.tracked_levels:
                fresh_levels = [l for l in self.tracked_levels[tf] if l.fresh]
                all_levels.extend(fresh_levels)

        if not all_levels:
            return clusters

        # Group by type
        supports = [l for l in all_levels if l.level_type == 'support']
        resistances = [l for l in all_levels if l.level_type == 'resistance']

        # Cluster supports
        support_clusters = self._find_price_clusters(supports, tolerance_pct)
        clusters.extend(support_clusters)

        # Cluster resistances
        resistance_clusters = self._find_price_clusters(resistances, tolerance_pct)
        clusters.extend(resistance_clusters)

        logger.debug(f"Found {len(clusters)} SAR clusters across timeframes")
        return clusters

    def _find_price_clusters(
        self,
        levels: List[SARLevel],
        tolerance_pct: float
    ) -> List[Dict]:
        """Find price clusters among SAR levels"""

        clusters = []
        used = set()

        for i, level1 in enumerate(levels):
            if i in used:
                continue

            cluster = {
                'levels': [level1],
                'timeframes': [level1.timeframe],
                'avg_price': level1.price,
                'type': level1.level_type
            }

            for j, level2 in enumerate(levels[i+1:], start=i+1):
                if j in used:
                    continue

                price_diff_pct = abs(level1.price - level2.price) / level1.price * 100

                if price_diff_pct <= tolerance_pct and level1.level_type == level2.level_type:
                    cluster['levels'].append(level2)
                    cluster['timeframes'].append(level2.timeframe)
                    used.add(j)

            # Only add if multiple timeframes align
            if len(cluster['levels']) >= 2:
                cluster['avg_price'] = np.mean([l.price for l in cluster['levels']])
                cluster['strength'] = len(cluster['levels'])
                clusters.append(cluster)

            used.add(i)

        return clusters
