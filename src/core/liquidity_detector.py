"""
Liquidity Detector Module
Detects liquidity levels: Weekly/Daily High-Low, Swing High-Low, EQH/EQL, Old High-Low, DOL
"""

import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

from src.utils.logger import setup_logger
from src.core.structure_detector import SwingPoint
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


class LiquidityType(Enum):
    """Types of liquidity"""
    WEEKLY_HIGH = "Weekly High"
    WEEKLY_LOW = "Weekly Low"
    DAILY_HIGH = "Daily High"
    DAILY_LOW = "Daily Low"
    SWING_HIGH = "Swing High"
    SWING_LOW = "Swing Low"
    EQH = "Equal High"
    EQL = "Equal Low"
    OLD_HIGH = "Old High"
    OLD_LOW = "Old Low"
    DOL = "Draw on Liquidity"


@dataclass
class LiquidityLevel:
    """Liquidity level representation"""
    level_type: LiquidityType
    price: float
    timestamp: pd.Timestamp
    timeframe: str
    taken: bool = False
    taken_timestamp: Optional[pd.Timestamp] = None

    # For EQH/EQL
    reference_points: Optional[List[float]] = None
    tolerance: Optional[float] = None


class LiquidityDetector:
    """Detects liquidity levels across timeframes"""

    def __init__(self):
        """Initialize LiquidityDetector"""
        self.tracked_liquidity: Dict[str, List[LiquidityLevel]] = {}

    def detect_all_liquidity(
        self,
        data_dict: Dict[str, pd.DataFrame],
        current_price: float
    ) -> List[LiquidityLevel]:
        """
        Detect all liquidity levels across timeframes

        Args:
            data_dict: Dictionary mapping timeframe to DataFrame
            current_price: Current market price

        Returns:
            List of all liquidity levels
        """

        all_liquidity = []

        # Weekly High/Low
        if 'W1' in data_dict:
            weekly_liq = self.detect_weekly_levels(data_dict['W1'])
            all_liquidity.extend(weekly_liq)

        # Daily High/Low
        if 'D1' in data_dict:
            daily_liq = self.detect_daily_levels(data_dict['D1'])
            all_liquidity.extend(daily_liq)

        # Swing High/Low on multiple timeframes
        for tf in ['D1', 'H4', 'H1', 'M15']:
            if tf in data_dict:
                swing_liq = self.detect_swing_levels(data_dict[tf], tf)
                all_liquidity.extend(swing_liq)

        # Equal Highs/Lows
        for tf in ['D1', 'H4', 'H1', 'M15']:
            if tf in data_dict:
                eq_liq = self.detect_equal_levels(data_dict[tf], tf)
                all_liquidity.extend(eq_liq)

        # Old High/Low (levels from past that haven't been revisited)
        for tf in ['D1', 'H4', 'H1']:
            if tf in data_dict:
                old_liq = self.detect_old_levels(data_dict[tf], tf)
                all_liquidity.extend(old_liq)

        # Update taken status
        all_liquidity = self._update_liquidity_status(all_liquidity, current_price)

        logger.debug(f"Detected {len(all_liquidity)} liquidity levels")
        return all_liquidity

    def detect_weekly_levels(self, df: pd.DataFrame) -> List[LiquidityLevel]:
        """Detect weekly high/low levels"""

        levels = []

        if df.empty or len(df) < 1:
            return levels

        # Get last week's high and low
        last_week = df.tail(2).iloc[0] if len(df) >= 2 else df.iloc[-1]

        levels.append(LiquidityLevel(
            level_type=LiquidityType.WEEKLY_HIGH,
            price=last_week['High'],
            timestamp=last_week.name,
            timeframe='W1',
            taken=False
        ))

        levels.append(LiquidityLevel(
            level_type=LiquidityType.WEEKLY_LOW,
            price=last_week['Low'],
            timestamp=last_week.name,
            timeframe='W1',
            taken=False
        ))

        return levels

    def detect_daily_levels(self, df: pd.DataFrame) -> List[LiquidityLevel]:
        """Detect daily high/low levels"""

        levels = []

        if df.empty or len(df) < 1:
            return levels

        # Get last day's high and low
        last_day = df.iloc[-1]

        levels.append(LiquidityLevel(
            level_type=LiquidityType.DAILY_HIGH,
            price=last_day['High'],
            timestamp=last_day.name,
            timeframe='D1',
            taken=False
        ))

        levels.append(LiquidityLevel(
            level_type=LiquidityType.DAILY_LOW,
            price=last_day['Low'],
            timestamp=last_day.name,
            timeframe='D1',
            taken=False
        ))

        return levels

    def detect_swing_levels(
        self,
        df: pd.DataFrame,
        timeframe: str,
        lookback: int = 5
    ) -> List[LiquidityLevel]:
        """Detect swing high/low levels"""

        levels = []

        # Find swing highs
        for i in range(lookback, len(df) - lookback):
            high = df['High'].iloc[i]
            is_swing_high = True

            for j in range(1, lookback + 1):
                if df['High'].iloc[i - j] >= high or df['High'].iloc[i + j] >= high:
                    is_swing_high = False
                    break

            if is_swing_high:
                levels.append(LiquidityLevel(
                    level_type=LiquidityType.SWING_HIGH,
                    price=high,
                    timestamp=df.index[i],
                    timeframe=timeframe,
                    taken=False
                ))

        # Find swing lows
        for i in range(lookback, len(df) - lookback):
            low = df['Low'].iloc[i]
            is_swing_low = True

            for j in range(1, lookback + 1):
                if df['Low'].iloc[i - j] <= low or df['Low'].iloc[i + j] <= low:
                    is_swing_low = False
                    break

            if is_swing_low:
                levels.append(LiquidityLevel(
                    level_type=LiquidityType.SWING_LOW,
                    price=low,
                    timestamp=df.index[i],
                    timeframe=timeframe,
                    taken=False
                ))

        return levels

    def detect_equal_levels(
        self,
        df: pd.DataFrame,
        timeframe: str,
        use_atr: bool = True,
        lookback: int = 300
    ) -> List[LiquidityLevel]:
        """
        Detect Equal Highs (EQH) and Equal Lows (EQL)
        Uses ATR-based tolerance from Guardeer logic

        PERFORMANCE NOTE: The original implementation compared every
        candle to every other candle (O(n^2) pure-Python loop). On a
        1-year H1 history (~5,700 candles) that alone produces
        600,000+ "equal" matches, each turned into a LiquidityLevel
        object; on M15/M5 histories it's worse. That flood of
        near-duplicate levels is what was causing the bot to hang for
        minutes downstream (every level can trigger a "sweep", and
        each sweep re-triggers a full OB+FVG+SAR scan). This version
        sorts once and clusters nearby prices (O(n log n)), and only
        looks at the most recent `lookback` candles, since equal
        highs/lows are a recent-price-action concept, not an all-time
        pairwise scan.

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            use_atr: Use ATR for tolerance calculation
            lookback: Only consider the most recent N candles

        Returns:
            List of EQH/EQL levels (one per cluster of equal prices)
        """

        levels = []

        if len(df) < settings.ATR_PERIOD:
            return levels

        # Calculate ATR for tolerance (vectorized, no .apply/axis=1)
        if use_atr:
            high_low = df['High'] - df['Low']
            high_close = (df['High'] - df['Close'].shift()).abs()
            low_close = (df['Low'] - df['Close'].shift()).abs()
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = true_range.rolling(settings.ATR_PERIOD).mean().iloc[-1]
            tolerance = atr * settings.EQH_EQL_THRESHOLD_MULTIPLIER
        else:
            # Use percentage-based tolerance
            tolerance = df['Close'].iloc[-1] * 0.001  # 0.1%

        if pd.isna(tolerance) or tolerance <= 0:
            return levels

        recent = df.tail(lookback)
        timestamps = recent.index

        levels.extend(self._cluster_equal_prices(
            recent['High'].to_numpy(), timestamps, tolerance, LiquidityType.EQH, timeframe
        ))
        levels.extend(self._cluster_equal_prices(
            recent['Low'].to_numpy(), timestamps, tolerance, LiquidityType.EQL, timeframe
        ))

        return levels

    def _cluster_equal_prices(
        self,
        prices: np.ndarray,
        timestamps: pd.Index,
        tolerance: float,
        level_type: 'LiquidityType',
        timeframe: str
    ) -> List[LiquidityLevel]:
        """
        Cluster near-equal prices in O(n log n) instead of comparing
        every pair. Sort the prices, keep track of which candle each
        sorted value came from, and walk through once: consecutive
        values within `tolerance` of each other form one cluster,
        which becomes a single EQH/EQL level (not one level per pair).
        """

        if len(prices) == 0:
            return []

        order = np.argsort(prices)
        sorted_prices = prices[order]

        levels = []
        cluster_prices = [sorted_prices[0]]
        cluster_positions = [order[0]]

        def flush():
            if len(cluster_prices) >= 2:
                avg_price = float(np.mean(cluster_prices))
                latest_pos = max(cluster_positions)
                levels.append(LiquidityLevel(
                    level_type=level_type,
                    price=avg_price,
                    timestamp=timestamps[latest_pos],
                    timeframe=timeframe,
                    taken=False,
                    reference_points=[float(p) for p in cluster_prices],
                    tolerance=tolerance
                ))

        for k in range(1, len(sorted_prices)):
            if sorted_prices[k] - cluster_prices[-1] <= tolerance:
                cluster_prices.append(sorted_prices[k])
                cluster_positions.append(order[k])
            else:
                flush()
                cluster_prices = [sorted_prices[k]]
                cluster_positions = [order[k]]

        flush()
        return levels

    def detect_old_levels(
        self,
        df: pd.DataFrame,
        timeframe: str,
        days_old: int = 5
    ) -> List[LiquidityLevel]:
        """
        Detect old high/low levels that haven't been revisited

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            days_old: Minimum age in days

        Returns:
            List of old levels
        """

        levels = []

        if df.empty:
            return levels

        # Find significant highs/lows from the past
        cutoff_date = df.index[-1] - timedelta(days=days_old)
        old_data = df[df.index < cutoff_date]

        if old_data.empty:
            return levels

        # Find highest high and lowest low in old data
        old_high = old_data['High'].max()
        old_low = old_data['Low'].min()

        # Check if these levels haven't been revisited
        recent_data = df[df.index >= cutoff_date]

        if not recent_data.empty:
            recent_high = recent_data['High'].max()
            recent_low = recent_data['Low'].min()

            # Old high not revisited
            if recent_high < old_high:
                old_high_timestamp = old_data[old_data['High'] == old_high].index[0]
                levels.append(LiquidityLevel(
                    level_type=LiquidityType.OLD_HIGH,
                    price=old_high,
                    timestamp=old_high_timestamp,
                    timeframe=timeframe,
                    taken=False
                ))

            # Old low not revisited
            if recent_low > old_low:
                old_low_timestamp = old_data[old_data['Low'] == old_low].index[0]
                levels.append(LiquidityLevel(
                    level_type=LiquidityType.OLD_LOW,
                    price=old_low,
                    timestamp=old_low_timestamp,
                    timeframe=timeframe,
                    taken=False
                ))

        return levels

    def _update_liquidity_status(
        self,
        levels: List[LiquidityLevel],
        current_price: float
    ) -> List[LiquidityLevel]:
        """
        Update taken status of liquidity levels

        Level is considered taken when:
        - Price wicks through it (for high: price goes above, for low: price goes below)

        Args:
            levels: List of liquidity levels
            current_price: Current market price

        Returns:
            Updated levels
        """

        for level in levels:
            if level.taken:
                continue

            # High levels taken when price goes above
            if level.level_type in [
                LiquidityType.WEEKLY_HIGH,
                LiquidityType.DAILY_HIGH,
                LiquidityType.SWING_HIGH,
                LiquidityType.EQH,
                LiquidityType.OLD_HIGH
            ]:
                if current_price > level.price:
                    level.taken = True
                    level.taken_timestamp = datetime.now()

            # Low levels taken when price goes below
            elif level.level_type in [
                LiquidityType.WEEKLY_LOW,
                LiquidityType.DAILY_LOW,
                LiquidityType.SWING_LOW,
                LiquidityType.EQL,
                LiquidityType.OLD_LOW
            ]:
                if current_price < level.price:
                    level.taken = True
                    level.taken_timestamp = datetime.now()

        return levels

    def get_untaken_liquidity(
        self,
        levels: List[LiquidityLevel],
        bias: Optional[str] = None
    ) -> List[LiquidityLevel]:
        """
        Get untaken liquidity levels

        Args:
            levels: All liquidity levels
            bias: Optional filter ('bullish' for highs, 'bearish' for lows)

        Returns:
            Untaken liquidity levels
        """

        untaken = [level for level in levels if not level.taken]

        if bias == 'bullish':
            # Bullish: Target highs above
            untaken = [
                level for level in untaken
                if level.level_type in [
                    LiquidityType.WEEKLY_HIGH,
                    LiquidityType.DAILY_HIGH,
                    LiquidityType.SWING_HIGH,
                    LiquidityType.EQH,
                    LiquidityType.OLD_HIGH
                ]
            ]
        elif bias == 'bearish':
            # Bearish: Target lows below
            untaken = [
                level for level in untaken
                if level.level_type in [
                    LiquidityType.WEEKLY_LOW,
                    LiquidityType.DAILY_LOW,
                    LiquidityType.SWING_LOW,
                    LiquidityType.EQL,
                    LiquidityType.OLD_LOW
                ]
            ]

        return untaken

    def identify_liquidity_sweep(
        self,
        df: pd.DataFrame,
        liquidity_levels: List[LiquidityLevel],
        lookback: int = 5
    ) -> List[Dict]:
        """
        Identify liquidity sweeps (price took liquidity and reversed)

        Args:
            df: OHLCV DataFrame
            liquidity_levels: List of liquidity levels
            lookback: Lookback period for reversal detection

        Returns:
            List of sweep events
        """

        sweeps = []

        recent_data = df.tail(lookback)

        for level in liquidity_levels:
            if not level.taken:
                continue

            # Check if sweep was recent
            for i, row in recent_data.iterrows():
                # Bullish sweep: Swept low and reversed up
                if level.level_type in [
                    LiquidityType.SWING_LOW,
                    LiquidityType.DAILY_LOW,
                    LiquidityType.EQL
                ]:
                    if row['Low'] < level.price < row['Close']:
                        # Swept and closed above
                        sweeps.append({
                            'type': 'bullish_sweep',
                            'level': level,
                            'sweep_time': i,
                            'sweep_low': row['Low'],
                            'close': row['Close']
                        })

                # Bearish sweep: Swept high and reversed down
                elif level.level_type in [
                    LiquidityType.SWING_HIGH,
                    LiquidityType.DAILY_HIGH,
                    LiquidityType.EQH
                ]:
                    if row['High'] > level.price > row['Close']:
                        # Swept and closed below
                        sweeps.append({
                            'type': 'bearish_sweep',
                            'level': level,
                            'sweep_time': i,
                            'sweep_high': row['High'],
                            'close': row['Close']
                        })

        return sweeps
