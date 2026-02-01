from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.keyboards.trading_menu import (
    get_trading_menu, get_manual_trading_menu, 
    get_positions_menu, get_signal_actions_menu, get_smc_analysis_menu, get_strategy_profiles_menu
)
from bot.keyboards.main_menu import get_main_menu
from bot.states import TradingStates
from data.user_data import UserDataManager
from services.bingx_api import BingXAPI
from services.trading import TradingEngine
from services.market_analysis import MarketAnalyzer
from services.statistics import StatisticsManager
from services.auto_trading import AutoTradingManager
from services.strategy_profiles import StrategyProfiles

router = Router()
user_data = UserDataManager()
auto_trading_manager = AutoTradingManager()  # Глобальный менеджер авто-торговли
profiles = StrategyProfiles()


@router.message(F.text == "📊 Торговля")
async def trading_menu(message: Message):
    """Улучшенное меню торговли с информацией о позициях"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    auto_enabled = data.get('auto_trading_enabled', False)
    
    # Получаем количество открытых позиций
    try:
        from services.statistics import StatisticsManager
        stats = StatisticsManager(None, user_id)
        open_trades = stats.get_demo_trades(status='open') if data.get('is_demo_mode', True) else []
        positions_count = len(open_trades)
    except:
        positions_count = 0
    
    # Проверяем наличие API ключей (только для реального режима)
    # Проверяем что ключи не только существуют, но и не пустые
    api_key = data.get('api_key')
    secret_key = data.get('secret_key')
    has_api = bool(api_key and secret_key and api_key.strip() and secret_key.strip())
    is_demo = data.get('is_demo_mode', True)
    
    menu_text = (
        f"📊 <b>РАЗДЕЛ ТОРГОВЛИ</b>\n\n"
        f"🔄 Авто-торговля: {'🟢 ВКЛ' if auto_enabled else '🔴 ВЫКЛ'}\n"
        f"📋 Открытых позиций: {positions_count}\n"
        f"💵 Режим: {'🧪 ДЕМО' if is_demo else '⚠️ РЕАЛЬНЫЙ'}\n\n"
        f"Выберите действие:"
    )
    
    await message.answer(
        menu_text,
        reply_markup=get_trading_menu(auto_enabled, positions_count),
        parse_mode='HTML'
    )
    
    # Показываем предупреждение только если в реальном режиме, нет API и авто-торговля выключена
    # Не показываем предупреждение если ключи есть или если авто-торговля уже включена
    if not is_demo and not has_api and not auto_enabled:
        await message.answer(
            "⚠️ <b>Для авто-торговли в реальном режиме нужны API ключи</b>\n\n"
            "Подключите API ключи BingX в настройках, чтобы включить авто-торговлю.",
            parse_mode='HTML'
        )


@router.message(F.text.in_(["🧠 Профиль", "🧠 Стратегия"]))
async def choose_profile_menu(message: Message):
    """Выбор профиля стратегии (как в pycryptobot: конфиг-профили)"""
    plist = profiles.list_profiles()
    titles = [f"✅ {p.title}" if user_data.get_user_data(message.from_user.id).get("strategy_profile") == p.key else p.title for p in plist]
    if not titles:
        await message.answer("Профили не найдены (нет `config/strategy_profiles.json`).")
        return
    await message.answer("🧠 Выберите профиль стратегии:", reply_markup=get_strategy_profiles_menu(titles))


@router.message(F.text.contains("Скальп") | F.text.contains("Тренд") | F.text.contains("✅"))
async def set_profile(message: Message):
    """Установка профиля по названию"""
    text = message.text.replace("✅", "").strip()
    plist = profiles.list_profiles()
    match = next((p for p in plist if p.title == text), None)
    if not match:
        return  # не наш обработчик
    user_id = message.from_user.id
    user_data.update_user_setting(user_id, "strategy_profile", match.key)
    # Также пробросим некоторые параметры профиля в user_data, чтобы авто-торговля читала их напрямую
    user_data.update_user_setting(user_id, "max_drawdown_percent", match.max_drawdown_percent)
    user_data.update_user_setting(user_id, "sl_cooldown_minutes", match.sl_cooldown_minutes)
    user_data.update_user_setting(user_id, "atr_min_percent", match.atr_min_percent)
    user_data.update_user_setting(user_id, "timeframe", match.timeframe)
    user_data.update_user_setting(user_id, "htf_timeframe", match.htf_timeframe)

    await message.answer(f"✅ Профиль установлен: {match.title}", reply_markup=get_trading_menu(user_data.get_user_data(user_id).get("auto_trading_enabled", False)))


@router.message(F.text.in_(["🧪 Сканер", "🧪 Сканер рынка"]))
async def scan_market(message: Message):
    """Сканер рынка: топ сигналов по списку пар"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    if not data.get('api_key') or not data.get('secret_key'):
        await message.answer("❌ Сначала подключите API BingX в настройках")
        return

    await message.answer("⏳ Сканирую рынок (топ-сигналы)...")

    api = BingXAPI(
        api_key=data.get('api_key'),
        secret_key=data.get('secret_key'),
        sandbox=False
    )
    engine = TradingEngine(api, is_demo=data.get("is_demo_mode", True))

    tf = data.get("timeframe", "5m")
    # берём ограничение из профиля (или дефолт)
    prof = profiles.get_or_default(data.get("strategy_profile"))
    from config.settings import DEFAULT_PAIRS
    user_pairs = data.get("trading_pairs") or []
    if user_pairs:
        pairs = user_pairs[: prof.scan_pairs_limit]
    else:
        # Если у пользователя нет сохранённых пар, используем DEFAULT_PAIRS
        pairs = DEFAULT_PAIRS[: prof.scan_pairs_limit]
    if not pairs:
        pairs = DEFAULT_PAIRS[: prof.scan_pairs_limit] or ['BTC/USDT:USDT']

    top = await engine.scan_market(pairs=pairs, timeframe=tf, top_n=prof.scan_top_n)
    if not top:
        await message.answer("Сильных сигналов не найдено.")
        return

    lines = [f"🧪 Топ сигналы ({tf}) — профиль: {prof.title}\n"]
    for i, r in enumerate(top, 1):
        lines.append(
            f"{i}. {r['symbol']} — {r['final_signal'].upper()} ~{r['probability']:.0f}% "
            f"(подтв.: {r.get('confirmations', 0)})"
        )
    await message.answer("\n".join(lines))


@router.message(F.text.contains("Авто"))
async def toggle_auto_trading(message: Message):
    """Включить/выключить авто-торговлю"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    current_status = data.get('auto_trading_enabled', False)
    new_status = not current_status
    
    # Проверяем API перед включением
    if new_status:
        if not data.get('api_key') or not data.get('secret_key'):
            await message.answer(
                "❌ Сначала подключите API BingX в настройках для авто-торговли"
            )
            return
    
    # Обновляем статус
    user_data.update_user_setting(user_id, 'auto_trading_enabled', new_status)
    
    # Запускаем или останавливаем авто-торговлю
    try:
        if new_status:
            started = await auto_trading_manager.start_auto_trading(user_id)
            if started:
                status_text = "включена и запущена"
            else:
                status_text = "включена (уже была запущена)"
        else:
            stopped = await auto_trading_manager.stop_auto_trading(user_id)
            status_text = "выключена и остановлена"
    except Exception as e:
        status_text = f"{'включена' if new_status else 'выключена'} (ошибка запуска: {str(e)})"
    
    await message.answer(
        f"🤖 Авто-торговля {status_text}",
        reply_markup=get_trading_menu(new_status)
    )


@router.message(F.text.in_(["✋ Ручная торговля", "✋ Ручная"]))
async def manual_trading_menu(message: Message):
    """Меню ручной торговли"""
    await message.answer(
        "✋ Выберите торговую пару:",
        reply_markup=get_manual_trading_menu()
    )


@router.message(F.text.in_(["BTC/USDT", "ETH/USDT", "SOL/USDT"]))
async def select_pair(message: Message, state: FSMContext):
    """Выбор пары для торговли"""
    pair = message.text
    symbol = f"{pair.split('/')[0]}/USDT:USDT"
    
    await state.update_data(symbol=symbol, pair=pair)
    await state.set_state(TradingStates.waiting_for_direction)
    
    await message.answer(
        f"Выбрана пара: {pair}\n\n"
        "Выберите направление:\n"
        "📈 LONG (покупка)\n"
        "📉 SHORT (продажа)"
    )


@router.message(F.text.in_(["📋 Мои позиции", "📋 Позиции"]))
async def positions_menu(message: Message):
    """Меню позиций"""
    await message.answer(
        "📋 Управление позициями",
        reply_markup=get_positions_menu()
    )


@router.message(F.text.in_(["📈 Сигналы сейчас", "📈 Сигналы", "📈 Сигналы"]))
async def show_signals(message: Message):
    """Показать текущие сигналы (из меню торговли или главного меню)"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    # Проверяем API
    if not data.get('api_key') or not data.get('secret_key'):
        await message.answer(
            "❌ Сначала подключите API BingX в настройках",
            reply_markup=get_main_menu(
                data.get('is_demo_mode', True),
                data.get('auto_trading_enabled', False)
            )
        )
        return
    
    await message.answer("⏳ Анализирую рынок...")
    
    try:
        is_demo = data.get('is_demo_mode', True)
        # BingX не имеет testnet API, всегда используем реальный API
        # Демо-режим контролируется на уровне логики бота
        api = BingXAPI(
            api_key=data.get('api_key'),
            secret_key=data.get('secret_key'),
            sandbox=False
        )
        
        trading_engine = TradingEngine(api, is_demo=is_demo)
        
        # Анализируем первую пару из списка
        from config.settings import DEFAULT_PAIRS
        user_pairs = data.get('trading_pairs') or []
        pairs = user_pairs if user_pairs else DEFAULT_PAIRS
        symbol = pairs[0] if pairs else 'BTC/USDT:USDT'
        
        result = await trading_engine.analyze_and_trade(symbol)
        
        if 'error' in result:
            await message.answer(f"❌ Ошибка: {result['error']}")
            return
        
        analysis = result.get('analysis', {})
        decision = result.get('decision', {})
        
        # Формируем отчёт
        report = format_analysis_report(analysis, symbol)
        
        await message.answer(
            report,
            reply_markup=get_signal_actions_menu()
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка анализа: {str(e)}")


@router.message(F.text.in_(["📊 Список позиций", "📊 Список"]))
async def list_positions(message: Message):
    """Показать список открытых позиций"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Загружаю позиции...")
    
    try:
        if not is_demo and (not data.get('api_key') or not data.get('secret_key')):
            await message.answer("❌ Сначала подключите API BingX в настройках")
            return
        
        if is_demo:
            await message.answer("📊 В демо-режиме позиции пока не реализованы")
            return
        
        api = BingXAPI(
            api_key=data.get('api_key'),
            secret_key=data.get('secret_key'),
            sandbox=False
        )
        
        positions = await api.get_positions()
        
        if not positions:
            await message.answer("📊 Нет открытых позиций")
            return
        
        positions_text = "📊 Открытые позиции:\n\n"
        for i, pos in enumerate(positions, 1):
            symbol = pos.get('symbol', 'N/A')
            side = pos.get('side', 'N/A')
            size = pos.get('contracts', 0)
            entry = pos.get('entryPrice', 0)
            mark = pos.get('markPrice', 0)
            pnl = pos.get('unrealizedPnl', 0)
            pnl_percent = pos.get('percentage', 0)
            
            pnl_sign = "📈" if pnl > 0 else "📉" if pnl < 0 else "➖"
            
            positions_text += f"{i}. {symbol} {side.upper()}\n"
            positions_text += f"   Размер: {abs(size)}\n"
            positions_text += f"   Вход: {entry:.2f}\n"
            positions_text += f"   Текущая: {mark:.2f}\n"
            positions_text += f"   {pnl_sign} P&L: {pnl:.2f} USDT ({pnl_percent:.2f}%)\n\n"
        
        await message.answer(positions_text)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения позиций: {str(e)}")


@router.message(F.text.in_(["❌ Закрыть все позиции", "❌ Закрыть все"]))
async def close_all_positions(message: Message):
    """Закрыть все позиции"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    if is_demo:
        await message.answer("✅ В демо-режиме все позиции закрыты (виртуально)")
        return
    
    if not data.get('api_key') or not data.get('secret_key'):
        await message.answer("❌ Сначала подключите API BingX в настройках")
        return
    
    await message.answer("⏳ Закрываю все позиции...")
    
    try:
        api = BingXAPI(
            api_key=data.get('api_key'),
            secret_key=data.get('secret_key'),
            sandbox=False
        )
        
        closed = await api.close_all_positions()
        
        if closed > 0:
            await message.answer(f"✅ Закрыто позиций: {closed}")
        else:
            await message.answer("📊 Нет открытых позиций для закрытия")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка закрытия позиций: {str(e)}")


@router.message(F.text.in_(["✅ Открыть по сигналу", "✅ Открыть"]))
async def open_by_signal(message: Message):
    """Открыть позицию по сигналу"""
    await message.answer(
        "⏳ Функция открытия по сигналу в разработке.\n"
        "Используйте ручную торговлю для открытия позиций."
    )


def format_analysis_report(analysis: dict, symbol: str) -> str:
    """Форматирует отчёт анализа с расширенными техниками"""
    current_price = analysis.get('current_price', 0)
    indicators = analysis.get('indicators', {})
    candle_analysis = analysis.get('candle_analysis', {})
    advanced_analysis = analysis.get('advanced_analysis', {})
    final_signal = analysis.get('final_signal', 'neutral')
    probability = analysis.get('probability', 0)
    recommendation = analysis.get('recommendation')
    
    report = f"📊 Анализ {symbol}\n\n"
    report += f"💰 Текущая цена: {current_price:.2f} USDT\n\n"
    
    # RSI
    rsi = indicators.get('rsi', {})
    if rsi.get('value'):
        rsi_signal = rsi.get('signal', 'neutral')
        signal_text = {
            'oversold': '→ перепроданность',
            'overbought': '→ перекупленность',
            'neutral': '→ нейтрально'
        }.get(rsi_signal, '')
        report += f"📈 RSI(14): {rsi['value']:.2f} {signal_text}\n"

    # VWAP / MFI / OBV / Ichimoku (как в Crypto-Signal)
    vwap = indicators.get("vwap")
    if vwap and vwap.get("value"):
        report += f"📏 VWAP: {vwap['value']:.2f} ({vwap.get('position', 'unknown')})\n"

    mfi = indicators.get("mfi")
    if mfi and mfi.get("value") is not None:
        report += f"💧 MFI(14): {mfi['value']:.2f} ({mfi.get('signal', 'neutral')})\n"

    obv = indicators.get("obv")
    if obv and obv.get("value") is not None:
        report += f"🧱 OBV: {obv.get('trend', 'unknown')}\n"

    ichi = indicators.get("ichimoku")
    if ichi and ichi.get("position") and ichi.get("position") != "unknown":
        report += f"☁️ Ichimoku: {ichi.get('position')}\n"
    
    # Свечные паттерны
    patterns = candle_analysis.get('patterns', [])
    if patterns:
        report += f"🕯️ Паттерны: {', '.join(patterns[:3])}\n"  # Показываем только первые 3
    
    # Расширенный анализ
    if advanced_analysis:
        # Order Flow
        order_flow = advanced_analysis.get('order_flow', {})
        if order_flow.get('direction') != 'neutral':
            of_direction = order_flow.get('direction', 'neutral')
            of_strength = order_flow.get('strength', 1)
            report += f"🔄 Order Flow: {of_direction.upper()} (сила: {of_strength})\n"
        
        # IMB зоны
        imbalances = advanced_analysis.get('imbalances', [])
        if imbalances:
            latest_imb = imbalances[-1]
            report += f"⚖️ IMB: {latest_imb.get('type', 'unknown')} ({latest_imb.get('direction', '')})\n"
        
        # FVG
        fvgs = advanced_analysis.get('fvgs', [])
        if fvgs:
            latest_fvg = fvgs[-1]
            report += f"📊 FVG: {latest_fvg.get('type', 'unknown')} на {latest_fvg.get('mid_point', 0):.2f}\n"
        
        # Свипы ликвидности
        sweeps = advanced_analysis.get('liquidity_sweeps', [])
        if sweeps:
            latest_sweep = sweeps[-1]
            report += f"💧 Свип: {latest_sweep.get('type', 'unknown')}\n"
        
        # Пулы ликвидности
        pools = advanced_analysis.get('liquidity_pools', {})
        if pools.get('poc'):
            poc = pools.get('poc', 0)
            position = pools.get('analysis', {}).get('position', 'unknown')
            report += f"🏊 POC: {poc:.2f} (позиция: {position})\n"
        
        # BOS/CHOCH
        structure = advanced_analysis.get('structure', {})
        if structure.get('bos'):
            report += f"📈 BOS: {structure['bos'].get('type', 'unknown')}\n"
        if structure.get('choch'):
            report += f"🔄 CHOCH: {structure['choch'].get('type', 'unknown')}\n"
    
    # Стакан
    orderbook_analysis = analysis.get('orderbook_analysis')
    if orderbook_analysis:
        summary = orderbook_analysis.get('summary', '')
        if summary:
            report += f"📚 Стакан: {summary}\n"
    
    report += f"\n🎯 Общий сигнал: {final_signal.upper()} (вероятность ~{probability}%)\n"
    
    if recommendation:
        report += f"\n💡 Рекомендация:\n"
        report += f"Направление: {recommendation.get('direction', 'N/A')}\n"
        if recommendation.get('entry'):
            report += f"Вход: {recommendation['entry']:.2f}\n"
        if recommendation.get('stop_loss'):
            report += f"Стоп-лосс: {recommendation['stop_loss']:.2f}\n"
        if recommendation.get('take_profit'):
            report += f"Тейк-профит: {recommendation['take_profit']:.2f}\n"
        if recommendation.get('reason'):
            report += f"Причина: {recommendation['reason']}\n"
    
    return report
