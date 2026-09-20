"""
Liquidity SAR Method (Method 3) - MSNR Edition
Rebuilt around Malaysian SNR (MSNR) confluence instead of the old
generic SAR-rejection / W-M pattern system.

TIMEFRAMES: 4H and 1H are used ONLY to find Key Levels (MSNR levels:
A&V/OCL, QM, and their flipped SBR/RBS states). 15M and 5M are used
ONLY for entry timing (MSS + confluence + Fibo2/POI).

BIAS: this method does not compute its own bias. It uses the shared
bias from bias_scheduler.py - the agreement between Combined Method's
and Percentage Method's current 1H bias, recalculated only at 01:00
and 17:45 New York time and held constant between those checkpoints.
If the two methods disagree, or bias_scheduler returns None, this
method does not trade that checkpoint window.

CONFLUENCE - exactly two valid patterns, both requiring an MSS first:
  Pattern A: MSS -> Key Level -> Fibo2 zone hit -> entry
  Pattern B: MSS -> Key Level -> POI (FVG/OB/iFVG) hit -> entry
"Key Level" = a fresh MSNR level (A&V, OCL, QM, or a freshly-flipped
SBR/RBS) sitting between the MSS break point and the current
retracement, confirming the setup has real structural backing before
either the Fibo2 zone or POI zone is used for the actual entry price.

FIBO2 ZONE: measured from the swing extreme before the MSS's
impulsive move ("0") to the extreme the impulsive move reached ("1").
Two independent tiers:
  - Shallow: entry at 0.145, SL fallback at 0.109
  - Deep:    entry at 0.25,  SL fallback at 0.214
Either tier qualifies as confluence independently.

STOP LOSS: beyond the swing extreme that produced the MSS, UNLESS that
distance exceeds 50 pips, in which case the relevant Fibo2 tier's
outer boundary (0.109 or 0.214) is used instead for a tighter stop.

TAKE PROFIT: opposite-side liquidity, or an MSNR level on 1H/4H if no
liquidity target is found, else a 3:1 reward-to-risk fallback.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from src.core.data_fetcher import DataFetcher
from src.core.structure_detector import StructureDetector, Bias, StructureType
from src.core.order_block_detector import OrderBlockDetector
from src.core.fvg_detector import FVGDetector
from src.core.liquidity_detector import LiquidityDetector
from src.core.msnr_detector import MSNRDetector, MSNRLevel
from src.core.bias_scheduler import get_shared_bias
from src.utils.logger import setup_logger
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)

# XAUUSD pip convention: 1 pip = $0.10. Adjust if your broker/feed uses
# a different convention (e.g., $0.01).
PIP_SIZE = 0.10
MAX_SWING_SL_PIPS = 50

FIBO2_SHALLOW_ENTRY = 0.145
FIBO2_SHALLOW_SL = 0.109
FIBO2_DEEP_ENTRY = 0.25
FIBO2_DEEP_SL = 0.214


@dataclass
class MSNRSignal:
    """Trade signal from Method 3 (MSNR Edition)"""
    timestamp: pd.Timestamp
    method: str = "Liquidity SAR Method"

    entry_price: float = 0.0
    entry_timeframe: str = "M15"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    bias: Bias = Bias.NEUTRAL

    key_level_source: str = ""      # 'A&V', 'OCL', 'QM'
    confluence_pattern: str = ""    # 'MSS+KeyLevel+Fibo2' or 'MSS+KeyLevel+POI'
    poi_type: str = ""              # 'OB', 'FVG', 'iFVG' (Pattern B only)
    fibo2_tier: str = ""            # 'shallow' or 'deep' (Pattern A only)

    # Generic fields the Telegram formatter expects on every method's
    # signal (see telegram_bot.py's _format_trade_alert) - populated
    # in _build_signal() rather than via a numeric scorer, since this
    # method is a fixed 3-layer confluence chain (MSS + Key Level +
    # Fibo2/POI), not a weighted score.
    confluence_score: int = 3
    confluence_details: List[str] = field(default_factory=list)


class LiquiditySARMethod:
    """
    Method 3: MSNR-based confluence system.
    4H/1H for Key Levels, 15M/5M for MSS + entry.
    """

    def __init__(self, data_fetcher: DataFetcher, combined_method=None, percentage_method=None):
        self.data_fetcher = data_fetcher
        self.structure_detector = StructureDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg_detector = FVGDetector()
        self.liquidity_detector = LiquidityDetector()
        self.msnr_detector = MSNRDetector()

        # Needed only for get_current_bias() - see bias_scheduler.py.
        # Passed in so this method doesn't duplicate their analysis.
        if combined_method is None:
            from src.methods.combined_method import CombinedMethod
            combined_method = CombinedMethod(data_fetcher)
        if percentage_method is None:
            from src.methods.percentage_method import PercentageMethod
            percentage_method = PercentageMethod(data_fetcher)
        self.combined_method = combined_method
        self.percentage_method = percentage_method

    def analyze(self) -> Optional[MSNRSignal]:
        logger.info("Running Liquidity SAR Method (MSNR) analysis")

        timeframes = ['H4', 'H1', 'M15', 'M5']
        data = self.data_fetcher.fetch_multiple_timeframes(timeframes)

        if not all(tf in data for tf in ['H1', 'M15']):
            logger.warning("Missing required H1/M15 data")
            return None
        if 'H4' not in data:
            logger.info("H4 data unavailable - continuing with H1-only Key Levels")
        if 'M5' not in data:
            logger.info("M5 data unavailable - continuing with M15-only entry")

        # Shared bias (no self-computed bias) - held constant between
        # 01:00/17:45 NY checkpoints, see bias_scheduler.py
        bias = get_shared_bias(self.combined_method, self.percentage_method, data)
        if bias is None:
            logger.debug("No agreed shared bias (Combined/Percentage disagree or unavailable) - no trade")
            return None

        # Key Levels from 4H + H1
        key_levels = self._get_key_levels(data, bias)
        if not key_levels:
            logger.debug(f"No fresh Key Levels found on H4/H1 for bias {bias.value}")
            return None

        # MSS on the entry timeframes (15M preferred, 5M fallback)
        entry_tf = 'M15'
        entry_df = data['M15']
        mss = self._find_recent_mss(entry_df, bias, entry_tf, max_age_bars=15)

        if mss is None and 'M5' in data:
            entry_tf = 'M5'
            entry_df = data['M5']
            mss = self._find_recent_mss(entry_df, bias, entry_tf, max_age_bars=15)

        if mss is None:
            logger.debug("No recent MSS matching shared bias on M15/M5 - no entry")
            return None

        # A Key Level must sit in the retracement zone between the MSS
        # break point and current price - this is the structural
        # backing both confluence patterns require before Fibo2/POI.
        current_price = entry_df['Close'].iloc[-1]
        relevant_key_level = self._find_relevant_key_level(key_levels, mss, current_price, bias)

        if relevant_key_level is None:
            logger.debug("No Key Level found between MSS break point and current price")
            return None

        # Pattern A: Key Level + Fibo2 zone
        fibo2 = self._compute_fibo2_zone(entry_df, mss, bias)
        fibo2_hit = self._check_fibo2_hit(current_price, fibo2, bias)

        if fibo2_hit:
            return self._build_signal(
                bias=bias, entry_tf=entry_tf, mss=mss, key_level=relevant_key_level,
                pattern='MSS+KeyLevel+Fibo2', fibo2=fibo2, fibo2_tier=fibo2_hit,
                current_price=current_price, data=data
            )

        # Pattern B: Key Level + POI (OB/FVG/iFVG)
        poi = self._find_poi(entry_df, entry_tf, bias, current_price)
        if poi:
            return self._build_signal(
                bias=bias, entry_tf=entry_tf, mss=mss, key_level=relevant_key_level,
                pattern='MSS+KeyLevel+POI', poi=poi, fibo2=fibo2,
                current_price=current_price, data=data
            )

        logger.debug("Key Level found, but neither Fibo2 zone nor POI confluence confirmed - no entry")
        return None

    # ------------------------------------------------------------------
    # Key Levels (4H/1H)
    # ------------------------------------------------------------------

    def _get_key_levels(self, data: Dict[str, pd.DataFrame], bias: Bias) -> List[MSNRLevel]:
        """Fresh A&V/OCL/QM levels (incl. flipped SBR/RBS) from 4H and 1H, matching bias direction."""

        level_type = 'support' if bias == Bias.BULLISH else 'resistance'
        levels = []

        for tf in ('H4', 'H1'):
            if tf not in data:
                continue
            self.msnr_detector.detect_av_levels(data[tf], tf)
            self.msnr_detector.detect_qm_levels(data[tf], tf)
            levels.extend(self.msnr_detector.get_fresh_levels(tf, level_type=level_type))

        return levels

    def _find_relevant_key_level(
        self,
        key_levels: List[MSNRLevel],
        mss,
        current_price: float,
        bias: Bias
    ) -> Optional[MSNRLevel]:
        """A Key Level sitting between the MSS break level and current price (the retracement zone)."""

        mss_level = mss.broken_level

        for level in key_levels:
            if bias == Bias.BULLISH:
                if mss_level <= level.price <= current_price:
                    return level
            else:
                if current_price <= level.price <= mss_level:
                    return level

        return None

    # ------------------------------------------------------------------
    # MSS (entry timeframe)
    # ------------------------------------------------------------------

    def _find_recent_mss(self, df: pd.DataFrame, bias: Bias, timeframe: str, max_age_bars: int):
        events = self.structure_detector.detect_structure(df, timeframe)
        matching = [e for e in events if e.type == StructureType.MSS and e.bias == bias]

        if not matching:
            return None

        last_mss = matching[-1]
        mss_idx = df.index.get_loc(last_mss.timestamp)

        if len(df) - mss_idx > max_age_bars:
            return None

        return last_mss

    # ------------------------------------------------------------------
    # Fibo2 zone
    # ------------------------------------------------------------------

    def _compute_fibo2_zone(self, df: pd.DataFrame, mss, bias: Bias, lookback: int = 50) -> Dict[str, float]:
        """
        '0' = the swing extreme before the MSS's impulsive move,
        '1' = the extreme that impulsive move reached (the MSS break
        candle's own price extreme). Two independent retracement
        tiers measured back from '1' toward '0'.
        """

        mss_idx = df.index.get_loc(mss.timestamp)
        start = max(0, mss_idx - lookback)
        window = df.iloc[start:mss_idx + 1]

        if bias == Bias.BEARISH:
            zero = window['High'].max()
            one = window['Low'].min()
            rng = zero - one
            return {
                'entry_shallow': zero - FIBO2_SHALLOW_ENTRY * rng,
                'sl_shallow': zero - FIBO2_SHALLOW_SL * rng,
                'entry_deep': zero - FIBO2_DEEP_ENTRY * rng,
                'sl_deep': zero - FIBO2_DEEP_SL * rng,
            }
        else:
            zero = window['Low'].min()
            one = window['High'].max()
            rng = one - zero
            return {
                'entry_shallow': zero + FIBO2_SHALLOW_ENTRY * rng,
                'sl_shallow': zero + FIBO2_SHALLOW_SL * rng,
                'entry_deep': zero + FIBO2_DEEP_ENTRY * rng,
                'sl_deep': zero + FIBO2_DEEP_SL * rng,
            }

    def _check_fibo2_hit(self, current_price: float, fibo2: Dict[str, float], bias: Bias) -> Optional[str]:
        """
        Returns 'shallow', 'deep', or None depending which Fibo2 tier
        current price has reached. entry_shallow (0.145) sits closer to
        the MSS's originating swing point than entry_deep (0.25), so
        reaching shallow requires MORE retracement than reaching deep -
        check the farther threshold (shallow) first so a price that has
        travelled past both isn't masked by the easier-to-reach one.
        """

        if bias == Bias.BEARISH:
            # price retracing UP into the zone
            if current_price >= fibo2['entry_shallow']:
                return 'shallow'
            if current_price >= fibo2['entry_deep']:
                return 'deep'
            return None
        else:
            # price retracing DOWN into the zone
            if current_price <= fibo2['entry_shallow']:
                return 'shallow'
            if current_price <= fibo2['entry_deep']:
                return 'deep'
            return None

    # ------------------------------------------------------------------
    # POI (OB / FVG / iFVG)
    # ------------------------------------------------------------------

    def _find_poi(self, df: pd.DataFrame, timeframe: str, bias: Bias, current_price: float) -> Optional[Dict]:
        """Fresh OB, FVG, or iFVG matching bias, that current price is sitting inside."""

        obs = self.ob_detector.detect_order_blocks(df, timeframe)
        for ob in obs:
            if ob.fresh and ob.bias == bias and ob.low <= current_price <= ob.high:
                return {'type': 'OB', 'bottom': ob.low, 'top': ob.high}

        fvgs = self.fvg_detector.detect_fvgs(df, timeframe)
        for fvg in fvgs:
            if fvg.fresh and fvg.bias == bias and fvg.bottom <= current_price <= fvg.top:
                return {'type': 'FVG', 'bottom': fvg.bottom, 'top': fvg.top}

        # iFVG: a fully-violated FVG's ENTIRE original range flips
        # polarity - the whole zone becomes a POI in the new direction,
        # not just whatever fraction was left unfilled.
        for fvg in fvgs:
            if not fvg.fresh and fvg.filled_pct >= 100 and fvg.bias != bias:
                if fvg.bottom <= current_price <= fvg.top:
                    return {'type': 'iFVG', 'bottom': fvg.bottom, 'top': fvg.top}

        return None

    # ------------------------------------------------------------------
    # Signal construction
    # ------------------------------------------------------------------

    def _build_signal(
        self,
        bias: Bias,
        entry_tf: str,
        mss,
        key_level: MSNRLevel,
        current_price: float,
        data: Dict[str, pd.DataFrame],
        pattern: str,
        fibo2: Dict[str, float],
        fibo2_tier: Optional[str] = None,
        poi: Optional[Dict] = None
    ) -> MSNRSignal:

        swing_extreme = mss.broken_level

        if pattern == 'MSS+KeyLevel+Fibo2':
            entry_price = fibo2[f'entry_{fibo2_tier}']
            fibo2_sl = fibo2[f'sl_{fibo2_tier}']
        else:
            entry_price = poi['top'] if bias == Bias.BEARISH else poi['bottom']
            # Pattern B has no Fibo2 tier hit; use the deep tier's SL
            # boundary as the tightening option under the same 50-pip rule.
            fibo2_sl = fibo2['sl_deep']

        # Stop loss: beyond the swing extreme, unless that's >50 pips
        # away, in which case use the tighter Fibo2 boundary.
        swing_sl_distance_pips = abs(entry_price - swing_extreme) / PIP_SIZE
        stop_loss = swing_extreme if swing_sl_distance_pips <= MAX_SWING_SL_PIPS else fibo2_sl

        # Take profit: opposite-side liquidity, else an MSNR level on
        # 1H/4H, else a 3:1 RR fallback (needs entry+SL, computed here).
        take_profit = self._find_take_profit(data, bias, entry_price, stop_loss)

        signal = MSNRSignal(
            timestamp=mss.timestamp,
            bias=bias,
            entry_price=entry_price,
            entry_timeframe=entry_tf,
            stop_loss=stop_loss,
            take_profit=take_profit,
            key_level_source=key_level.source.value,
            confluence_pattern=pattern,
        )

        if pattern == 'MSS+KeyLevel+Fibo2':
            signal.fibo2_tier = fibo2_tier
            signal.confluence_details = [
                f"MSS confirmed ({bias.value}) at {swing_extreme:.2f}",
                f"Key Level: {key_level.source.value} at {key_level.price:.2f}",
                f"Fibo2 {fibo2_tier} tier hit at {entry_price:.2f}",
            ]
        else:
            signal.poi_type = poi['type']
            signal.confluence_details = [
                f"MSS confirmed ({bias.value}) at {swing_extreme:.2f}",
                f"Key Level: {key_level.source.value} at {key_level.price:.2f}",
                f"POI: {poi['type']} at {entry_price:.2f}",
            ]

        return signal

    def _find_take_profit(
        self,
        data: Dict[str, pd.DataFrame],
        bias: Bias,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """Opposite-side liquidity target, else nearest opposite MSNR level on 1H/4H, else 3:1 RR."""

        all_liquidity = self.liquidity_detector.detect_all_liquidity(data, entry_price)
        untaken = self.liquidity_detector.get_untaken_liquidity(
            all_liquidity, bias='bullish' if bias == Bias.BULLISH else 'bearish'
        )

        if bias == Bias.BULLISH:
            targets = [lv.price for lv in untaken if lv.price > entry_price]
            if targets:
                return min(targets)
        else:
            targets = [lv.price for lv in untaken if lv.price < entry_price]
            if targets:
                return max(targets)

        # Fallback: nearest opposite-direction MSNR level on 1H/4H
        opposite_type = 'resistance' if bias == Bias.BULLISH else 'support'
        opposite_levels = []
        for tf in ('H1', 'H4'):
            opposite_levels.extend(self.msnr_detector.get_fresh_levels(tf, level_type=opposite_type))

        if opposite_levels:
            if bias == Bias.BULLISH:
                candidates = [lv.price for lv in opposite_levels if lv.price > entry_price]
                if candidates:
                    return min(candidates)
            else:
                candidates = [lv.price for lv in opposite_levels if lv.price < entry_price]
                if candidates:
                    return max(candidates)

        # Last resort: 3:1 RR based on the actual entry/SL distance
        risk = abs(entry_price - stop_loss)
        return entry_price + risk * 3 if bias == Bias.BULLISH else entry_price - risk * 3
