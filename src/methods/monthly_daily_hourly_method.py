"""
Monthly-Daily-Hourly Method (Method 2)
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
from src.core.daily_structure import analyze_daily_structure
from src.utils.confluence_scorer import ConfluenceScorer, ConfluenceFactors
from src.utils.params import get_param
from src.utils.logger import setup_logger
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


@dataclass
class MonthlyDailyHourlySignal:
    """Trade signal from Percentage Method"""
    timestamp: pd.Timestamp
    method: str = "Monthly-Daily-Hourly"

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

    # Monthly OB (information only - never blocks a trade, sets no trend or target)
    monthly_ob_low: Optional[float] = None
    monthly_ob_high: Optional[float] = None
    price_at_monthly_ob: bool = False


class MonthlyDailyHourlyMethod:
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

    def get_current_bias(self, data: Dict[str, pd.DataFrame]) -> Optional[Bias]:
        """
        The directional bias Percentage Method is currently working
        from - Daily bias, but only if H1 actually confirms it (same
        gate analyze() uses). Used by bias_scheduler.py to derive
        Method 3's shared 1H bias without duplicating this method's
        Daily/H1 structure logic.

        Returns None if Daily structure isn't valid, or H1 doesn't
        confirm it (no bias to report).
        """
        daily_info = {}
        if 'D1' in data:
            daily_valid, daily_info = self._analyze_daily_structure(data['D1'])
            if not daily_valid:
                daily_info = {}

        h1_valid, h1_info = self._analyze_h1_structure(data['H1'], daily_info)
        if not h1_valid:
            return None

        return h1_info['bias']

    def analyze(self) -> Optional[MonthlyDailyHourlySignal]:
        """
        Run Percentage Method analysis

        Returns:
            Trade signal if found, None otherwise
        """

        logger.info("Running Monthly-Daily-Hourly Method analysis")

        # Fetch required data
        timeframes = ['MN', 'D1', 'H1', 'M5']
        data = self.data_fetcher.fetch_multiple_timeframes(timeframes)

        if 'H1' not in data:
            logger.warning("Missing required H1 data")
            return None

        for tf in ['MN', 'D1', 'M5']:
            if tf not in data:
                logger.info(f"{tf} data unavailable - continuing without it")

        # D1 only gives the HTF bias and never blocks a signal. M5 is the
        # entry timeframe, so without it there is nothing to enter on.
        if 'M5' not in data:
            logger.warning("M5 data unavailable - no entry timeframe, no signal")
            return None

        # Step 1: Monthly OB (information only)
        monthly_ob = self._find_monthly_ob(data.get('MN'), data['H1']['Close'].iloc[-1])

        # Step 2: Daily structure = HTF bias only (never blocks a signal)
        daily_info = {}
        if 'D1' in data:
            daily_valid, daily_info = self._analyze_daily_structure(data['D1'])
            if not daily_valid:
                logger.debug("Daily structure not valid - continuing without HTF bias")
                daily_info = {}
        else:
            logger.debug("No D1 data - continuing without HTF bias")

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
            monthly_ob
        )

        if signal:
            logger.info(f"Percentage Method signal: {signal.bias.value} at {signal.entry_price}")

        return signal

    def _find_monthly_ob(
        self,
        monthly_df: Optional[pd.DataFrame],
        current_price: float
    ) -> Optional[Dict]:
        """
        Monthly only gives a fresh Monthly OB showing how far Daily price
        can go. It never sets the trend or a target and never blocks a
        trade. Uses all available Monthly candles (15 years = 180 wanted).

        Returns the fresh Monthly OB nearest to current price, or None.
        """

        min_candles = 180  # 15 years of Monthly candles
        if monthly_df is None or monthly_df.empty:
            logger.info("Monthly data unavailable - no Monthly OB")
            return None
        if len(monthly_df) < min_candles:
            logger.warning(
                f"Only {len(monthly_df)} Monthly candles (15 years = {min_candles}) - using what is available"
            )

        obs = self.ob_detector.detect_order_blocks(monthly_df, 'MN')
        fresh = [ob for ob in obs if ob.fresh]
        if not fresh:
            logger.debug("No fresh Monthly OB found")
            return None

        def distance(ob):
            if ob.low <= current_price <= ob.high:
                return 0.0
            return min(abs(current_price - ob.low), abs(current_price - ob.high))

        nearest = min(fresh, key=distance)
        inside = nearest.low <= current_price <= nearest.high
        logger.debug(
            f"Nearest fresh Monthly OB: {nearest.low:.2f}-{nearest.high:.2f} "
            f"({nearest.bias.value}), price inside: {inside}"
        )
        return {
            'low': nearest.low,
            'high': nearest.high,
            'bias': nearest.bias,
            'price_inside': inside
        }

    def _analyze_daily_structure(
        self,
        daily_df: pd.DataFrame
    ) -> Tuple[bool, Dict]:
        """
        Daily structure (see daily_structure.py): finds the MSS direction,
        Recent STH and New STH confirmation point. Passes as soon as all
        three exist, whatever the pullback. Marks the main POIs (fresh OBs
        and the FVGs overlapping them) in the leg. They are stored for 1H
        confluence only and have no effect on the result.
        """

        info = {}

        structure = analyze_daily_structure(daily_df)
        if not structure.valid:
            logger.debug("No Daily MSS found - Daily direction not confirmed")
            return False, info

        info['structure'] = structure
        info['bias'] = structure.bias
        info['pullback_pct'] = structure.pullback_pct * 100
        info['fib'] = structure.fib

        # All fresh D1 OBs (only a reversal sign, never required)
        info['all_obs'] = [
            ob for ob in self.ob_detector.detect_order_blocks(daily_df, 'D1') if ob.fresh
        ]

        leg_df = daily_df.loc[structure.recent_sth_time:]
        obs = self.ob_detector.detect_order_blocks(leg_df, 'D1')
        fresh_obs = [ob for ob in obs if ob.fresh and ob.bias == structure.bias]
        fvgs = self.fvg_detector.detect_fvgs(leg_df, 'D1')
        fresh_fvgs = [f for f in fvgs if f.fresh and f.bias == structure.bias]

        info['obs'] = fresh_obs
        info['fvgs'] = [
            c['fvg'] for c in self.fvg_detector.check_fvg_ob_confluence(fresh_fvgs, fresh_obs)
        ]

        return True, info

    def _analyze_h1_structure(
        self,
        h1_df: pd.DataFrame,
        daily_info: Dict
    ) -> Tuple[bool, Dict]:
        """
        H1 structure: same method as Daily (see daily_structure.py) but the
        pullback must reach 0.375. This is the LTF trend inside the Daily
        trend, and it may or may not match the Daily direction. Passes as
        soon as the MSS, Recent STH/STL and confirmation point exist.
        Marks the OBs and the FVGs overlapping them (no Advance OB).
        """

        info = {}

        structure = analyze_daily_structure(h1_df, 'H1', 0.375)
        if not structure.valid:
            logger.debug("No H1 MSS found - H1 direction not confirmed")
            return False, info

        info['structure'] = structure
        info['bias'] = structure.bias
        info['pullback_pct'] = structure.pullback_pct * 100
        info['fib'] = structure.fib

        # Broad trading range: Recent STH/STL to the confirmation point
        info['low'] = min(structure.recent_sth, structure.confirmation)
        info['high'] = max(structure.recent_sth, structure.confirmation)

        # All fresh H1 OBs from the last 1000 candles (M5+H1 alignment and TP)
        info['all_obs'] = [
            ob for ob in self.ob_detector.detect_order_blocks(h1_df.tail(1000), 'H1') if ob.fresh
        ]

        leg_df = h1_df.loc[structure.recent_sth_time:]
        obs = self.ob_detector.detect_order_blocks(leg_df, 'H1')
        fresh_obs = [ob for ob in obs if ob.fresh and ob.bias == structure.bias]
        fvgs = self.fvg_detector.detect_fvgs(leg_df, 'H1')
        fresh_fvgs = [f for f in fvgs if f.fresh and f.bias == structure.bias]

        info['obs'] = fresh_obs
        info['fvgs'] = [
            c['fvg'] for c in self.fvg_detector.check_fvg_ob_confluence(fresh_fvgs, fresh_obs)
        ]

        return True, info

    def _find_m5_entry(
        self,
        m5_df: pd.DataFrame,
        daily_info: Dict,
        h1_info: Dict,
        monthly_ob: Optional[Dict]
    ) -> Optional[MonthlyDailyHourlySignal]:
        """
        M5 entry. Same structure method as Daily/H1 (0.375 pullback).
        The trade follows the M5 trend, which may match H1 or be counter-1H.
        Entry: the closest fresh M5 OB beyond the M5 0.375 level (above it
        for a sell, below it for a buy), inside both the M5 short range and
        the H1 broad range. An FVG near the OB is optional (+1 score).
        Entry = the OB edge price touches first. SL = M5 Recent STH/STL.
        TP is unchanged until the TP corrections.
        """

        m5 = analyze_daily_structure(m5_df, 'M5', 0.375)
        if not m5.valid:
            logger.debug("No M5 MSS found - M5 direction not confirmed")
            return None

        bias = m5.bias
        bull = bias == Bias.BULLISH
        counter_h1 = bias != h1_info['bias']
        level_375 = m5.fib['0.375']
        m5_low = min(m5.recent_sth, m5.confirmation)
        m5_high = max(m5.recent_sth, m5.confirmation)
        price = m5_df['Close'].iloc[-1]

        # Fresh M5 OBs in the trade direction, beyond the 0.375 level and
        # inside both the M5 short range and the H1 broad range
        range_low = max(m5_low, h1_info['low'])
        range_high = min(m5_high, h1_info['high'])
        candidates = []
        for ob in self.ob_detector.detect_order_blocks(m5_df, 'M5'):
            if not ob.fresh or ob.bias != bias:
                continue
            if ob.timestamp < m5.recent_sth_time:  # only OBs formed inside the current leg
                continue
            if bull and ob.high > level_375:
                continue
            if not bull and ob.low < level_375:
                continue
            if ob.low < range_low or ob.high > range_high:
                continue
            candidates.append(ob)

        if not candidates:
            logger.debug(
                f"No fresh M5 {bias.value} OB beyond the 0.375 level ({level_375:.2f}) "
                f"inside M5 and H1 ranges - no signal"
            )
            return None

        def distance(ob):
            if ob.low <= price <= ob.high:
                return 0.0
            return min(abs(price - ob.low), abs(price - ob.high))

        # An M5 OB overlapping a fresh H1 OB (M5+H1) beats a plain M5 OB.
        # If there is no M5+H1 OB, use the closest plain M5 OB.
        h1_same = [ob for ob in h1_info.get('all_obs', []) if ob.bias == bias]
        aligned = [
            ob for ob in candidates
            if any(h.low <= ob.high and h.high >= ob.low for h in h1_same)
        ]
        entry_ob_label = "M5+H1" if aligned else "M5 only"
        best = min(aligned if aligned else candidates, key=distance)

        # Entry = the edge price touches first; SL = M5 Recent STH/STL
        entry = best.high if bull else best.low
        stop_loss = m5.recent_sth
        if (bull and stop_loss >= entry) or (not bull and stop_loss <= entry):
            logger.debug("M5 Recent STH/STL is not beyond the entry - no signal")
            return None

        # Optional FVG near the OB (above it for a buy, below it for a sell)
        ob_height = best.high - best.low
        fvgs = self.fvg_detector.detect_fvgs(m5_df, 'M5')
        near_fvg = []
        for f in fvgs:
            if not f.fresh or f.bias != bias:
                continue
            if bull and best.low <= f.bottom <= best.high + ob_height:
                near_fvg.append(f)
            elif not bull and best.low - ob_height <= f.top <= best.high:
                near_fvg.append(f)

        # Confluence
        factors = ConfluenceFactors()
        factors.mss_present = True
        factors.ob_fresh = True
        factors.premium_discount_alignment = True  # OB is beyond the M5 0.375 level
        factors.htf_structure_aligned = True
        factors.fvg_present = bool(near_fvg)

        confluence_result = self.confluence_scorer.score_percentage_method(factors)
        if not confluence_result['passed']:
            logger.debug(f"Confluence failed: {confluence_result['score']}/{confluence_result['min_required']}")
            return None

        details = list(confluence_result['details'])
        details.append("Counter-1H trade" if counter_h1 else "With the 1H trend")

        signal = MonthlyDailyHourlySignal(
            timestamp=m5.recent_sth_time,  # one signal per leg
            bias=bias,
            entry_price=entry,
            entry_timeframe='M5',
            stop_loss=stop_loss,
            daily_pullback_pct=daily_info.get('pullback_pct', 0.0),
            h1_pullback_pct=h1_info['pullback_pct'],
            m5_pullback_pct=m5.pullback_pct * 100,
            in_premium_discount=True,
            monthly_ob_low=monthly_ob['low'] if monthly_ob else None,
            monthly_ob_high=monthly_ob['high'] if monthly_ob else None,
            price_at_monthly_ob=monthly_ob['price_inside'] if monthly_ob else False,
            confluence_score=confluence_result['score'],
            confluence_details=details
        )

        # TP: closest fresh H1 OB beyond the entry (supply above for a buy,
        # demand below for a sell), at its near edge. If there is none, the
        # M5 confirmation point.
        h1_targets = [
            ob for ob in h1_info.get('all_obs', [])
            if (bull and ob.bias == Bias.BEARISH and ob.low > entry)
            or (not bull and ob.bias == Bias.BULLISH and ob.high < entry)
        ]
        h1_ob_tp = None
        if h1_targets:
            h1_ob_tp = min(ob.low for ob in h1_targets) if bull else max(ob.high for ob in h1_targets)

        if counter_h1:
            # Counter-1H: closest fresh H1 OB, else the M5 confirmation point
            m5_conf_ok = m5.confirmation > entry if bull else m5.confirmation < entry
            if h1_ob_tp is not None:
                take_profit, tp_source = h1_ob_tp, "closest H1 OB"
            elif m5_conf_ok:
                take_profit, tp_source = m5.confirmation, "M5 confirmation point"
            else:
                take_profit, tp_source = None, ""
        else:
            # With the 1H trend: closest of H1 OB, M5 confirmation point, H1 confirmation point
            options = [
                (h1_ob_tp, "closest H1 OB"),
                (m5.confirmation, "M5 confirmation point"),
                (h1_info['structure'].confirmation, "H1 confirmation point"),
            ]
            beyond = [
                (p, s) for p, s in options
                if p is not None and (p > entry if bull else p < entry)
            ]
            if beyond:
                take_profit, tp_source = min(beyond, key=lambda x: abs(x[0] - entry))
            else:
                take_profit, tp_source = None, ""

        # No TP found by these rules: standard 1:3 risk to reward
        if take_profit is None:
            risk = abs(entry - stop_loss)
            take_profit = entry + risk * 3.0 if bull else entry - risk * 3.0
            tp_source = "1:3 risk to reward"

        signal.take_profit = take_profit
        signal.zone_type = "discount" if bull else "premium"

        # D1 / D1+H1 OBs are only a reversal sign, never required
        d1_same = [ob for ob in daily_info.get('all_obs', []) if ob.bias == bias]
        at_d1 = any(d.low <= best.high and d.high >= best.low for d in d1_same)
        at_d1_h1 = any(
            max(d.low, h.low) <= min(d.high, h.high)
            and max(d.low, h.low) <= best.high
            and min(d.high, h.high) >= best.low
            for d in d1_same for h in h1_same
        )

        tags = [
            "Entry 1 (MSS leg)" if m5.recent_sth_time <= m5.mss_time else "Re-entry (new leg)",
            "Counter-1H trade" if counter_h1 else "With the 1H trend",
            f"Entry OB: {entry_ob_label}",
            f"TP: {tp_source}",
        ]
        if at_d1_h1:
            tags.append("Entry at a D1+H1 OB zone (reversal sign)")
        elif at_d1:
            tags.append("Entry at a D1 OB (reversal sign)")
        signal.confluence_details = tags + [d for d in signal.confluence_details if d not in tags]

        return signal
