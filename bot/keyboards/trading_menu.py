from typing import List
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_trading_menu(auto_trading_enabled: bool = False, open_positions_count: int = 0) -> ReplyKeyboardMarkup:
    """
    Улучшенное меню торговли с информацией о позициях
    
    Args:
        auto_trading_enabled: Статус авто-торговли
        open_positions_count: Количество открытых позиций
    """
    auto_status = "🟢 Авто ВКЛ" if auto_trading_enabled else "🔴 Авто ВЫКЛ"
    positions_text = f"📋 Позиции ({open_positions_count})" if open_positions_count > 0 else "📋 Позиции"
    
    keyboard = [
        [KeyboardButton(text=auto_status)],
        [
            KeyboardButton(text="✋ Ручная торговля"),
            KeyboardButton(text=positions_text)
        ],
        [
            KeyboardButton(text="📈 Сигналы сейчас"),
            KeyboardButton(text="🔍 SMC-Анализ")
        ],
        [
            KeyboardButton(text="🧪 Сканер рынка"),
            KeyboardButton(text="⚡ Быстрый анализ")
        ],
        [KeyboardButton(text="◀️ Назад")]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, persistent=True)


def get_strategy_profiles_menu(profile_titles: List[str]) -> ReplyKeyboardMarkup:
    """Меню выбора профиля стратегии"""
    rows: List[List[KeyboardButton]] = []
    row: List[KeyboardButton] = []
    for t in profile_titles:
        row.append(KeyboardButton(text=t))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([KeyboardButton(text="◀️ Назад")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_smc_analysis_menu() -> ReplyKeyboardMarkup:
    """Меню SMC-анализа (из tt.txt)"""
    keyboard = [
        [
            KeyboardButton(text="🔎 Проверить IMB/FVG"),
            KeyboardButton(text="📊 Сигналы по ОФ")
        ],
        [
            KeyboardButton(text="💧 Пулы ликвидности"),
            KeyboardButton(text="🌊 Свипы")
        ],
        [KeyboardButton(text="◀️ Назад")]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_manual_trading_menu() -> ReplyKeyboardMarkup:
    """Меню ручной торговли"""
    keyboard = [
        [KeyboardButton(text="BTC/USDT"), KeyboardButton(text="ETH/USDT")],
        [KeyboardButton(text="SOL/USDT"), KeyboardButton(text="Другая пара")],
        [KeyboardButton(text="◀️ Назад")]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_positions_menu() -> ReplyKeyboardMarkup:
    """Меню управления позициями"""
    keyboard = [
        [
            KeyboardButton(text="📊 Список"),
            KeyboardButton(text="❌ Закрыть все")
        ],
        [KeyboardButton(text="◀️ Назад")]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_signal_actions_menu() -> ReplyKeyboardMarkup:
    """Меню действий по сигналу"""
    keyboard = [
        [
            KeyboardButton(text="✅ Открыть"),
            KeyboardButton(text="⏭️ Игнорировать")
        ],
        [KeyboardButton(text="◀️ Назад")]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
