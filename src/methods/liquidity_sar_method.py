"""
Liquidity SAR Method (Method 3)
Liquidity-driven entries with SAR strategy integration
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.core.data_fetcher import DataFetcher
from src.core.structure_detector import StructureDetector, Bias, StructureType
from src.core.order_block_detector import OrderBlockDetector
from src.core.fvg_detector import FVGDetector
from src.core.liquidity_detector import LiquidityDetector, LiquidityType
from src.core.sar_detector import SARDetector
from src.core.pattern_detector import PatternDetector, PatternType
from src.utils.confluence_scorer import ConfluenceScorer, ConfluenceFactors
from src.utils.logger import setup_logger
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


@dataclass
class LiquiditySARSignal:
    """Trade signal from Liquidity SAR Method"""
    timestamp: pd.Timestamp
    method: str = "Liquidity SAR Method"

    # Entry details
    entry_price: float = 0.0
    entry_timeframe: str = "M15"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    bias: Bias = Bias.NEUTRAL

    # Liquidity context
    liquidity_swept: List[str] = None
    liquidity_type: str = ""  # "grab" or "sweep"
    target_liquidity: Optional[float] = None

    # SAR levels
    fresh_sar_level: Optional[float] = None
    sar_rejection: bool = False
    sar_breakout: bool = False

    # Trade zone
    trade_zone_type: str = ""  # "OB", "FVG", "OB+FVG", "OB+FVG+SAR"
    blue_zone: Optional[Tuple[float, float]] = None

    # Pattern
    pattern_type: Optional[PatternType] = None
    pattern_strength: str = ""

    # Entry model
    entry_model: str = ""  # "MSS", "CISD", "Unicorn", "Turtle Soup", "SCOB"

    # Confluence
    confluence_score: int = 0
    confluence_details: List[str] = None

    # Multi-entry potential
    can_multi_entry: bool = False


class LiquiditySARMethod:
    """
    Method 3: Liquidity + SAR Strategy

    8-layer confirmation system:
    1. Liquidity sweep detection
    2. Trade zone identification (OB/FVG)
    3. SAR rejection
    4. SAR breakout
    5. Pullback to blue zone
    6. Entry signal (MSS/CISD/etc)
    7. W/M pattern confirmation
    8. Fresh level entry
    """

    def __init__(self, data_fetcher: DataFetcher):
        """Initialize Liquidity SAR Method"""
        self.data_fetcher = data_fetcher
        self.structure_detector = StructureDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg_detector = FVGDetector()
        self.liquidity_detector = LiquidityDetector()
        self.sar_detector = SARDetector()
        self.pattern_detector = PatternDetector()
        self.confluence_scorer = ConfluenceScorer()

    def analyze(self) -> Optional[LiquiditySARSignal]:
        """
        Run Liquidity SAR Method analysis

        Returns:
            Trade signal if found, None otherwise
        """

        logger.info("Running Liquidity SAR Method analysis")

        # Fetch required data
        timeframes = ['D1', 'H4', 'H1', 'M30', 'M15', 'M5']
        data = self.data_fetcher.fetch_multiple_timeframes(timeframes)

        required = ['H1', 'M15']
        if not all(tf in data for tf in required):
            missing = [tf for tf in required if tf not in data]
            logger.warning(f"Missing required timeframe data: {missing}")
            return None

        # Log if optional timeframes are missing
        if 'H4' not in data:
            logger.info("H4 data unavailable - continuing without it")
        if 'M30' not in data:
            logger.info("M30 data unavailable - continuing without it")

        current_price = data['M15']['Close'].iloc[-1]

        # Step 1: Detect all liquidity levels
        all_liquidity = self.liquidity_detector.detect_all_liquidity(data, current_price)

        # Step 2: Identify liquidity sweeps
        sweeps = self.liquidity_detector.identify_liquidity_sweep(
            data['M15'],
            all_liquidity,
            lookback=10
        )

        if not sweeps:
            logger.debug("No liquidity sweeps detected")
            return None

        logger.debug(f"Validating {len(sweeps)} liquidity sweep(s)")

        # Step 3: For each sweep, check full validation chain
        #
        # _identify_trade_zones() runs OB + FVG + SAR detection across
        # 4 timeframes and only depends on `bias`, not on the specific
        # sweep event. The original code called it fresh inside this
        # loop for every sweep, so with dozens/hundreds of sweeps the
        # same expensive multi-timeframe scan was repeated that many
        # times - this (combined with the EQH/EQL explosion fixed in
        # LiquidityDetector) is what caused the multi-minute hang.
        # Cache the result per bias so it's computed at most twice.
        zone_cache: Dict[Bias, List[Dict]] = {}

        for sweep in sweeps:
            signal = self._validate_full_chain(
                sweep,
                data,
                all_liquidity,
                zone_cache
            )

            if signal:
                return signal

        return None

    def _validate_full_chain(
        self,
        sweep: Dict,
        data: Dict[str, pd.DataFrame],
        all_liquidity: List,
        zone_cache: Optional[Dict[Bias, List[Dict]]] = None
    ) -> Optional[LiquiditySARSignal]:
        """
        Validate complete 8-layer confirmation chain

        Args:
            sweep: Liquidity sweep event
            data: Timeframe data
            all_liquidity: All liquidity levels
            zone_cache: Optional dict caching _identify_trade_zones()
                results by bias, since that scan is bias-only and
                identical across every sweep of the same bias

        Returns:
            Signal if all layers pass
        """

        sweep_type = sweep['type']
        bias = Bias.BULLISH if 'bullish' in sweep_type else Bias.BEARISH

        # Layer 1: Liquidity sweep (already confirmed)
        liquidity_type = "grab"  # Assume grab for now (stronger than sweep)

        # Layer 2: Identify trade zone (5m, 15m, 30m, max 1H)
        if zone_cache is not None:
            if bias not in zone_cache:
                zone_cache[bias] = self._identify_trade_zones(data, sweep, bias)
            trade_zones = zone_cache[bias]
        else:
            trade_zones = self._identify_trade_zones(data, sweep, bias)

        if not trade_zones:
            return None

        # Layer 3: Check SAR rejection at fresh level
        sar_levels = self.sar_detector.detect_sar_levels(data['M15'], 'M15')
        fresh_sar = self.sar_detector.get_fresh_levels('M15',
            level_type='support' if bias == Bias.BULLISH else 'resistance'
        )

        sar_rejection = False
        sar_level_price = None

        for sar_level in fresh_sar:
            if self.sar_detector.identify_rejection(data['M15'], sar_level):
                sar_rejection = True
                sar_level_price = sar_level.price
                break

        if not sar_rejection:
            logger.debug("No SAR rejection found")
            return None

        # Layer 4: Check SAR breakout
        sar_breakout = False
        for sar_level in fresh_sar:
            if self.sar_detector.identify_breakout(data['M15'], sar_level):
                sar_breakout = True
                break

        # Layer 5: Check pullback to blue zone (trade zone)
        current_price = data['M15']['Close'].iloc[-1]
        best_zone = trade_zones[0]

        in_blue_zone = (
            best_zone['zone_bottom'] <= current_price <= best_zone['zone_top']
        )

        if not in_blue_zone:
            logger.debug("Not in blue zone")
            return None

        # Layer 6: Check entry signal (MSS preferred, alternatives accepted)
        entry_model = self._identify_entry_model(data['M15'], bias)

        if not entry_model:
            logger.debug("No entry model found")
            return None

        # Layer 7: W/M pattern confirmation
        if bias == Bias.BULLISH:
            patterns = self.pattern_detector.detect_w_patterns(data['M15'], 'M15')
            recent_patterns = [p for p in patterns if p.pattern_type in [PatternType.STRONG_W, PatternType.WEAK_W]]
        else:
            patterns = self.pattern_detector.detect_m_patterns(data['M15'], 'M15')
            recent_patterns = [p for p in patterns if p.pattern_type in [PatternType.STRONG_M, PatternType.WEAK_M]]

        if not recent_patterns:
            logger.debug("No W/M pattern found")
            return None

        best_pattern = recent_patterns[-1]
        pattern_strength_info = self.pattern_detector.calculate_pattern_strength(best_pattern)

        # Layer 8: Fresh level entry (already confirmed with SAR)
        # All layers passed!

        # Calculate confluence score
        factors = ConfluenceFactors()
        factors.liquidity_grab = liquidity_type == "grab"
        factors.fresh_sr_level = True
        factors.strong_w_pattern = best_pattern.pattern_type in [PatternType.STRONG_W, PatternType.STRONG_M]
        factors.multiple_zones_aligned = len(trade_zones) > 1

        # Entry model factors
        if entry_model == "MSS":
            factors.mss_present = True
        elif entry_model == "CISD":
            factors.cisd_present = True
        elif entry_model == "Unicorn":
            factors.unicorn_model = True
        elif entry_model == "Turtle Soup":
            factors.turtle_soup = True
        elif entry_model == "SCOB":
            factors.scob_present = True

        # Multi-TF OB alignment
        if best_zone.get('timeframes') and len(best_zone['timeframes']) >= 3:
            factors.ob_alignment_3tf = True
        elif best_zone.get('timeframes') and len(best_zone['timeframes']) >= 2:
            factors.ob_alignment_2tf = True

        confluence_result = self.confluence_scorer.score_liquidity_sar_method(factors)

        if not confluence_result['passed']:
            logger.debug(f"Confluence failed: {confluence_result['score']}/{confluence_result['min_required']}")
            return None

        # Build signal
        signal = LiquiditySARSignal(
            timestamp=data['M15'].index[-1],
            bias=bias,
            entry_price=sar_level_price,
            entry_timeframe='M15',
            liquidity_swept=[sweep['level'].level_type.value],
            liquidity_type=liquidity_type,
            fresh_sar_level=sar_level_price,
            sar_rejection=True,
            sar_breakout=sar_breakout,
            trade_zone_type=best_zone.get('type', 'OB+FVG+SAR'),
            blue_zone=(best_zone['zone_bottom'], best_zone['zone_top']),
            pattern_type=best_pattern.pattern_type,
            pattern_strength=pattern_strength_info['strength'],
            entry_model=entry_model,
            confluence_score=confluence_result['score'],
            confluence_details=confluence_result['details'],
            can_multi_entry=True  # Fresh level allows multiple entries
        )

        # Calculate SL and TP
        swept_liquidity = sweep['level'].price

        if bias == Bias.BULLISH:
            signal.stop_loss = swept_liquidity - abs(swept_liquidity * 0.002)  # Below swept liquidity

            # Target opposite liquidity
            untaken = self.liquidity_detector.get_untaken_liquidity(all_liquidity, bias='bullish')
            if untaken:
                # Find closest untaken liquidity above
                targets_above = [liq for liq in untaken if liq.price > current_price]
                if targets_above:
                    signal.take_profit = min(targets_above, key=lambda x: x.price).price
                    signal.target_liquidity = signal.take_profit
                else:
                    # Use 3:1 RR
                    signal.take_profit = signal.entry_price + (signal.entry_price - signal.stop_loss) * 3
            else:
                signal.take_profit = signal.entry_price + (signal.entry_price - signal.stop_loss) * 3

        else:  # Bearish
            signal.stop_loss = swept_liquidity + abs(swept_liquidity * 0.002)

            untaken = self.liquidity_detector.get_untaken_liquidity(all_liquidity, bias='bearish')
            if untaken:
                targets_below = [liq for liq in untaken if liq.price < current_price]
                if targets_below:
                    signal.take_profit = max(targets_below, key=lambda x: x.price).price
                    signal.target_liquidity = signal.take_profit
                else:
                    signal.take_profit = signal.entry_price - (signal.stop_loss - signal.entry_price) * 3
            else:
                signal.take_profit = signal.entry_price - (signal.stop_loss - signal.entry_price) * 3

        return signal

    def _identify_trade_zones(
        self,
        data: Dict[str, pd.DataFrame],
        sweep: Dict,
        bias: Bias
    ) -> List[Dict]:
        """
        Identify trade zones (OB + FVG + SAR confluence)

        Args:
            data: Timeframe data
            sweep: Sweep event
            bias: Trade bias

        Returns:
            List of trade zones sorted by strength
        """

        zones = []

        # Check 5m, 15m, 30m, 1H
        for tf in ['M5', 'M15', 'M30', 'H1']:
            if tf not in data:
                continue

            # Detect OBs
            obs = self.ob_detector.detect_order_blocks(data[tf], tf)
            fresh_obs = [ob for ob in obs if ob.fresh and ob.bias == bias]

            # Detect FVGs
            fvgs = self.fvg_detector.detect_fvgs(data[tf], tf)
            fresh_fvgs = [fvg for fvg in fvgs if fvg.fresh and fvg.bias == bias]

            # Detect SAR levels
            sar_levels = self.sar_detector.detect_sar_levels(data[tf], tf)
            fresh_sar = self.sar_detector.get_fresh_levels(tf,
                level_type='support' if bias == Bias.BULLISH else 'resistance'
            )

            # Find confluence zones
            for ob in fresh_obs:
                zone = {
                    'timeframe': tf,
                    'zone_bottom': ob.low,
                    'zone_top': ob.high,
                    'type': 'OB',
                    'timeframes': [tf],
                    'strength': 1
                }

                # Check for FVG overlap
                for fvg in fresh_fvgs:
                    if self._check_overlap((ob.low, ob.high), (fvg.bottom, fvg.top)):
                        zone['type'] = 'OB+FVG'
                        zone['strength'] += 1
                        break

                # Check for SAR overlap
                for sar in fresh_sar:
                    if ob.low <= sar.price <= ob.high:
                        zone['type'] = 'OB+FVG+SAR' if 'FVG' in zone['type'] else 'OB+SAR'
                        zone['strength'] += 2  # SAR adds more weight
                        break

                zones.append(zone)

        # Check for multi-TF alignment
        aligned_zones = self._find_aligned_zones(zones)

        # Sort by strength
        all_zones = zones + aligned_zones
        all_zones.sort(key=lambda x: x['strength'], reverse=True)

        return all_zones

    def _check_overlap(
        self,
        range1: Tuple[float, float],
        range2: Tuple[float, float]
    ) -> bool:
        """Check if two price ranges overlap"""
        return max(range1[0], range2[0]) < min(range1[1], range2[1])

    def _find_aligned_zones(self, zones: List[Dict]) -> List[Dict]:
        """Find zones aligned across multiple timeframes"""
        aligned = []

        for i, zone1 in enumerate(zones):
            for zone2 in zones[i+1:]:
                if self._check_overlap(
                    (zone1['zone_bottom'], zone1['zone_top']),
                    (zone2['zone_bottom'], zone2['zone_top'])
                ):
                    # Create aligned zone
                    aligned_zone = {
                        'timeframe': f"{zone1['timeframe']}+{zone2['timeframe']}",
                        'zone_bottom': max(zone1['zone_bottom'], zone2['zone_bottom']),
                        'zone_top': min(zone1['zone_top'], zone2['zone_top']),
                        'type': 'Multi-TF',
                        'timeframes': [zone1['timeframe'], zone2['timeframe']],
                        'strength': zone1['strength'] + zone2['strength'] + 2  # Bonus for alignment
                    }
                    aligned.append(aligned_zone)

        return aligned

    def _identify_entry_model(
        self,
        df: pd.DataFrame,
        bias: Bias
    ) -> Optional[str]:
        """
        Identify entry model on current timeframe

        MSS preferred, but accepts alternatives:
        - CISD (Candle In Strong Displacement)
        - Unicorn Model
        - Turtle Soup
        - SCOB (Single Candle Order Block)

        Args:
            df: Price dataframe
            bias: Expected bias

        Returns:
            Entry model name if found
        """

        # Check for MSS
        structure_events = self.structure_detector.detect_structure(df, 'M15')
        recent_mss = [e for e in structure_events if e.type == StructureType.MSS and e.bias == bias]

        if recent_mss:
            # Check if recent (last 10 candles)
            last_mss = recent_mss[-1]
            mss_idx = df.index.get_loc(last_mss.timestamp)
            if len(df) - mss_idx <= 10:
                return "MSS"

        # Check for CISD (strong displacement candle)
        recent_candles = df.tail(5)
        avg_range = (recent_candles['High'] - recent_candles['Low']).mean()

        for idx, row in recent_candles.iterrows():
            candle_range = row['High'] - row['Low']
            candle_body = abs(row['Close'] - row['Open'])

            # Strong displacement: 2x avg range, body > 80%
            if candle_range > avg_range * 2 and candle_body > candle_range * 0.8:
                if (bias == Bias.BULLISH and row['Close'] > row['Open']) or \
                   (bias == Bias.BEARISH and row['Close'] < row['Open']):
                    return "CISD"

        # Check for SCOB (single strong candle creating OB)
        for idx, row in recent_candles.iterrows():
            if row['High'] - row['Low'] > avg_range * 1.5:
                return "SCOB"

        # Could implement Unicorn and Turtle Soup patterns here
        # For now, return None if no model found
        return None
