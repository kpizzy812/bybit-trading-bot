"""Генератор графиков для AI сценариев"""
import io
import matplotlib
matplotlib.use('Agg')  # Backend без GUI

import pandas as pd
import mplfinance as mpf
from loguru import logger

from .styles import COLORS, CHART_STYLE


class ChartGenerator:
    """Генератор свечных графиков с уровнями из AI сценариев"""

    def __init__(self):
        mc = mpf.make_marketcolors(
            up=CHART_STYLE['marketcolors']['candle']['up'],
            down=CHART_STYLE['marketcolors']['candle']['down'],
            edge={'up': CHART_STYLE['marketcolors']['edge']['up'],
                  'down': CHART_STYLE['marketcolors']['edge']['down']},
            wick={'up': CHART_STYLE['marketcolors']['wick']['up'],
                  'down': CHART_STYLE['marketcolors']['wick']['down']},
            volume={'up': CHART_STYLE['marketcolors']['volume']['up'],
                    'down': CHART_STYLE['marketcolors']['volume']['down']},
        )
        self.style = mpf.make_mpf_style(
            base_mpl_style=CHART_STYLE['base_mpl_style'],
            marketcolors=mc,
            facecolor=CHART_STYLE['facecolor'],
            gridcolor=CHART_STYLE['gridcolor'],
            gridstyle='--',
        )

    def generate_scenario_chart(
        self,
        klines: list[dict],
        scenario: dict,
        symbol: str,
        timeframe: str,
        current_price: float = 0.0
    ) -> bytes:
        """
        Генерировать PNG график для AI сценария.

        Args:
            klines: Список свечей от Bybit
            scenario: AI сценарий с entry, stop_loss, targets
            symbol: Символ (BTCUSDT)
            timeframe: Таймфрейм (1h, 4h, 1d)
            current_price: Текущая цена

        Returns:
            bytes: PNG изображение
        """
        df = self._klines_to_dataframe(klines)
        if df.empty:
            raise ValueError("No kline data to plot")

        # Извлекаем уровни из сценария
        entry = scenario.get('entry', {})
        entry_min = entry.get('price_min', 0)
        entry_max = entry.get('price_max', 0)

        stop_loss = scenario.get('stop_loss', {})
        sl_price = stop_loss.get('recommended', 0)

        targets = scenario.get('targets', [])
        tp_prices = [t.get('price', 0) for t in targets if t.get('price')]

        # Формируем горизонтальные линии
        hlines_prices = []
        hline_colors = []
        hline_widths = []
        hline_styles = []

        # Stop Loss (красная пунктирная)
        if sl_price > 0:
            hlines_prices.append(sl_price)
            hline_colors.append(COLORS['stop_loss'])
            hline_widths.append(1.5)
            hline_styles.append('--')

        # Take Profit уровни (синие)
        for tp in tp_prices[:3]:
            hlines_prices.append(tp)
            hline_colors.append(COLORS['take_profit'])
            hline_widths.append(1.2)
            hline_styles.append('-.')

        # Текущая цена (оранжевая)
        if current_price > 0:
            hlines_prices.append(current_price)
            hline_colors.append(COLORS['current_price'])
            hline_widths.append(1.0)
            hline_styles.append(':')

        # Генерируем график
        buf = io.BytesIO()
        title = f"{symbol} {timeframe.upper()}"

        kwargs = {
            'type': 'candle',
            'style': self.style,
            'title': title,
            'ylabel': 'Price',
            'figsize': (10, 6),
            'tight_layout': True,
            'savefig': {'fname': buf, 'dpi': 150, 'bbox_inches': 'tight'},
        }

        # Добавляем горизонтальные линии
        if hlines_prices:
            kwargs['hlines'] = dict(
                hlines=hlines_prices,
                colors=hline_colors,
                linewidths=hline_widths,
                linestyle=hline_styles,
            )

        # Entry zone как fill_between
        if entry_min > 0 and entry_max > 0:
            kwargs['fill_between'] = dict(
                y1=entry_min,
                y2=entry_max,
                alpha=COLORS['entry_zone_alpha'],
                color=COLORS['entry_zone'],
            )

        mpf.plot(df, **kwargs)

        buf.seek(0)
        return buf.read()

    def _klines_to_dataframe(self, klines: list[dict]) -> pd.DataFrame:
        """Конвертировать klines в DataFrame для mplfinance"""
        if not klines:
            return pd.DataFrame()

        df = pd.DataFrame(klines)
        df['Date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('Date', inplace=True)

        df = df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume',
        })

        return df[['Open', 'High', 'Low', 'Close', 'Volume']]


# Singleton
_chart_generator: ChartGenerator | None = None


def get_chart_generator() -> ChartGenerator:
    """Получить singleton генератора графиков"""
    global _chart_generator
    if _chart_generator is None:
        _chart_generator = ChartGenerator()
    return _chart_generator
