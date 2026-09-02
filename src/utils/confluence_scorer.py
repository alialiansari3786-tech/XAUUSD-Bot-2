"""
Confluence Scorer
Calculates confluence scores for trade setups across all methods
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class ConfluenceFactors:
    """Container for confluence factors"""
    # Multi-timeframe alignment
    ob_alignment_2tf: bool = False  # OB aligned across 2 TFs
    ob_alignment_3tf: bool = False  # OB aligned across 3 TFs
    ob_alignment_4tf: bool = False  # OB aligned across 4 TFs

    # Structure factors
    mss_present: bool = False
    choch_present: bool = False
    choch_plus_present: bool = False

    # Order Block factors
    volumetric_ob: bool = False
    ob_fresh: bool = False
    ob_untested: bool = False

    # FVG factors
    fvg_present: bool = False
    fvg_fresh: bool = False

    # Liquidity factors
    liquidity_sweep: bool = False
    liquidity_grab: bool = False  # Stronger than sweep
    eqh_eql_present: bool = False

    # S/R factors (Method 3)
    fresh_sr_level: bool = False
    sr_cluster: bool = False  # Multiple S/R levels close together

    # Pattern factors
    strong_w_pattern: bool = False
    weak_w_pattern: bool = False
    strong_m_pattern: bool = False

    # Zone factors
    premium_discount_alignment: bool = False
    multiple_zones_aligned: bool = False

    # Entry model factors
    cisd_present: bool = False
    unicorn_model: bool = False
    turtle_soup: bool = False
    scob_present: bool = False

    # HTF factors
    htf_trend_aligned: bool = False
    htf_structure_aligned: bool = False

    # Additional
    impulse_indicator_aligned: bool = False


class ConfluenceScorer:
    """Calculate confluence scores for trade setups"""

    @staticmethod
    def score_combined_method(factors: ConfluenceFactors) -> Dict[str, Any]:
        """
        Score Combined Method (Method 1) confluence

        Scoring:
        - 4-TF OB alignment: +5 points (Daily+4H+1H+15m)
        - 3-TF OB alignment: +4 points
        - 2-TF OB alignment: +3 points
        - STL/STH structure confirmed: +2 points
        - IDM present: +1 point
        - Fresh OB: +2 points
        - MSS at OB: +2 points
        - FVG at OB: +1 point
        - HTF trend aligned: +2 points
        - Premium/Discount zone: +1 point

        Minimum score: 6 points
        """
        score = 0
        details = []

        # Multi-TF alignment (mutually exclusive - take highest)
        if factors.ob_alignment_4tf:
            score += 5
            details.append("4-TF OB Alignment (+5)")
        elif factors.ob_alignment_3tf:
            score += 4
            details.append("3-TF OB Alignment (+4)")
        elif factors.ob_alignment_2tf:
            score += 3
            details.append("2-TF OB Alignment (+3)")

        # Structure
        if factors.mss_present:
            score += 2
            details.append("MSS Present (+2)")

        if factors.choch_plus_present:
            score += 2
            details.append("CHoCH+ Present (+2)")
        elif factors.choch_present:
            score += 1
            details.append("CHoCH Present (+1)")

        # Order Block quality
        if factors.ob_fresh:
            score += 2
            details.append("Fresh OB (+2)")

        if factors.volumetric_ob:
            score += 1
            details.append("Volumetric OB (+1)")

        # FVG
        if factors.fvg_fresh:
            score += 1
            details.append("Fresh FVG (+1)")

        # HTF alignment
        if factors.htf_trend_aligned:
            score += 2
            details.append("HTF Trend Aligned (+2)")

        # Zone
        if factors.premium_discount_alignment:
            score += 1
            details.append("Premium/Discount Zone (+1)")

        # Impulse
        if factors.impulse_indicator_aligned:
            score += 1
            details.append("Impulse Aligned (+1)")

        return {
            'score': score,
            'min_required': 6,
            'passed': score >= 6,
            'strength': 'Strong' if score >= 10 else 'Medium' if score >= 6 else 'Weak',
            'details': details
        }

    @staticmethod
    def score_percentage_method(factors: ConfluenceFactors) -> Dict[str, Any]:
        """
        Score Monthly-Daily-Hourly-5m Method (Method 2) confluence

        Scoring:
        - Percentage pullback met (25% Daily or 37.5% H1/M5): +3 points
        - Simple MSS: +2 points
        - ICT MSS: +2 points
        - Fresh OB in discount/premium zone: +2 points
        - FVG present: +1 point
        - Monthly target projection aligned: +2 points
        - Premium/Discount zone entry: +2 points
        - CHoCH for reversal: +1 point

        Minimum score: 5 points
        """
        score = 0
        details = []

        # MSS (take best available)
        if factors.mss_present:
            score += 2
            details.append("MSS Present (+2)")

        # Structure
        if factors.choch_present:
            score += 1
            details.append("CHoCH Present (+1)")

        # OB quality
        if factors.ob_fresh:
            score += 2
            details.append("Fresh OB (+2)")

        # FVG
        if factors.fvg_present:
            score += 1
            details.append("FVG Present (+1)")

        # Zone alignment
        if factors.premium_discount_alignment:
            score += 2
            details.append("Premium/Discount Entry (+2)")

        # HTF structure
        if factors.htf_structure_aligned:
            score += 2
            details.append("HTF Structure Aligned (+2)")

        return {
            'score': score,
            'min_required': 5,
            'passed': score >= 5,
            'strength': 'Strong' if score >= 8 else 'Medium' if score >= 5 else 'Weak',
            'details': details
        }

    @staticmethod
    def score_liquidity_sar_method(factors: ConfluenceFactors) -> Dict[str, Any]:
        """
        Score Liquidity + SAR Method (Method 3) confluence

        Scoring:
        - Liquidity Grab MSS: +2 points
        - Fresh S/R level: +2 points
        - Strong W/M pattern: +2 points
        - S/R cluster (multiple levels): +1 point
        - OB+FVG+S/R confluence: +2 points
        - Entry model (CISD/Unicorn/Turtle/SCOB): +1 point each
        - Multi-TF OB alignment (5m+15m+1H): +3 points
        - EQH/EQL present: +1 point

        Minimum score: 7 points
        """
        score = 0
        details = []

        # Liquidity factors
        if factors.liquidity_grab:
            score += 2
            details.append("Liquidity Grab (+2)")
        elif factors.liquidity_sweep:
            score += 1
            details.append("Liquidity Sweep (+1)")

        # Fresh S/R
        if factors.fresh_sr_level:
            score += 2
            details.append("Fresh S/R Level (+2)")

        # S/R cluster
        if factors.sr_cluster:
            score += 1
            details.append("S/R Cluster (+1)")

        # Pattern strength
        if factors.strong_w_pattern or factors.strong_m_pattern:
            score += 2
            details.append("Strong W/M Pattern (+2)")
        elif factors.weak_w_pattern:
            score += 1
            details.append("Weak W Pattern (+1)")

        # Trade zone confluence
        if factors.multiple_zones_aligned:
            score += 2
            details.append("OB+FVG+S/R Confluence (+2)")

        # Entry models
        entry_models = []
        if factors.mss_present:
            entry_models.append("MSS")
            score += 1
        if factors.cisd_present:
            entry_models.append("CISD")
            score += 1
        if factors.unicorn_model:
            entry_models.append("Unicorn")
            score += 1
        if factors.turtle_soup:
            entry_models.append("Turtle Soup")
            score += 1
        if factors.scob_present:
            entry_models.append("SCOB")
            score += 1

        if entry_models:
            details.append(f"Entry Models: {', '.join(entry_models)} (+{len(entry_models)})")

        # Multi-TF alignment
        if factors.ob_alignment_3tf:
            score += 3
            details.append("3-TF OB Alignment (+3)")
        elif factors.ob_alignment_2tf:
            score += 2
            details.append("2-TF OB Alignment (+2)")

        # EQH/EQL
        if factors.eqh_eql_present:
            score += 1
            details.append("EQH/EQL Present (+1)")

        return {
            'score': score,
            'min_required': 7,
            'passed': score >= 7,
            'strength': 'Strong' if score >= 12 else 'Medium' if score >= 7 else 'Weak',
            'details': details
        }

    @classmethod
    def calculate_score(
        cls,
        method: int,
        factors: ConfluenceFactors
    ) -> Dict[str, Any]:
        """
        Calculate confluence score for given method

        Args:
            method: Trading method (1, 2, or 3)
            factors: Confluence factors

        Returns:
            Scoring result with score, threshold, and details
        """

        if method == 1:
            return cls.score_combined_method(factors)
        elif method == 2:
            return cls.score_percentage_method(factors)
        elif method == 3:
            return cls.score_liquidity_sar_method(factors)
        else:
            return {
                'score': 0,
                'min_required': 0,
                'passed': False,
                'strength': 'Invalid',
                'details': ['Invalid method']
            }
