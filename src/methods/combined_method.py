"""
Combined Method (Method 1)
Multi-timeframe analysis with STL/STH tracking and IDM identification
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.core.data_fetcher import DataFetcher
from src.core.structure_detector import StructureDetector, STLSTHLevel, Bias, StructureType
from src.core.order_block_detector import OrderBlockDetector
from src.core.fvg_detector import FVGDetector
from src.utils.confluence_scorer import ConfluenceScorer, ConfluenceFactors
from src.utils.logger import setup_logger
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


@dataclass
class CombinedSignal:
    """Trade signal from Combined Method"""
    timestamp: pd.Timestamp
    method: str = "Combined Method"

    # Entry details
    entry_price: float = 0.0
    entry_timeframe: str = "M15"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    bias: Bias = Bias.NEUTRAL

    # STL/STH structure
    stl_sth_level: Optional[STLSTHLevel] = None
    idm_present: bool = False
    trading_range: Optional[Tuple[float, float]] = None

    # OB alignment
    aligned_timeframes: List[str] = None
    ob_count: int = 0

    # Confluence
    confluence_score: int = 0
    confluence_details: List[str] = None

    # HTF context
    weekly_pullback: bool = False
    htf_target: Optional[float] = None


class CombinedMethod:
    """
    Method 1: Combined Method

    Multi-timeframe analysis (Weekly, Daily, 4H, 1H, 15m, 5m/3m)
    with STL/STH structure tracking and IDM identification
    """

    def __init__(self, data_fetcher: DataFetcher):
        """Initialize Combined Method"""
        self.data_fetcher = data_fetcher
        self.structure_detector = StructureDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg_detector = FVGDetector()
        self.confluence_scorer = ConfluenceScorer()

    def analyze(self) -> Optional[CombinedSignal]:
        """
        Run Combined Method analysis

        Returns:
            Trade signal if found, None otherwise
        """

        logger.info("Running Combined Method analysis")

        # Fetch required data
        timeframes = ['W1', 'D1', 'H4', 'H1', 'M15', 'M5']
        data = self.data_fetcher.fetch_multiple_timeframes(timeframes)

        # H4 is optional - if it fails, continue with other timeframes
        required = ['D1', 'H1', 'M15']
        if not all(tf in data for tf in required):
            missing = [tf for tf in required if tf not in data]
            logger.warning(f"Missing required timeframe data: {missing}")
            return None

        # Log if H4 is missing (optional but preferred)
        if 'H4' not in data:
            logger.info("H4 data unavailable - continuing without it")

        # Step 1: Analyze Weekly for HTF context
        weekly_context = self._analyze_weekly(data.get('W1'), data['D1'])

        # Step 2: Track STL/STH on Daily
        daily_stl_sth = self.structure_detector.track_stl_sth(data['D1'], 'D1')

        # Step 3: Identify trading ranges and mark OBs
        ob_zones = self._identify_ob_zones(data, daily_stl_sth)

        if not ob_zones:
            logger.debug("No valid OB zones found")
            return None

        # Step 4: Check for OB alignment
        aligned_obs = self._check_ob_alignment(ob_zones)

        if not aligned_obs:
            logger.debug("No OB alignment found")
            return None

        # Step 5: Find entry on 15m or 5m
        signal = self._find_entry(
            data,
            aligned_obs,
            daily_stl_sth,
            weekly_context
        )

        if signal:
            logger.info(f"Combined Method signal: {signal.bias.value} at {signal.entry_price}")

        return signal

    def _analyze_weekly(
        self,
        weekly_df: Optional[pd.DataFrame],
        daily_df: pd.DataFrame
    ) -> Dict:
        """
        Analyze Weekly timeframe for HTF context

        Determines if in HTF pullback scenario

        Returns:
            Context dictionary
        """

        context = {
            'in_pullback': False,
            'weekly_high': None,
            'weekly_low': None,
            'target': None
        }

        if weekly_df is None or weekly_df.empty:
            return context

        # Get last weekly candle
        last_week = weekly_df.iloc[-1]
        context['weekly_high'] = last_week['High']
        context['weekly_low'] = last_week['Low']

        # Check if Daily is pulling back to Weekly structure
        daily_current = daily_df['Close'].iloc[-1]
        daily_range = daily_df['High'].iloc[-20:].max() - daily_df['Low'].iloc[-20:].min()

        # Simple pullback detection: If price moved significantly from weekly high/low
        if last_week['Close'] > last_week['Open']:  # Bullish week
            # Check if pulling back
            if daily_current < last_week['High'] * 0.985:  # More than 1.5% pullback
                context['in_pullback'] = True
                context['target'] = last_week['High']

        else:  # Bearish week
            if daily_current > last_week['Low'] * 1.015:
                context['in_pullback'] = True
                context['target'] = last_week['Low']

        return context

    def _identify_ob_zones(
        self,
        data: Dict[str, pd.DataFrame],
        stl_sth: STLSTHLevel
    ) -> Dict[str, List]:
        """
        Identify OB zones within valid trading ranges

        Args:
            data: Dictionary of timeframe data
            stl_sth: STL/STH level tracking

        Returns:
            Dictionary mapping timeframe to OB list
        """

        ob_zones = {}

        # Determine trading range from STL/STH
        if stl_sth.trading_range_start and stl_sth.trading_range_end:
            trading_range = (
                min(stl_sth.trading_range_start, stl_sth.trading_range_end),
                max(stl_sth.trading_range_start, stl_sth.trading_range_end)
            )
        else:
            trading_range = None

        # Detect OBs on each HTF
        for tf in ['D1', 'H4', 'H1', 'M15']:
            if tf not in data:
                continue

            obs = self.ob_detector.detect_order_blocks(
                data[tf],
                tf,
                trading_range=trading_range
            )

            # Filter for fresh OBs in trading range
            if trading_range:
                valid_obs = [ob for ob in obs if ob.fresh and ob.in_trading_range]
            else:
                valid_obs = [ob for ob in obs if ob.fresh]

            if valid_obs:
                ob_zones[tf] = valid_obs

        return ob_zones

    def _check_ob_alignment(
        self,
        ob_zones: Dict[str, List]
    ) -> List[Dict]:
        """
        Check for OB alignment across timeframes

        Args:
            ob_zones: Dictionary of OBs per timeframe

        Returns:
            List of aligned OB groups
        """

        # Check for different confluence levels
        aligned_groups = []

        timeframe_combinations = [
            ['D1', 'H4', 'H1', 'M15'],  # 4-TF alignment
            ['D1', 'H4', 'H1'],         # 3-TF alignment
            ['D1', 'H4'],               # Daily + 4H
            ['D1', 'H1'],               # Daily + 1H
            ['H4', 'H1'],               # 4H + 1H
        ]

        for combo in timeframe_combinations:
            # Check if all timeframes in combo have OBs
            if not all(tf in ob_zones for tf in combo):
                continue

            # Find overlapping OBs
            aligned = self.ob_detector.check_ob_alignment(combo)

            if aligned:
                for group in aligned:
                    group['tf_count'] = len(combo)
                aligned_groups.extend(aligned)

        # Sort by TF count (prefer more TF alignment)
        aligned_groups.sort(key=lambda x: x.get('tf_count', 0), reverse=True)

        return aligned_groups

    def _find_entry(
        self,
        data: Dict[str, pd.DataFrame],
        aligned_obs: List[Dict],
        stl_sth: STLSTHLevel,
        weekly_context: Dict
    ) -> Optional[CombinedSignal]:
        """
        Find entry on 15m or 5m timeframe

        Args:
            data: Timeframe data
            aligned_obs: Aligned OB groups
            stl_sth: STL/STH tracking
            weekly_context: Weekly context

        Returns:
            Signal if entry found
        """

        if not aligned_obs:
            return None

        # Take best aligned group (highest TF count)
        best_group = aligned_obs[0]
        bias = best_group['bias']

        # Check for MSS on entry timeframe
        entry_tf = 'M15' if 'M15' in data else 'M5'
        entry_df = data[entry_tf]

        structure_events = self.structure_detector.detect_structure(entry_df, entry_tf)

        # Get recent MSS matching bias
        recent_mss = [
            e for e in structure_events
            if e.type == StructureType.MSS and e.bias == bias
        ]

        if not recent_mss:
            # Try M5 if M15 didn't work
            if entry_tf == 'M15' and 'M5' in data:
                entry_tf = 'M5'
                entry_df = data['M5']
                structure_events = self.structure_detector.detect_structure(entry_df, entry_tf)
                recent_mss = [
                    e for e in structure_events
                    if e.type == StructureType.MSS and e.bias == bias
                ]

        if not recent_mss:
            return None

        last_mss = recent_mss[-1]

        # Check if MSS is recent
        mss_idx = entry_df.index.get_loc(last_mss.timestamp)
        if len(entry_df) - mss_idx > 15:
            return None

        # Detect FVGs on entry timeframe
        fvgs = self.fvg_detector.detect_fvgs(entry_df, entry_tf)
        fresh_fvgs = [fvg for fvg in fvgs if fvg.fresh and fvg.bias == bias]

        # Calculate confluence
        factors = ConfluenceFactors()
        factors.mss_present = True

        # TF alignment
        tf_count = best_group.get('tf_count', 0)
        if tf_count >= 4:
            factors.ob_alignment_4tf = True
        elif tf_count >= 3:
            factors.ob_alignment_3tf = True
        elif tf_count >= 2:
            factors.ob_alignment_2tf = True

        # OB quality
        factors.ob_fresh = True
        factors.ob_untested = True

        # FVG
        if fresh_fvgs:
            factors.fvg_fresh = True

        # HTF context
        if weekly_context.get('in_pullback'):
            factors.htf_trend_aligned = True

        # IDM present
        if stl_sth.idm:
            # IDM adds to confluence (counted in scoring)
            pass

        confluence_result = self.confluence_scorer.score_combined_method(factors)

        if not confluence_result['passed']:
            logger.debug(f"Confluence failed: {confluence_result['score']}/{confluence_result['min_required']}")
            return None

        # Build signal
        entry_price = best_group['avg_low'] if bias == Bias.BULLISH else best_group['avg_high']
        current_price = entry_df['Close'].iloc[-1]

        signal = CombinedSignal(
            timestamp=entry_df.index[-1],
            bias=bias,
            entry_price=entry_price,
            entry_timeframe=entry_tf,
            stl_sth_level=stl_sth,
            idm_present=stl_sth.idm is not None,
            trading_range=(stl_sth.trading_range_start, stl_sth.trading_range_end) if stl_sth.trading_range_start else None,
            aligned_timeframes=best_group['timeframes'],
            ob_count=len(best_group['obs']),
            confluence_score=confluence_result['score'],
            confluence_details=confluence_result['details'],
            weekly_pullback=weekly_context.get('in_pullback', False),
            htf_target=weekly_context.get('target')
        )

        # Calculate SL and TP
        if bias == Bias.BULLISH:
            signal.stop_loss = best_group['avg_low'] - (best_group['avg_high'] - best_group['avg_low']) * 0.2

            # TP: HTF target or next resistance
            if weekly_context.get('target'):
                signal.take_profit = weekly_context['target']
            elif stl_sth.sth:
                signal.take_profit = stl_sth.sth.price
            else:
                # Use 2:1 RR
                signal.take_profit = entry_price + (entry_price - signal.stop_loss) * 2

        else:  # Bearish
            signal.stop_loss = best_group['avg_high'] + (best_group['avg_high'] - best_group['avg_low']) * 0.2

            if weekly_context.get('target'):
                signal.take_profit = weekly_context['target']
            elif stl_sth.stl:
                signal.take_profit = stl_sth.stl.price
            else:
                signal.take_profit = entry_price - (signal.stop_loss - entry_price) * 2

        return signal
