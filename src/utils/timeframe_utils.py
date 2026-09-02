"""
Timeframe Utilities
Helper functions for timeframe conversions and calculations
"""

from typing import Dict, List, Optional
import pandas as pd


# Timeframe hierarchy (minutes)
TIMEFRAME_MINUTES = {
    'M1': 1,
    'M3': 3,
    'M5': 5,
    'M15': 15,
    'M30': 30,
    'H1': 60,
    'H4': 240,
    'D1': 1440,
    'W1': 10080,
    'MN': 43200  # Approximate month
}


def get_higher_timeframe(current_tf: str) -> Optional[str]:
    """
    Get the next higher timeframe

    Args:
        current_tf: Current timeframe (e.g., 'M15')

    Returns:
        Next higher timeframe or None if at highest
    """
    current_minutes = TIMEFRAME_MINUTES.get(current_tf)
    if not current_minutes:
        return None

    higher_tfs = [tf for tf, mins in TIMEFRAME_MINUTES.items() if mins > current_minutes]
    if not higher_tfs:
        return None

    return min(higher_tfs, key=lambda x: TIMEFRAME_MINUTES[x])


def get_lower_timeframe(current_tf: str) -> Optional[str]:
    """
    Get the next lower timeframe

    Args:
        current_tf: Current timeframe (e.g., 'H1')

    Returns:
        Next lower timeframe or None if at lowest
    """
    current_minutes = TIMEFRAME_MINUTES.get(current_tf)
    if not current_minutes:
        return None

    lower_tfs = [tf for tf, mins in TIMEFRAME_MINUTES.items() if mins < current_minutes]
    if not lower_tfs:
        return None

    return max(lower_tfs, key=lambda x: TIMEFRAME_MINUTES[x])


def get_timeframe_ratio(higher_tf: str, lower_tf: str) -> int:
    """
    Calculate ratio between two timeframes

    Args:
        higher_tf: Higher timeframe
        lower_tf: Lower timeframe

    Returns:
        Ratio (higher/lower)
    """
    higher_mins = TIMEFRAME_MINUTES.get(higher_tf, 0)
    lower_mins = TIMEFRAME_MINUTES.get(lower_tf, 0)

    if lower_mins == 0:
        return 0

    return higher_mins // lower_mins


def resample_to_timeframe(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """
    Resample OHLCV dataframe to target timeframe

    Args:
        df: DataFrame with datetime index and OHLCV columns
        target_tf: Target timeframe (e.g., 'H1', 'M15')

    Returns:
        Resampled DataFrame
    """

    # Mapping to pandas resample rule
    resample_rules = {
        'M1': '1min',
        'M3': '3min',
        'M5': '5min',
        'M15': '15min',
        'M30': '30min',
        'H1': '1h',
        'H4': '4h',
        'D1': '1D',
        'W1': '1W',
        'MN': '1M'
    }

    rule = resample_rules.get(target_tf)
    if not rule:
        return df

    resampled = df.resample(rule).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()

    return resampled


def get_lookback_periods(timeframe: str) -> Dict[str, int]:
    """
    Get appropriate lookback periods for structure detection

    Args:
        timeframe: Current timeframe

    Returns:
        Dictionary with swing and internal lookback periods
    """

    lookback_configs = {
        'M1': {'swing': 3, 'internal': 2},
        'M3': {'swing': 3, 'internal': 2},
        'M5': {'swing': 5, 'internal': 3},
        'M15': {'swing': 5, 'internal': 3},
        'M30': {'swing': 5, 'internal': 3},
        'H1': {'swing': 7, 'internal': 4},
        'H4': {'swing': 7, 'internal': 4},
        'D1': {'swing': 10, 'internal': 5},
        'W1': {'swing': 10, 'internal': 5},
        'MN': {'swing': 12, 'internal': 6}
    }

    return lookback_configs.get(timeframe, {'swing': 5, 'internal': 3})


def get_valid_entry_timeframes(method: int, structure_tf: str) -> List[str]:
    """
    Get valid entry timeframes for a given structure timeframe and method

    Args:
        method: Trading method number (1, 2, or 3)
        structure_tf: Structure timeframe where signal was detected

    Returns:
        List of valid entry timeframes
    """

    if method == 1:  # Combined Method
        if structure_tf in ['D1', 'H4', 'H1']:
            return ['M15', 'M5', 'M3']
        elif structure_tf == 'M15':
            return ['M5', 'M3']

    elif method == 2:  # Monthly-Daily-Hourly-5m
        if structure_tf == 'D1':
            return ['M5']
        elif structure_tf == 'H1':
            return ['M5']

    elif method == 3:  # Liquidity + SAR
        if structure_tf in ['H1', 'M30', 'M15']:
            return ['M15', 'M5']

    return ['M15', 'M5']


def is_higher_timeframe(tf1: str, tf2: str) -> bool:
    """
    Check if tf1 is higher timeframe than tf2

    Args:
        tf1: First timeframe
        tf2: Second timeframe

    Returns:
        True if tf1 > tf2
    """
    return TIMEFRAME_MINUTES.get(tf1, 0) > TIMEFRAME_MINUTES.get(tf2, 0)


def format_timeframe_display(tf: str) -> str:
    """
    Format timeframe for display

    Args:
        tf: Timeframe code (e.g., 'M15')

    Returns:
        Formatted string (e.g., '15-Minute')
    """

    display_names = {
        'M1': '1-Minute',
        'M3': '3-Minute',
        'M5': '5-Minute',
        'M15': '15-Minute',
        'M30': '30-Minute',
        'H1': '1-Hour',
        'H4': '4-Hour',
        'D1': 'Daily',
        'W1': 'Weekly',
        'MN': 'Monthly'
    }

    return display_names.get(tf, tf)
