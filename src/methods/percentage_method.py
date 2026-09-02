"""
Percentage Method (Method 2)
Monthly-Daily-Hourly-5m with percentage-based structure analysis
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from src.core.data_fetcher import DataFetcher
from src.core.structure_detector import StructureDetector, StructureType, Bias
from src.core.order_block_detector import OrderBlockDetector
from src.core.fvg_detector import FVGDetector
from src.utils.confluence_scorer import ConfluenceScorer, ConfluenceFactors
from src.utils.logger import setup_logger
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


@dataclass
class PercentageSignal:
    """Trade signal from Percentage Method"""
    timestamp: pd.Timestamp
    method: str = "Percentage Method"

    # Entry details
    entry_price: float = 0.0
    entry_timeframe: str = "M5"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    bias: Bias = Bias.NEUTRAL

    # Structure details
    daily_pullback_pct: float = 0.0
    h1_pullback_pct: float = 0.0
    m5_pullback_pct: float = 0.0
    in_premium_discount: bool = False
    zone_type: str = ""  # "premium", "discount", "equilibrium"

    # Confluence
    confluence_score: int = 0
    confluence_details: List[str] = None

    # Monthly projection
    monthly_target: Optional[float] = None
    monthly_direction: str = ""


class PercentageMethod:
    """
    Method 2: Monthly-Daily-Hourly-5m

    Uses 25% Daily and 37.5% H1/M5 pullback requirements
    with Fibonacci zones
    """

    def __init__(self, data_fetcher: DataFetcher):
        """Initialize Percentage Method"""
        self.data_fetcher = data_fetcher
        self.structure_detector = StructureDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg_detector = FVGDetector()
        self.confluence_scorer = ConfluenceScorer()

    def analyze(self) -> Optional[PercentageSignal]:
        """
        Run Percentage Method analysis

        Returns:
            Trade signal if found, None otherwise
        """

        logger.info("Running Percentage Method analysis")

        # Fetch required data
        timeframes = ['MN', 'D1', 'H1', 'M5']
        data = self.data_fetcher.fetch_multiple_timeframes(timeframes)

        if not all(tf in data for tf in ['D1', 'H1', 'M5']):
            logger.warning("Missing required timeframe data")
            return None

        # Step 1: Get Monthly direction (rough target projection)
        monthly_direction, monthly_target = self._analyze_monthly(data.get('MN'))

        # Step 2: Check Daily structure and pullback
        daily_valid, daily_info = self._analyze_daily_structure(data['D1'])
        if not daily_valid:
            logger.debug("Daily structure not valid")
            return None

        # Step 3: Check H1 structure and pullback
        h1_valid, h1_info = self._analyze_h1_structure(data['H1'], daily_info)
        if not h1_valid:
            logger.debug("H1 structure not valid")
            return None

        # Step 4: Look for M5 entry
        signal = self._find_m5_entry(
            data['M5'],
            daily_info,
            h1_info,
            monthly_direction,
            monthly_target
        )

        if signal:
            logger.info(f"Percentage Method signal: {signal.bias.value} at {signal.entry_price}")

        return signal

    def _analyze_monthly(
        self,
        monthly_df: Optional[pd.DataFrame]
    ) -> Tuple[str, Optional[float]]:
        """
        Analyze monthly timeframe for target projection

        Returns:
            (direction, target_price)
        """

        if monthly_df is None or monthly_df.empty or len(monthly_df) < 3:
            return "neutral", None

        # Get last 3 monthly candles
        recent = monthly_df.tail(3)

        # Simple trend determination
        if recent['Close'].iloc[-1] > recent['Close'].iloc[0]:
            direction = "bullish"
            # Project target as recent high + average range
            avg_range = (recent['High'] - recent['Low']).mean()
            target = recent['High'].max() + avg_range
        else:
            direction = "bearish"
            avg_range = (recent['High'] - recent['Low']).mean()
            target = recent['Low'].min() - avg_range

        logger.debug(f"Monthly direction: {direction}, target: {target}")
        return direction, target

    def _analyze_daily_structure(
        self,
        daily_df: pd.DataFrame
    ) -> Tuple[bool, Dict]:
        """
        Analyze Daily structure

        Checks for:
        - MSS (Simple or ICT)
        - 25% pullback requirement
        - OB formation

        Returns:
            (valid, info_dict)
        """

        info = {}

        # Detect structure
        structure_events = self.structure_detector.detect_structure(daily_df, 'D1')

        # Get recent MSS
        recent_mss = [e for e in structure_events if e.type == StructureType.MSS]
        if not recent_mss:
            return False, info

        last_mss = recent_mss[-1]
        info['mss'] = last_mss
        info['bias'] = last_mss.bias

        # Calculate pullback from MSS
        mss_idx = daily_df.index.get_loc(last_mss.timestamp)
        after_mss = daily_df.iloc[mss_idx:]

        if len(after_mss) < 2:
            return False, info

        if last_mss.bias == Bias.BULLISH:
            # Find high after MSS
            high_after_mss = after_mss['High'].max()
            current_price = after_mss['Close'].iloc[-1]

            # Calculate pullback percentage
            pullback_pct = ((high_after_mss - current_price) / high_after_mss) * 100

            # Check 25% requirement
            if pullback_pct < 25.0:
                return False, info

            info['high'] = high_after_mss
            info['low'] = after_mss['Low'].min()
            info['pullback_pct'] = pullback_pct
            info['current_price'] = current_price

            # Detect OBs
            obs = self.ob_detector.detect_order_blocks(after_mss, 'D1')
            fresh_demand = [ob for ob in obs if ob.fresh and ob.bias == Bias.BULLISH]
            info['obs'] = fresh_demand

        else:  # Bearish
            low_after_mss = after_mss['Low'].min()
            current_price = after_mss['Close'].iloc[-1]

            pullback_pct = ((current_price - low_after_mss) / low_after_mss) * 100

            if pullback_pct < 25.0:
                return False, info

            info['high'] = after_mss['High'].max()
            info['low'] = low_after_mss
            info['pullback_pct'] = pullback_pct
            info['current_price'] = current_price

            obs = self.ob_detector.detect_order_blocks(after_mss, 'D1')
            fresh_supply = [ob for ob in obs if ob.fresh and ob.bias == Bias.BEARISH]
            info['obs'] = fresh_supply

        return True, info

    def _analyze_h1_structure(
        self,
        h1_df: pd.DataFrame,
        daily_info: Dict
    ) -> Tuple[bool, Dict]:
        """
        Analyze H1 structure

        Checks for:
        - MSS aligned with Daily
        - 37.5% pullback requirement
        - Premium/Discount zones

        Returns:
            (valid, info_dict)
        """

        info = {}

        # Detect structure
        structure_events = self.structure_detector.detect_structure(h1_df, 'H1')

        # Get recent MSS matching Daily bias
        recent_mss = [
            e for e in structure_events
            if e.type == StructureType.MSS and e.bias == daily_info['bias']
        ]

        if not recent_mss:
            return False, info

        last_mss = recent_mss[-1]
        info['mss'] = last_mss

        # Calculate pullback from MSS
        mss_idx = h1_df.index.get_loc(last_mss.timestamp)
        after_mss = h1_df.iloc[mss_idx:]

        if len(after_mss) < 2:
            return False, info

        if last_mss.bias == Bias.BULLISH:
            high_after_mss = after_mss['High'].max()
            current_price = after_mss['Close'].iloc[-1]
            pullback_pct = ((high_after_mss - current_price) / high_after_mss) * 100

            # Check 37.5% requirement
            if pullback_pct < 37.5:
                return False, info

            info['high'] = high_after_mss
            info['low'] = after_mss['Low'].min()
            info['pullback_pct'] = pullback_pct

            # Calculate zones (0, 0.25, 0.375, 0.5, 1)
            range_size = high_after_mss - info['low']
            info['zones'] = {
                '0': info['low'],
                '0.25': info['low'] + range_size * 0.25,
                '0.375': info['low'] + range_size * 0.375,
                '0.5': info['low'] + range_size * 0.5,
                '1': high_after_mss
            }

            # Check if in discount zone (0-0.375)
            if current_price <= info['zones']['0.375']:
                info['in_discount'] = True
            else:
                return False, info

            # Detect OBs
            obs = self.ob_detector.detect_order_blocks(after_mss, 'H1')
            fresh_demand = [ob for ob in obs if ob.fresh and ob.bias == Bias.BULLISH]
            info['obs'] = fresh_demand

        else:  # Bearish
            low_after_mss = after_mss['Low'].min()
            current_price = after_mss['Close'].iloc[-1]
            pullback_pct = ((current_price - low_after_mss) / low_after_mss) * 100

            if pullback_pct < 37.5:
                return False, info

            info['high'] = after_mss['High'].max()
            info['low'] = low_after_mss
            info['pullback_pct'] = pullback_pct

            # Calculate zones
            range_size = info['high'] - low_after_mss
            info['zones'] = {
                '0': info['high'],
                '0.25': info['high'] - range_size * 0.25,
                '0.375': info['high'] - range_size * 0.375,
                '0.5': info['high'] - range_size * 0.5,
                '1': low_after_mss
            }

            # Check if in premium zone (0.375-1)
            if current_price >= info['zones']['0.375']:
                info['in_premium'] = True
            else:
                return False, info

            obs = self.ob_detector.detect_order_blocks(after_mss, 'H1')
            fresh_supply = [ob for ob in obs if ob.fresh and ob.bias == Bias.BEARISH]
            info['obs'] = fresh_supply

        return True, info

    def _find_m5_entry(
        self,
        m5_df: pd.DataFrame,
        daily_info: Dict,
        h1_info: Dict,
        monthly_direction: str,
        monthly_target: Optional[float]
    ) -> Optional[PercentageSignal]:
        """
        Find M5 entry point

        Looks for:
        - MSS on M5
        - Fresh OB in discount/premium zone
        - Confluence with H1

        Returns:
            Signal if entry found
        """

        # Detect M5 structure
        structure_events = self.structure_detector.detect_structure(m5_df, 'M5')

        # Get recent MSS matching bias
        bias = daily_info['bias']
        recent_mss = [
            e for e in structure_events
            if e.type == StructureType.MSS and e.bias == bias
        ]

        if not recent_mss:
            return None

        last_mss = recent_mss[-1]

        # Check if MSS is recent (within last 20 candles)
        mss_idx = m5_df.index.get_loc(last_mss.timestamp)
        if len(m5_df) - mss_idx > 20:
            return None

        # Detect OBs
        obs = self.ob_detector.detect_order_blocks(m5_df, 'M5')
        fresh_obs = [ob for ob in obs if ob.fresh and ob.bias == bias]

        if not fresh_obs:
            return None

        # Get closest OB to current price
        current_price = m5_df['Close'].iloc[-1]
        closest_ob = min(fresh_obs, key=lambda ob: abs((ob.high + ob.low) / 2 - current_price))

        # Detect FVGs
        fvgs = self.fvg_detector.detect_fvgs(m5_df, 'M5')
        fresh_fvgs = [fvg for fvg in fvgs if fvg.fresh and fvg.bias == bias]

        # Calculate confluence
        factors = ConfluenceFactors()
        factors.mss_present = True
        factors.ob_fresh = True
        factors.premium_discount_alignment = h1_info.get('in_discount') or h1_info.get('in_premium', False)
        factors.htf_structure_aligned = True  # Daily + H1 aligned

        if fresh_fvgs:
            factors.fvg_present = True

        if daily_info.get('obs'):
            factors.ob_alignment_2tf = True

        confluence_result = self.confluence_scorer.score_percentage_method(factors)

        if not confluence_result['passed']:
            logger.debug(f"Confluence failed: {confluence_result['score']}/{confluence_result['min_required']}")
            return None

        # Build signal
        signal = PercentageSignal(
            timestamp=m5_df.index[-1],
            bias=bias,
            entry_price=(closest_ob.high + closest_ob.low) / 2,
            entry_timeframe='M5',
            daily_pullback_pct=daily_info['pullback_pct'],
            h1_pullback_pct=h1_info['pullback_pct'],
            in_premium_discount=True,
            monthly_target=monthly_target,
            monthly_direction=monthly_direction,
            confluence_score=confluence_result['score'],
            confluence_details=confluence_result['details']
        )

        # Calculate SL and TP
        if bias == Bias.BULLISH:
            signal.stop_loss = closest_ob.low - (closest_ob.high - closest_ob.low) * 0.1
            signal.take_profit = h1_info['high']
            signal.zone_type = "discount"
        else:
            signal.stop_loss = closest_ob.high + (closest_ob.high - closest_ob.low) * 0.1
            signal.take_profit = h1_info['low']
            signal.zone_type = "premium"

        return signal
