import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Опционально: прокси для Telegram (если требуется)
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY")  # Формат: http://user:pass@host:port или socks5://host:port

# BingX API
BINGX_API_KEY = os.getenv("BINGX_API_KEY")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY")
# Опционально: прокси для BingX API (если требуется обход блокировки)
# Поддерживается один прокси или несколько через запятую (для ротации)
# Формат: BINGX_PROXY=http://proxy1:port,http://proxy2:port
_BINGX_PROXY_RAW = os.getenv("BINGX_PROXY", "")
BINGX_PROXY_LIST = [p.strip() for p in _BINGX_PROXY_RAW.split(',') if p.strip()] if _BINGX_PROXY_RAW else []
BINGX_PROXY = BINGX_PROXY_LIST[0] if BINGX_PROXY_LIST else None

# Опционально: отключить проверку SSL сертификатов (небезопасно, только для тестирования)
BINGX_SSL_VERIFY = os.getenv("BINGX_SSL_VERIFY", "true").lower() == "true"

# Настройки по умолчанию
DEFAULT_RISK_PER_TRADE = 1.5  # % от баланса на одну позицию
DEFAULT_TAKE_PROFIT = 3.0  # % прибыли
DEFAULT_STOP_LOSS = 1.5  # % убытка
DEFAULT_LEVERAGE = 5  # Плечо
MAX_OPEN_POSITIONS = 5  # Максимум открытых позиций

# Торговые пары для скальпинга - только выбранные пользователем
DEFAULT_PAIRS = [
    "ZEC/USDT:USDT",   # Zcash - высокая волатильность
    "WIF/USDT:USDT"    # dogwifhat - мемкоин с высокой активностью
]

# Отдельный список пар, которые считаются ПРОБЛЕМНЫМИ для скальпинга по результатам анализа.
# Эти пары принудительно исключаются из авто-торговли (но могут использоваться вручную при желании).
# ПРИМЕЧАНИЕ: ZEC/USDT:USDT и WIF/USDT:USDT теперь в DEFAULT_PAIRS, поэтому не блокируются
SCALPING_BLOCKED_PAIRS = {
    "DOGE/USDT:USDT",
    "ETH/USDT:USDT",
    "SUI/USDT:USDT",
    "DOT/USDT:USDT",
    "AVAX/USDT:USDT",
    "LTC/USDT:USDT",
    "SKR/USDT:USDT",   # Сильный отрицательный PnL по внутреннему тикеру
    # ZEC/USDT:USDT удалён из блокировки, так как теперь в DEFAULT_PAIRS
}

# Ограничения по времени для скальпинга (по результатам анализа)
# ВРЕМЯ УКАЗАНО В UTC!
# Проблемные часы: 06:00 (WR 0%, сильный минус), 11:00 (WR 0%, отрицательный PnL)
SCALPING_BLOCKED_HOURS = {6, 11}

# Дополнительно: ограничиваем торговлю по дням недели (0 = Понедельник, 6 = Воскресенье)
# Понедельник показал очень слабые результаты по WinRate и PnL.
SCALPING_BLOCKED_WEEKDAYS = {0}

# Таймфреймы
TIMEFRAMES = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d"
}

# Демо-режим
DEMO_BALANCE = 1000  # Начальный баланс в демо-режиме (USDT)
