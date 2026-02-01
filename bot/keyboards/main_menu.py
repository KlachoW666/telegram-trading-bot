from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from typing import Optional


def get_main_menu(is_demo_mode: bool = False, auto_trading_enabled: bool = False) -> ReplyKeyboardMarkup:
    """
    Улучшенное главное меню бота с динамическими элементами
    
    Args:
        is_demo_mode: Режим демо/реальный
        auto_trading_enabled: Статус авто-торговли
    """
    mode_text = "🧪 ДЕМО" if is_demo_mode else "⚠️ РЕАЛЬНЫЙ"
    auto_status = "🟢 Авто ВКЛ" if auto_trading_enabled else "🔴 Авто ВЫКЛ"
    
    keyboard = [
        [KeyboardButton(text=mode_text), KeyboardButton(text=auto_status)],
        [
            KeyboardButton(text="📊 Торговля"),
            KeyboardButton(text="👤 Профиль")
        ],
        [
            KeyboardButton(text="📈 Сигналы"),
            KeyboardButton(text="📊 Статистика")
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
            KeyboardButton(text="❓ Помощь")
        ]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, persistent=True)


def get_back_button() -> ReplyKeyboardMarkup:
    """Кнопка 'Назад'"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="◀️ Назад")]],
        resize_keyboard=True
    )
