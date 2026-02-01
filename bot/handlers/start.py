from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.keyboards.main_menu import get_main_menu
from data.user_data import UserDataManager

router = Router()
user_data = UserDataManager()


@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    welcome_text = (
        "🤖 Добро пожаловать в Trading Bot для BingX!\n\n"
        "Я ваш личный торговый ассистент с автоматическим анализом рынка.\n\n"
        "📋 Быстрый старт:\n"
        "1️⃣ Подключите API BingX в настройках\n"
        "2️⃣ Выберите режим торговли (демо/реальный)\n"
        "3️⃣ Настройте риск-менеджмент\n"
        "4️⃣ Готово! Можете начинать торговлю\n\n"
        "Используйте меню ниже для навигации."
    )
    
    is_demo = data.get('is_demo_mode', True)
    auto_enabled = data.get('auto_trading_enabled', False)
    await message.answer(
        welcome_text,
        reply_markup=get_main_menu(is_demo, auto_enabled)
    )


@router.message(F.text == "◀️ Назад")
async def cmd_back(message: Message, state: FSMContext):
    """Обработчик кнопки 'Назад'"""
    await state.clear()
    
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    auto_enabled = data.get('auto_trading_enabled', False)
    
    await message.answer(
        "Главное меню",
        reply_markup=get_main_menu(is_demo, auto_enabled)
    )


@router.message(F.text.in_(["🧪 ДЕМО", "⚠️ РЕАЛЬНЫЙ"]))
async def toggle_mode_from_main(message: Message):
    """Переключение режима из главного меню"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    current_mode = data.get('is_demo_mode', True)
    
    # Определяем, что хочет пользователь по тексту кнопки
    if "ДЕМО" in message.text:
        new_mode = True
    elif "РЕАЛЬНЫЙ" in message.text:
        new_mode = False
    else:
        new_mode = not current_mode
    
    if new_mode == current_mode:
        # Режим не изменился
        if new_mode:
            await message.answer(
                "🧪 Демо-режим уже включен\n\n"
                "Бот торгует виртуально без риска для реальных средств.\n"
                f"Начальный баланс: 10,000 USDT"
            )
        else:
            await message.answer(
                "⚠️ Реальный режим уже включен\n\n"
                "Внимание! Торговля реальными средствами."
            )
        return
    
    if new_mode:
        # Включаем демо
        user_data.update_user_setting(user_id, 'is_demo_mode', True)
        await message.answer(
            "🧪 Демо-режим включен\n\n"
            "Бот будет торговать виртуально без риска для реальных средств.\n"
            f"Начальный баланс: 10,000 USDT"
        )
    else:
        # Включаем реальный режим
        if not data.get('api_key') or not data.get('secret_key'):
            await message.answer(
                "❌ Сначала подключите API BingX для реального режима"
            )
            return
        
        user_data.update_user_setting(user_id, 'is_demo_mode', False)
        await message.answer(
            "⚠️ РЕАЛЬНЫЙ РЕЖИМ ВКЛЮЧЕН\n\n"
            "Внимание! Торговля реальными средствами.\n"
            "Убедитесь в настройках риска!"
        )
    
    # Обновляем меню
    updated_data = user_data.get_user_data(user_id)
    await message.answer(
        "Настройки обновлены",
        reply_markup=get_main_menu(
            updated_data.get('is_demo_mode', True),
            updated_data.get('auto_trading_enabled', False)
        )
    )


@router.message(F.text == "/cancel")
async def cmd_cancel(message: Message, state: FSMContext):
    """Обработчик команды /cancel"""
    await state.clear()
    
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    auto_enabled = data.get('auto_trading_enabled', False)
    
    await message.answer(
        "❌ Операция отменена",
        reply_markup=get_main_menu(is_demo, auto_enabled)
    )
