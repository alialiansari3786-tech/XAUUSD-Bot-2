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
        use_atr: bool = True
    ) -> List[LiquidityLevel]:
        """
        Detect Equal Highs (EQH) and Equal Lows (EQL)
        Uses ATR-based tolerance from Guardeer logic

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            use_atr: Use ATR for tolerance calculation

        Returns:
            List of EQH/EQL levels
        """

        levels = []

        if len(df) < settings.ATR_PERIOD:
            return levels

        # Calculate ATR for tolerance
        if use_atr:
            df = df.copy()
            df['TR'] = df[['High', 'Low', 'Close']].apply(
                lambda x: max(
                    x['High'] - x['Low'],
                    abs(x['High'] - x['Close']),
                    abs(x['Low'] - x['Close'])
                ),
                axis=1
            )
            atr = df['TR'].rolling(settings.ATR_PERIOD).mean().iloc[-1]
            tolerance = atr * settings.EQH_EQL_THRESHOLD_MULTIPLIER
        else:
            # Use percentage-based tolerance
            tolerance = df['Close'].iloc[-1] * 0.001  # 0.1%

        # Find Equal Highs
        highs = df['High'].values
        for i in range(len(highs) - 1):
            for j in range(i + 1, len(highs)):
                if abs(highs[i] - highs[j]) <= tolerance:
                    # Equal high found
                    levels.append(LiquidityLevel(
                        level_type=LiquidityType.EQH,
                        price=(highs[i] + highs[j]) / 2,
                        timestamp=df.index[j],
                        timeframe=timeframe,
                        taken=False,
                        reference_points=[highs[i], highs[j]],
                        tolerance=tolerance
                    ))

        # Find Equal Lows
        lows = df['Low'].values
        for i in range(len(lows) - 1):
            for j in range(i + 1, len(lows)):
                if abs(lows[i] - lows[j]) <= tolerance:
                    # Equal low found
                    levels.append(LiquidityLevel(
                        level_type=LiquidityType.EQL,
                        price=(lows[i] + lows[j]) / 2,
                        timestamp=df.index[j],
                        timeframe=timeframe,
                        taken=False,
                        reference_points=[lows[i], lows[j]],
                        tolerance=tolerance
                    ))

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
