from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_settings_menu(is_demo_mode: bool = False) -> ReplyKeyboardMarkup:
    """Меню настроек"""
    demo_status = "🟢 Демо" if is_demo_mode else "⚪ Демо"
    real_status = "🟢 Реал" if not is_demo_mode else "⚪ Реал"
    
    keyboard = [
        [
            KeyboardButton(text="🔑 API"),
            KeyboardButton(text=demo_status)
        ],
        [
            KeyboardButton(text=real_status),
            KeyboardButton(text="⚖️ Риск")
        ],
        [
            KeyboardButton(text="📊 Пары"),
            KeyboardButton(text="🔔 Уведомления")
        ],
        [KeyboardButton(text="◀️ Назад")]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_api_settings_menu() -> ReplyKeyboardMarkup:
    """Меню настроек API"""
    keyboard = [
        [
            KeyboardButton(text="➕ Подключить"),
            KeyboardButton(text="✏️ Изменить")
        ],
        [
            KeyboardButton(text="✅ Проверить"),
            KeyboardButton(text="◀️ Назад")
        ]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_risk_settings_menu() -> ReplyKeyboardMarkup:
    """Меню риск-менеджмента"""
    keyboard = [
        [
            KeyboardButton(text="📊 Макс. %"),
            KeyboardButton(text="🎯 Take-Profit")
        ],
        [
            KeyboardButton(text="🛑 Stop-Loss"),
            KeyboardButton(text="📈 Trailing")
        ],
        [
            KeyboardButton(text="🔢 Макс. позиций"),
            KeyboardButton(text="◀️ Назад")
        ]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
