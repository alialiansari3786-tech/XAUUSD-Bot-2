"""
Chart Generator Module
Generates annotated charts with levels, zones, and structure
"""

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import mplfinance as mpf
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

from config.settings import settings
from src.utils.logger import setup_logger


logger = setup_logger(__name__, settings.LOG_LEVEL)


class ChartGenerator:
    """Generates trading charts with annotations"""

    def __init__(self):
        """Initialize ChartGenerator"""
        self.output_dir = settings.CHART_STORAGE_PATH
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set style
        if settings.CHART_STYLE == 'dark':
            plt.style.use('dark_background')

    def generate_signal_chart(
        self,
        df: pd.DataFrame,
        signal: Any,
        filename: Optional[str] = None
    ) -> str:
        """
        Generate chart for trade signal

        Args:
            df: OHLCV DataFrame
            signal: Trade signal object
            filename: Optional output filename

        Returns:
            Path to generated chart
        """

        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"signal_{signal.method.replace(' ', '_')}_{timestamp}.png"

        output_path = self.output_dir / filename

        # Prepare data (last 100 candles)
        plot_df = df.tail(100).copy()

        # Create figure
        fig, axes = plt.subplots(2, 1, figsize=(16, 10),
                                gridspec_kw={'height_ratios': [3, 1]})

        # Plot candlesticks
        self._plot_candlesticks(axes[0], plot_df)

        # Add annotations
        self._add_signal_annotations(axes[0], plot_df, signal)

        # Add volume
        self._plot_volume(axes[1], plot_df)

        # Add title
        bias_color = 'green' if signal.bias.value == 'Bullish' else 'red'
        fig.suptitle(
            f"{signal.method} - {signal.bias.value} Signal\n"
            f"Entry: {signal.entry_price:.2f} | SL: {signal.stop_loss:.2f} | "
            f"TP: {signal.take_profit:.2f} | Confluence: {signal.confluence_score}",
            fontsize=14,
            color=bias_color,
            weight='bold'
        )

        plt.tight_layout()
        plt.savefig(output_path, dpi=settings.CHART_DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"Chart generated: {output_path}")
        return str(output_path)

    def _plot_candlesticks(self, ax, df: pd.DataFrame):
        """Plot candlestick chart"""

        for idx, row in df.iterrows():
            color = 'green' if row['Close'] > row['Open'] else 'red'

            # Candle body
            body_height = abs(row['Close'] - row['Open'])
            body_bottom = min(row['Open'], row['Close'])

            rect = patches.Rectangle(
                (idx, body_bottom),
                0.6,
                body_height,
                linewidth=1,
                edgecolor=color,
                facecolor=color,
                alpha=0.8
            )
            ax.add_patch(rect)

            # Wicks
            ax.plot([idx + 0.3, idx + 0.3], [row['Low'], row['High']],
                   color=color, linewidth=1, alpha=0.6)

        ax.set_xlim(-0.5, len(df) - 0.5)
        ax.set_ylim(df['Low'].min() * 0.999, df['High'].max() * 1.001)
        ax.set_ylabel('Price', fontsize=10)
        ax.grid(True, alpha=0.3)

    def _add_signal_annotations(self, ax, df: pd.DataFrame, signal: Any):
        """Add signal-specific annotations"""

        # Entry level
        ax.axhline(y=signal.entry_price, color='blue', linestyle='--',
                  linewidth=2, label=f'Entry: {signal.entry_price:.2f}', alpha=0.8)

        # Stop Loss
        ax.axhline(y=signal.stop_loss, color='red', linestyle='--',
                  linewidth=2, label=f'SL: {signal.stop_loss:.2f}', alpha=0.8)

        # Take Profit
        ax.axhline(y=signal.take_profit, color='green', linestyle='--',
                  linewidth=2, label=f'TP: {signal.take_profit:.2f}', alpha=0.8)

        # Method-specific annotations
        if signal.method == "Combined Method":
            # Trading range
            if signal.trading_range:
                range_low, range_high = signal.trading_range
                ax.axhspan(range_low, range_high, alpha=0.1, color='blue',
                          label='Trading Range')

        elif signal.method == "Percentage Method":
            # Zone box
            if hasattr(signal, 'blue_zone') and signal.blue_zone:
                zone_low, zone_high = signal.blue_zone
                ax.axhspan(zone_low, zone_high, alpha=0.15, color='cyan',
                          label=f'{signal.zone_type.title()} Zone')

        elif signal.method == "Liquidity SAR Method":
            # Blue zone (trade zone)
            if signal.blue_zone:
                zone_low, zone_high = signal.blue_zone
                ax.axhspan(zone_low, zone_high, alpha=0.2, color='blue',
                          label='Blue Zone (Trade Zone)')

            # Fresh SAR level
            if signal.fresh_sar_level:
                ax.axhline(y=signal.fresh_sar_level, color='yellow',
                          linestyle=':', linewidth=1.5,
                          label=f'Fresh S/R: {signal.fresh_sar_level:.2f}')

        ax.legend(loc='upper left', fontsize=8)

    def _plot_volume(self, ax, df: pd.DataFrame):
        """Plot volume bars"""

        colors = ['green' if row['Close'] > row['Open'] else 'red'
                 for _, row in df.iterrows()]

        ax.bar(range(len(df)), df['Volume'], color=colors, alpha=0.6)
        ax.set_ylabel('Volume', fontsize=10)
        ax.set_xlabel('Time', fontsize=10)
        ax.grid(True, alpha=0.3)

    def generate_multi_timeframe_chart(
        self,
        data_dict: Dict[str, pd.DataFrame],
        title: str = "Multi-Timeframe Analysis"
    ) -> str:
        """
        Generate multi-timeframe overview chart

        Args:
            data_dict: Dictionary mapping timeframe to DataFrame
            title: Chart title

        Returns:
            Path to generated chart
        """

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"multi_tf_{timestamp}.png"
        output_path = self.output_dir / filename

        # Create subplots for each timeframe
        timeframes = list(data_dict.keys())[:4]  # Max 4 timeframes
        fig, axes = plt.subplots(len(timeframes), 1, figsize=(16, 4 * len(timeframes)))

        if len(timeframes) == 1:
            axes = [axes]

        for idx, tf in enumerate(timeframes):
            df = data_dict[tf].tail(50)
            self._plot_candlesticks(axes[idx], df)
            axes[idx].set_title(f"{tf} Timeframe", fontsize=12)

        fig.suptitle(title, fontsize=14, weight='bold')
        plt.tight_layout()
        plt.savefig(output_path, dpi=settings.CHART_DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"Multi-TF chart generated: {output_path}")
        return str(output_path)

    def generate_structure_chart(
        self,
        df: pd.DataFrame,
        structure_events: List,
        timeframe: str = "M15"
    ) -> str:
        """
        Generate chart showing market structure

        Args:
            df: OHLCV DataFrame
            structure_events: List of structure events
            timeframe: Timeframe name

        Returns:
            Path to generated chart
        """

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"structure_{timeframe}_{timestamp}.png"
        output_path = self.output_dir / filename

        fig, ax = plt.subplots(figsize=(16, 8))

        plot_df = df.tail(100)
        self._plot_candlesticks(ax, plot_df)

        # Mark structure events
        for event in structure_events:
            if event.timestamp in plot_df.index:
                idx = plot_df.index.get_loc(event.timestamp)

                if event.bias.value == "Bullish":
                    marker_color = 'green'
                    marker = '^'
                else:
                    marker_color = 'red'
                    marker = 'v'

                ax.scatter(idx, event.price, color=marker_color, marker=marker,
                          s=200, zorder=5, label=event.type.value)

        ax.set_title(f"Market Structure - {timeframe}", fontsize=14, weight='bold')
        ax.legend()

        plt.tight_layout()
        plt.savefig(output_path, dpi=settings.CHART_DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"Structure chart generated: {output_path}")
        return str(output_path)
