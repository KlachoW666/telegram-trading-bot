from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.keyboards.settings_menu import (
    get_settings_menu, get_api_settings_menu, get_risk_settings_menu
)
from bot.keyboards.main_menu import get_main_menu
from bot.states import SettingsStates
from data.user_data import UserDataManager
from services.bingx_api import BingXAPI

router = Router()
user_data = UserDataManager()


@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message):
    """Меню настроек"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer(
        "⚙️ Настройки",
        reply_markup=get_settings_menu(is_demo)
    )


@router.message(F.text.in_(["🔑 API BingX", "🔑 API"]))
async def api_settings_menu(message: Message):
    """Меню настроек API"""
    await message.answer(
        "🔑 Настройки API BingX",
        reply_markup=get_api_settings_menu()
    )


@router.message(F.text.in_(["➕ Подключить API", "➕ Подключить"]))
async def connect_api(message: Message, state: FSMContext):
    """Начать подключение API"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    if data.get('api_key') and data.get('secret_key'):
        await message.answer(
            "⚠️ API уже подключен. Используйте 'Изменить API' для обновления."
        )
        return
    
    await state.set_state(SettingsStates.waiting_for_api_key)
    await message.answer(
        "🔑 Введите ваш API KEY от BingX:\n\n"
        "Или отправьте /cancel для отмены"
    )


@router.message(SettingsStates.waiting_for_api_key)
async def process_api_key(message: Message, state: FSMContext):
    """Обработка API ключа"""
    # Проверяем команду отмены
    if message.text == "/cancel":
        await state.clear()
        user_id = message.from_user.id
        data = user_data.get_user_data(user_id)
        is_demo = data.get('is_demo_mode', True)
        await message.answer(
            "❌ Подключение API отменено",
            reply_markup=get_settings_menu(is_demo)
        )
        return
    
    api_key = message.text.strip()
    
    if len(api_key) < 10:
        await message.answer("❌ Неверный формат API KEY. Длина должна быть не менее 10 символов.\nПопробуйте снова или отправьте /cancel")
        return
    
    await state.update_data(api_key=api_key)
    await state.set_state(SettingsStates.waiting_for_secret_key)
    
    await message.answer(
        "🔐 Введите ваш SECRET KEY от BingX:\n\n"
        "Или отправьте /cancel для отмены"
    )


@router.message(SettingsStates.waiting_for_secret_key)
async def process_secret_key(message: Message, state: FSMContext):
    """Обработка SECRET ключа"""
    # Проверяем команду отмены
    if message.text == "/cancel":
        await state.clear()
        user_id = message.from_user.id
        data = user_data.get_user_data(user_id)
        is_demo = data.get('is_demo_mode', True)
        await message.answer(
            "❌ Подключение API отменено",
            reply_markup=get_settings_menu(is_demo)
        )
        return
    
    secret_key = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    api_key = data.get('api_key')
    
    if not api_key:
        await state.clear()
        await message.answer("❌ Ошибка: API KEY не найден. Начните заново.")
        return
    
    if len(secret_key) < 10:
        await message.answer("❌ Неверный формат SECRET KEY. Длина должна быть не менее 10 символов.\nПопробуйте снова или отправьте /cancel")
        return
    
    # Сохраняем ключи без проверки (как в project)
    # Проверка будет происходить при первом использовании API
    try:
        # Сохраняем оба ключа одновременно для атомарности
        current_data = user_data.get_user_data(user_id)
        current_data['api_key'] = api_key
        current_data['secret_key'] = secret_key
        user_data.save_user_data(user_id, current_data)
        
        await state.clear()
        
        # Получаем обновленные данные для проверки
        # Принудительно читаем из БД заново
        if user_data.use_database and user_data.db:
            # Очищаем возможный кэш, читая напрямую из БД
            updated_data = user_data.db.get_user(user_id)
            if updated_data:
                is_demo = updated_data.get('is_demo_mode', True)
            else:
                is_demo = current_data.get('is_demo_mode', True)
        else:
            is_demo = current_data.get('is_demo_mode', True)
        
        await message.answer(
            "✅ <b>API ключи сохранены!</b>\n\n"
            "Ключи будут проверены при первом использовании API.\n"
            "Теперь вы можете использовать реальный режим торговли.\n\n"
            "💡 Используйте кнопку '✅ Проверить API' для проверки ключей.",
            reply_markup=get_settings_menu(is_demo),
            parse_mode='HTML'
        )
    except Exception as e:
        await message.answer(
            f"❌ Ошибка при сохранении ключей: {str(e)}\n\n"
            "Попробуйте снова или отправьте /cancel"
        )


@router.message(F.text.in_(["✏️ Изменить API", "✏️ Изменить"]))
async def change_api(message: Message, state: FSMContext):
    """Изменить API ключи"""
    await state.set_state(SettingsStates.waiting_for_api_key)
    await message.answer(
        "🔑 Введите новый API KEY от BingX:\n\n"
        "Или отправьте /cancel для отмены"
    )


@router.message(F.text.in_(["✅ Проверить API", "✅ Проверить"]))
async def test_api(message: Message):
    """Проверить текущий API"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    if not data.get('api_key') or not data.get('secret_key'):
        await message.answer("❌ API не подключен")
        return
    
    await message.answer("⏳ Проверяю API...")
    
    try:
        api = BingXAPI(
            api_key=data.get('api_key'),
            secret_key=data.get('secret_key'),
            sandbox=False  # BingX не имеет testnet API
        )
        is_valid = await api.test_api()
        
        if is_valid:
            await message.answer("✅ API работает корректно!")
        else:
            await message.answer("❌ API не работает. Проверьте ключи.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")


@router.message(F.text.in_(["🧪 ДЕМО", "⚠️ РЕАЛЬНЫЙ", "🟢 Демо", "⚪ Демо"]))
async def toggle_demo_mode(message: Message):
    """Переключить демо-режим"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    current_mode = data.get('is_demo_mode', True)
    
    # Определяем, что хочет пользователь по тексту кнопки
    if "ДЕМО" in message.text or ("Демо" in message.text and "🟢" in message.text):
        new_mode = True
    elif "РЕАЛЬНЫЙ" in message.text or ("Реал" in message.text and "🟢" in message.text):
        new_mode = False
    else:
        # Переключаем на противоположный
        new_mode = not current_mode
    
    if new_mode == current_mode:
        # Режим не изменился, просто показываем текущий статус
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
        reply_markup=get_settings_menu(updated_data.get('is_demo_mode', True))
    )


@router.message(F.text.contains("Реал"))
async def toggle_real_mode(message: Message):
    """Переключить реальный режим (аналогично демо)"""
    await toggle_demo_mode(message)


@router.message(F.text.in_(["⚖️ Риск-менеджмент", "⚖️ Риск"]))
async def risk_management_menu(message: Message):
    """Меню риск-менеджмента"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    risk_text = (
        "⚖️ Текущие настройки риск-менеджмента:\n\n"
        f"📊 Макс. % на позицию: {data.get('risk_per_trade', 1.5)}%\n"
        f"🎯 Take-Profit: {data.get('take_profit_percent', 3.0)}%\n"
        f"🛑 Stop-Loss: {data.get('stop_loss_percent', 1.5)}%\n"
        f"📈 Плечо: {data.get('leverage', 10)}x\n"
        f"🔢 Макс. позиций: {data.get('max_open_positions', 5)}\n"
    )
    
    await message.answer(
        risk_text,
        reply_markup=get_risk_settings_menu()
    )


@router.message(F.text.in_(["📊 Макс. % на позицию", "📊 Макс. %"]))
async def set_risk_percent(message: Message, state: FSMContext):
    """Установить максимальный % риска на позицию"""
    await state.set_state(SettingsStates.waiting_for_risk_percent)
    await message.answer(
        "📊 Введите максимальный % от баланса на одну позицию:\n\n"
        "Пример: 1.5 (для 1.5%)\n"
        "Рекомендуется: 1-2%\n\n"
        "Или отправьте /cancel для отмены"
    )


@router.message(SettingsStates.waiting_for_risk_percent)
async def process_risk_percent(message: Message, state: FSMContext):
    """Обработка % риска"""
    try:
        risk = float(message.text.replace(',', '.'))
        
        if risk < 0.1 or risk > 10:
            await message.answer("❌ Значение должно быть от 0.1% до 10%. Попробуйте снова или /cancel")
            return
        
        user_id = message.from_user.id
        user_data.update_user_setting(user_id, 'risk_per_trade', risk)
        
        await state.clear()
        await message.answer(f"✅ Максимальный риск на позицию установлен: {risk}%")
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 1.5) или /cancel")


@router.message(F.text.in_(["🎯 Take-Profit по умолчанию", "🎯 Take-Profit"]))
async def set_tp_percent(message: Message, state: FSMContext):
    """Установить Take-Profit"""
    await state.set_state(SettingsStates.waiting_for_tp_percent)
    await message.answer(
        "🎯 Введите % прибыли для Take-Profit:\n\n"
        "Пример: 3 (для +3%)\n\n"
        "Или отправьте /cancel для отмены"
    )


@router.message(SettingsStates.waiting_for_tp_percent)
async def process_tp_percent(message: Message, state: FSMContext):
    """Обработка TP"""
    try:
        tp = float(message.text.replace(',', '.'))
        
        if tp < 0.1 or tp > 50:
            await message.answer("❌ Значение должно быть от 0.1% до 50%. Попробуйте снова или /cancel")
            return
        
        user_id = message.from_user.id
        user_data.update_user_setting(user_id, 'take_profit_percent', tp)
        
        await state.clear()
        await message.answer(f"✅ Take-Profit установлен: {tp}%")
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 3) или /cancel")


@router.message(F.text.in_(["🛑 Stop-Loss по умолчанию", "🛑 Stop-Loss"]))
async def set_sl_percent(message: Message, state: FSMContext):
    """Установить Stop-Loss"""
    await state.set_state(SettingsStates.waiting_for_sl_percent)
    await message.answer(
        "🛑 Введите % убытка для Stop-Loss:\n\n"
        "Пример: 1.5 (для -1.5%)\n\n"
        "Или отправьте /cancel для отмены"
    )


@router.message(SettingsStates.waiting_for_sl_percent)
async def process_sl_percent(message: Message, state: FSMContext):
    """Обработка SL"""
    try:
        sl = float(message.text.replace(',', '.'))
        
        if sl < 0.1 or sl > 10:
            await message.answer("❌ Значение должно быть от 0.1% до 10%. Попробуйте снова или /cancel")
            return
        
        user_id = message.from_user.id
        user_data.update_user_setting(user_id, 'stop_loss_percent', sl)
        
        await state.clear()
        await message.answer(f"✅ Stop-Loss установлен: {sl}%")
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 1.5) или /cancel")


@router.message(F.text.in_(["📈 Trailing Stop", "📈 Trailing"]))
async def set_trailing_stop(message: Message):
    """Настройка Trailing Stop"""
    await message.answer("💡 Trailing Stop в разработке")


@router.message(F.text.in_(["🔢 Макс. открытых позиций", "🔢 Макс. позиций"]))
async def set_max_positions(message: Message, state: FSMContext):
    """Установить максимальное количество открытых позиций"""
    await state.set_state(SettingsStates.waiting_for_max_positions)
    await message.answer(
        "🔢 Введите максимальное количество открытых позиций:\n\n"
        "Пример: 5\n\n"
        "Или отправьте /cancel для отмены"
    )


@router.message(SettingsStates.waiting_for_max_positions)
async def process_max_positions(message: Message, state: FSMContext):
    """Обработка максимального количества позиций"""
    try:
        max_pos = int(message.text.strip())
        
        if max_pos < 1 or max_pos > 20:
            await message.answer("❌ Значение должно быть от 1 до 20. Попробуйте снова или /cancel")
            return
        
        user_id = message.from_user.id
        user_data.update_user_setting(user_id, 'max_open_positions', max_pos)
        
        await state.clear()
        await message.answer(f"✅ Максимальное количество позиций установлено: {max_pos}")
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите целое число (например: 5) или /cancel")


@router.message(F.text.in_(["📊 Выбор пар / стратегий", "📊 Пары"]))
async def pairs_selection_menu(message: Message):
    """Меню выбора пар"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    from config.settings import DEFAULT_PAIRS
    user_pairs = data.get('trading_pairs') or []
    pairs = user_pairs if user_pairs else DEFAULT_PAIRS
    
    pairs_text = "📊 Текущие торговые пары:\n\n"
    for i, pair in enumerate(pairs, 1):
        pairs_text += f"{i}. {pair}\n"
    
    pairs_text += "\n💡 Функция изменения пар в разработке"
    
    await message.answer(pairs_text)


@router.message(F.text.in_(["🔔 Уведомления"]))
async def notifications_menu(message: Message):
    """Меню уведомлений"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    notifications_enabled = data.get('notifications_enabled', True)
    
    status = "включены" if notifications_enabled else "выключены"
    status_emoji = "🟢" if notifications_enabled else "🔴"
    
    await message.answer(
        f"{status_emoji} Уведомления {status}\n\n"
        "💡 Функция настройки уведомлений в разработке"
    )
