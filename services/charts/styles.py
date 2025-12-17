"""Стили для графиков AI сценариев"""

# Цвета уровней
COLORS = {
    'entry_zone': '#4CAF50',       # Зелёный для entry zone
    'entry_zone_alpha': 0.2,       # Прозрачность зоны
    'stop_loss': '#F44336',        # Красный для SL
    'take_profit': '#2196F3',      # Синий для TP
    'current_price': '#FF9800',    # Оранжевый для текущей цены
}

# Стиль графика (тёмная тема для Telegram)
CHART_STYLE = {
    'base_mpl_style': 'dark_background',
    'marketcolors': {
        'candle': {'up': '#26A69A', 'down': '#EF5350'},
        'edge': {'up': '#26A69A', 'down': '#EF5350'},
        'wick': {'up': '#26A69A', 'down': '#EF5350'},
        'ohlc': {'up': '#26A69A', 'down': '#EF5350'},
        'volume': {'up': '#26A69A', 'down': '#EF5350'},
    },
    'facecolor': '#1E1E1E',
    'gridcolor': '#333333',
}
