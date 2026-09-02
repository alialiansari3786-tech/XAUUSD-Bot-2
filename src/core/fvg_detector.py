"""
FVG Detector Module
Detects Fair Value Gaps, Volume Imbalances, and Overlap Gaps
"""

import pandas as pd
import numpy as np
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import setup_logger
from src.core.structure_detector import Bias
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


class GapType(Enum):
    """Types of gaps"""
    FVG = "FVG"  # Fair Value Gap
    VI = "VI"    # Volume Imbalance
    OG = "OG"    # Overlap Gap


@dataclass
class FairValueGap:
    """Fair Value Gap representation"""
    timestamp: pd.Timestamp
    top: float
    bottom: float
    bias: Bias
    gap_type: GapType
    timeframe: str
    fresh: bool = True

    # Gap metrics
    size: Optional[float] = None
    size_pct: Optional[float] = None

    # Tracking
    filled_pct: float = 0.0
    last_test_time: Optional[pd.Timestamp] = None


class FVGDetector:
    """Detects Fair Value Gaps and related imbalances"""

    def __init__(self):
        """Initialize FVGDetector"""
        self.tracked_fvgs: dict = {}

    def detect_fvgs(
        self,
        df: pd.DataFrame,
        timeframe: str,
        auto_threshold: bool = True,
        min_gap_pct: float = 0.05
    ) -> List[FairValueGap]:
        """
        Detect Fair Value Gaps

        FVG = 3-candle pattern where candle 2 creates a gap
        - Bullish FVG: Candle 1 high < Candle 3 low
        - Bearish FVG: Candle 1 low > Candle 3 high

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe
            auto_threshold: Use auto-threshold based on bar delta percentage
            min_gap_pct: Minimum gap size as percentage of price

        Returns:
            List of detected FVGs
        """

        fvgs = []

        # Calculate bar delta percentage for auto-threshold (Smart Money Concepts logic)
        if auto_threshold:
            df = df.copy()
            df['bar_delta_pct'] = abs(df['Close'] - df['Open']) / df['Open'] * 100
            threshold = df['bar_delta_pct'].rolling(20).mean()
        else:
            threshold = pd.Series([min_gap_pct * 100] * len(df), index=df.index)

        for i in range(2, len(df)):
            candle_1 = df.iloc[i - 2]
            candle_2 = df.iloc[i - 1]
            candle_3 = df.iloc[i]

            current_threshold = threshold.iloc[i - 1] if auto_threshold else min_gap_pct * 100

            # Bullish FVG: Gap between candle 1 high and candle 3 low
            if candle_1['High'] < candle_3['Low']:
                gap_size = candle_3['Low'] - candle_1['High']
                gap_pct = (gap_size / candle_1['High']) * 100

                # Check if gap meets threshold
                if gap_pct >= current_threshold * 0.01:  # Convert to percentage
                    fvg = FairValueGap(
                        timestamp=df.index[i - 1],
                        top=candle_3['Low'],
                        bottom=candle_1['High'],
                        bias=Bias.BULLISH,
                        gap_type=GapType.FVG,
                        timeframe=timeframe,
                        fresh=True,
                        size=gap_size,
                        size_pct=gap_pct
                    )
                    fvgs.append(fvg)

            # Bearish FVG: Gap between candle 1 low and candle 3 high
            elif candle_1['Low'] > candle_3['High']:
                gap_size = candle_1['Low'] - candle_3['High']
                gap_pct = (gap_size / candle_1['Low']) * 100

                if gap_pct >= current_threshold * 0.01:
                    fvg = FairValueGap(
                        timestamp=df.index[i - 1],
                        top=candle_1['Low'],
                        bottom=candle_3['High'],
                        bias=Bias.BEARISH,
                        gap_type=GapType.FVG,
                        timeframe=timeframe,
                        fresh=True,
                        size=gap_size,
                        size_pct=gap_pct
                    )
                    fvgs.append(fvg)

        # Update freshness
        fvgs = self._update_freshness(fvgs, df)

        self.tracked_fvgs[timeframe] = fvgs

        logger.debug(f"Detected {len(fvgs)} FVGs on {timeframe}")
        return fvgs

    def detect_volume_imbalances(
        self,
        df: pd.DataFrame,
        timeframe: str,
        volume_threshold: float = 1.5
    ) -> List[FairValueGap]:
        """
        Detect Volume Imbalances (VI)

        VI = Gap with significant volume spike on middle candle

        Args:
            df: OHLCV DataFrame with Volume
            timeframe: Current timeframe
            volume_threshold: Minimum volume multiplier vs average

        Returns:
            List of volume imbalances
        """

        vis = []

        # Calculate average volume
        df = df.copy()
        df['avg_volume'] = df['Volume'].rolling(20).mean()

        for i in range(2, len(df)):
            candle_1 = df.iloc[i - 2]
            candle_2 = df.iloc[i - 1]
            candle_3 = df.iloc[i]

            # Check for volume spike on candle 2
            if candle_2['Volume'] > candle_2['avg_volume'] * volume_threshold:
                # Check for gap
                if candle_1['High'] < candle_3['Low']:
                    # Bullish VI
                    vi = FairValueGap(
                        timestamp=df.index[i - 1],
                        top=candle_3['Low'],
                        bottom=candle_1['High'],
                        bias=Bias.BULLISH,
                        gap_type=GapType.VI,
                        timeframe=timeframe,
                        fresh=True,
                        size=candle_3['Low'] - candle_1['High']
                    )
                    vis.append(vi)

                elif candle_1['Low'] > candle_3['High']:
                    # Bearish VI
                    vi = FairValueGap(
                        timestamp=df.index[i - 1],
                        top=candle_1['Low'],
                        bottom=candle_3['High'],
                        bias=Bias.BEARISH,
                        gap_type=GapType.VI,
                        timeframe=timeframe,
                        fresh=True,
                        size=candle_1['Low'] - candle_3['High']
                    )
                    vis.append(vi)

        vis = self._update_freshness(vis, df)

        self.tracked_fvgs[f"{timeframe}_VI"] = vis

        logger.debug(f"Detected {len(vis)} Volume Imbalances on {timeframe}")
        return vis

    def detect_overlap_gaps(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> List[FairValueGap]:
        """
        Detect Overlap Gaps (OG)

        OG = Partial gap with some overlap between candle 1 and 3

        Args:
            df: OHLCV DataFrame
            timeframe: Current timeframe

        Returns:
            List of overlap gaps
        """

        ogs = []

        for i in range(2, len(df)):
            candle_1 = df.iloc[i - 2]
            candle_3 = df.iloc[i]

            # Bullish OG: Partial gap up with some overlap
            if candle_3['Low'] < candle_1['High'] < candle_3['High']:
                og = FairValueGap(
                    timestamp=df.index[i - 1],
                    top=candle_3['High'],
                    bottom=candle_1['High'],
                    bias=Bias.BULLISH,
                    gap_type=GapType.OG,
                    timeframe=timeframe,
                    fresh=True,
                    size=candle_3['High'] - candle_1['High']
                )
                ogs.append(og)

            # Bearish OG: Partial gap down with overlap
            elif candle_3['Low'] < candle_1['Low'] < candle_3['High']:
                og = FairValueGap(
                    timestamp=df.index[i - 1],
                    top=candle_1['Low'],
                    bottom=candle_3['Low'],
                    bias=Bias.BEARISH,
                    gap_type=GapType.OG,
                    timeframe=timeframe,
                    fresh=True,
                    size=candle_1['Low'] - candle_3['Low']
                )
                ogs.append(og)

        ogs = self._update_freshness(ogs, df)

        self.tracked_fvgs[f"{timeframe}_OG"] = ogs

        logger.debug(f"Detected {len(ogs)} Overlap Gaps on {timeframe}")
        return ogs

    def _update_freshness(
        self,
        fvgs: List[FairValueGap],
        df: pd.DataFrame
    ) -> List[FairValueGap]:
        """
        Update freshness and fill percentage of FVGs

        FVG becomes unfresh when:
        - Fully filled (price closes through entire gap)
        - Partially filled gaps can still be fresh

        Args:
            fvgs: List of FVGs
            df: Price dataframe

        Returns:
            Updated FVGs
        """

        for fvg in fvgs:
            if not fvg.fresh:
                continue

            # Get price action after FVG formation
            future_data = df[df.index > fvg.timestamp]

            if future_data.empty:
                continue

            gap_size = fvg.top - fvg.bottom

            for idx, row in future_data.iterrows():
                # Bullish FVG: Check how much has been filled from above
                if fvg.bias == Bias.BULLISH:
                    if row['Low'] <= fvg.top:
                        fvg.last_test_time = idx

                        # Calculate fill percentage
                        fill_level = min(row['Low'], fvg.top)
                        filled_amount = fvg.top - max(fill_level, fvg.bottom)
                        fvg.filled_pct = (filled_amount / gap_size) * 100

                        # Fully filled if closed below bottom
                        if row['Close'] <= fvg.bottom:
                            fvg.fresh = False
                            fvg.filled_pct = 100.0
                            break

                # Bearish FVG: Check fill from below
                elif fvg.bias == Bias.BEARISH:
                    if row['High'] >= fvg.bottom:
                        fvg.last_test_time = idx

                        fill_level = max(row['High'], fvg.bottom)
                        filled_amount = min(fill_level, fvg.top) - fvg.bottom
                        fvg.filled_pct = (filled_amount / gap_size) * 100

                        if row['Close'] >= fvg.top:
                            fvg.fresh = False
                            fvg.filled_pct = 100.0
                            break

        return fvgs

    def get_fresh_fvgs(
        self,
        timeframe: str,
        bias: Optional[Bias] = None,
        gap_type: Optional[GapType] = None,
        max_fill_pct: float = 50.0
    ) -> List[FairValueGap]:
        """
        Get fresh FVGs

        Args:
            timeframe: Timeframe to query
            bias: Optional bias filter
            gap_type: Optional gap type filter
            max_fill_pct: Maximum fill percentage to consider fresh

        Returns:
            List of fresh FVGs
        """

        all_fvgs = []

        # Get all FVG types
        for key in [timeframe, f"{timeframe}_VI", f"{timeframe}_OG"]:
            if key in self.tracked_fvgs:
                all_fvgs.extend(self.tracked_fvgs[key])

        # Filter
        fresh_fvgs = [
            fvg for fvg in all_fvgs
            if fvg.fresh and fvg.filled_pct <= max_fill_pct
        ]

        if bias:
            fresh_fvgs = [fvg for fvg in fresh_fvgs if fvg.bias == bias]

        if gap_type:
            fresh_fvgs = [fvg for fvg in fresh_fvgs if fvg.gap_type == gap_type]

        return fresh_fvgs

    def check_fvg_ob_confluence(
        self,
        fvgs: List[FairValueGap],
        order_blocks: List,
        price_tolerance: float = 0.001
    ) -> List[dict]:
        """
        Check for FVG and OB confluence

        Args:
            fvgs: List of FVGs
            order_blocks: List of Order Blocks
            price_tolerance: Price tolerance as percentage

        Returns:
            List of confluence zones
        """

        confluences = []

        for fvg in fvgs:
            for ob in order_blocks:
                # Check if same bias
                if fvg.bias != ob.bias:
                    continue

                # Check for overlap
                fvg_range = (fvg.bottom, fvg.top)
                ob_range = (ob.low, ob.high)

                overlap_bottom = max(fvg_range[0], ob_range[0])
                overlap_top = min(fvg_range[1], ob_range[1])

                if overlap_top > overlap_bottom:
                    # Confluence found
                    confluences.append({
                        'fvg': fvg,
                        'ob': ob,
                        'zone_bottom': overlap_bottom,
                        'zone_top': overlap_top,
                        'zone_size': overlap_top - overlap_bottom,
                        'bias': fvg.bias,
                        'timeframe': fvg.timeframe
                    })

        logger.debug(f"Found {len(confluences)} FVG-OB confluences")
        return confluences
