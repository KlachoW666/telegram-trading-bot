from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_profile_menu() -> ReplyKeyboardMarkup:
    """Меню профиля"""
    keyboard = [
        [
            KeyboardButton(text="💰 Баланс"),
            KeyboardButton(text="📊 Статистика")
        ],
        [
            KeyboardButton(text="📜 История"),
            KeyboardButton(text="◀️ Назад")
        ]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_statistics_menu() -> ReplyKeyboardMarkup:
    """Меню статистики"""
    keyboard = [
        [
            KeyboardButton(text="⏰ Час"),
            KeyboardButton(text="📅 24ч")
        ],
        [
            KeyboardButton(text="📆 Неделя"),
            KeyboardButton(text="🗓️ Месяц")
        ],
        [
            KeyboardButton(text="📈 Общая"),
            KeyboardButton(text="◀️ Назад")
        ]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
