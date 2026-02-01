from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from bot.keyboards.profile_menu import get_profile_menu, get_statistics_menu
from bot.keyboards.main_menu import get_main_menu
from data.user_data import UserDataManager
from services.bingx_api import BingXAPI
from services.statistics import StatisticsManager
from datetime import datetime

router = Router()
user_data = UserDataManager()


@router.message(F.text == "👤 Профиль")
async def profile_menu(message: Message):
    """Улучшенное меню профиля с информацией"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    # Получаем базовую статистику
    try:
        from services.statistics import StatisticsManager
        stats = StatisticsManager(None, user_id)
        basic_stats = await stats.get_statistics(period='24h', is_demo=data.get('is_demo_mode', True))
        
        menu_text = (
            f"👤 <b>ПРОФИЛЬ</b>\n\n"
            f"💵 Режим: {'🧪 ДЕМО' if data.get('is_demo_mode', True) else '⚠️ РЕАЛЬНЫЙ'}\n"
            f"📊 Сделок за 24ч: {basic_stats.get('total_trades', 0)}\n"
            f"🎯 Win Rate: {basic_stats.get('win_rate', 0)}%\n"
            f"💰 Чистая прибыль: {basic_stats.get('net_profit', 0)} USDT\n\n"
            f"Выберите раздел:"
        )
    except:
        menu_text = (
            f"👤 <b>ПРОФИЛЬ</b>\n\n"
            f"💵 Режим: {'🧪 ДЕМО' if data.get('is_demo_mode', True) else '⚠️ РЕАЛЬНЫЙ'}\n\n"
            f"Выберите раздел:"
        )
    
    await message.answer(
        menu_text,
        reply_markup=get_profile_menu(),
        parse_mode='HTML'
    )


@router.message(F.text == "💰 Баланс")
async def show_balance(message: Message):
    """Показать баланс"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Загружаю баланс...")
    
    try:
        if not is_demo and (not data.get('api_key') or not data.get('secret_key')):
            await message.answer(
                "❌ Сначала подключите API BingX в настройках"
            )
            return
        
        if is_demo:
            # Демо-режим
            demo_balance = data.get('demo_balance', 10000.0)
            balance_text = (
                f"💰 Баланс (ДЕМО-режим):\n\n"
                f"💵 Общий баланс: {demo_balance:.2f} USDT\n"
                f"🆓 Доступно: {demo_balance:.2f} USDT\n"
                f"📊 Equity: {demo_balance:.2f} USDT\n\n"
                f"⚠️ Это виртуальный баланс для тестирования"
            )
        else:
            api = BingXAPI(
                api_key=data.get('api_key'),
                secret_key=data.get('secret_key'),
                sandbox=False
            )
            
            stats = StatisticsManager(api, user_id)
            balance_info = await stats.get_balance_info(is_demo=False)
            
            balance_text = (
                f"💰 Баланс:\n\n"
                f"💵 Общий баланс: {balance_info.get('total', 0):.2f} USDT\n"
                f"🆓 Доступно: {balance_info.get('free', 0):.2f} USDT\n"
                f"📊 Equity: {balance_info.get('equity', 0):.2f} USDT\n"
            )
            
            if balance_info.get('unrealized_pnl', 0) != 0:
                pnl = balance_info.get('unrealized_pnl', 0)
                pnl_sign = "📈" if pnl > 0 else "📉"
                balance_text += f"{pnl_sign} Нереализованный P&L: {pnl:.2f} USDT\n"
            
            if balance_info.get('open_positions', 0) > 0:
                balance_text += f"📋 Открытых позиций: {balance_info.get('open_positions', 0)}\n"
        
        await message.answer(balance_text)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения баланса: {str(e)}")


@router.message(F.text.in_(["📊 Статистика"]))
async def statistics_menu(message: Message):
    """Меню статистики (из профиля или главного меню)"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    # Показываем быструю статистику и меню выбора периода
    try:
        from services.statistics import StatisticsManager
        stats = StatisticsManager(None, user_id)
        quick_stats = await stats.get_statistics(period='24h', is_demo=data.get('is_demo_mode', True))
        
        quick_text = (
            f"📊 <b>БЫСТРАЯ СТАТИСТИКА</b> (24ч)\n\n"
            f"Сделок: {quick_stats.get('total_trades', 0)}\n"
            f"Win Rate: {quick_stats.get('win_rate', 0)}%\n"
            f"Чистая прибыль: {quick_stats.get('net_profit', 0)} USDT\n\n"
            f"Выберите период для детального анализа:"
        )
    except:
        quick_text = "📊 Выберите период для статистики:"
    
    await message.answer(
        quick_text,
        reply_markup=get_statistics_menu(),
        parse_mode='HTML'
    )


@router.message(F.text.in_(["⏰ За последний час", "⏰ Час", "📅 За 24 часа", "📅 24ч", "📆 За неделю", "📆 Неделя", "🗓️ За месяц", "🗓️ Месяц", "📈 Общая статистика", "📈 Общая"]))
async def show_statistics(message: Message):
    """Показать статистику"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    
    period_map = {
        "⏰ За последний час": "1h",
        "⏰ Час": "1h",
        "📅 За 24 часа": "24h",
        "📅 24ч": "24h",
        "📆 За неделю": "7d",
        "📆 Неделя": "7d",
        "🗓️ За месяц": "30d",
        "🗓️ Месяц": "30d",
        "📈 Общая статистика": "all",
        "📈 Общая": "all"
    }
    
    period = period_map.get(message.text, "24h")
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Загружаю статистику...")
    
    try:
        if not is_demo and (not data.get('api_key') or not data.get('secret_key')):
            await message.answer(
                "❌ Сначала подключите API BingX в настройках"
            )
            return
        
        if is_demo:
            # В демо-режиме используем демо-статистику
            stats = StatisticsManager(None, user_id)
            stats_data = await stats.get_statistics(period, is_demo=True)
        else:
            api = BingXAPI(
                api_key=data.get('api_key'),
                secret_key=data.get('secret_key'),
                sandbox=False
            )
            stats = StatisticsManager(api, user_id)
            stats_data = await stats.get_statistics(period, is_demo=False)
        
        stats_text = stats.format_statistics_message(stats_data)
        await message.answer(stats_text)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения статистики: {str(e)}")


@router.message(F.text.in_(["📜 История сделок", "📜 История"]))
async def show_trade_history(message: Message):
    """Показать историю сделок"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Загружаю историю...")
    
    try:
        if not is_demo and (not data.get('api_key') or not data.get('secret_key')):
            await message.answer(
                "❌ Сначала подключите API BingX в настройках"
            )
            return
        
        if is_demo:
            stats = StatisticsManager(None, user_id)
            trades = await stats.get_trade_history(limit=20, is_demo=True)
        else:
            api = BingXAPI(
                api_key=data.get('api_key'),
                secret_key=data.get('secret_key'),
                sandbox=False
            )
            stats = StatisticsManager(api, user_id)
            trades = await stats.get_trade_history(limit=20, is_demo=False)
        
        if not trades:
            await message.answer("📜 История сделок пуста")
            return
        
        history_text = "📜 Последние сделки:\n\n"
        for i, trade in enumerate(trades[-10:], 1):  # Показываем последние 10
            direction = trade.get('direction', 'N/A')
            symbol = trade.get('symbol', 'N/A')
            pnl = trade.get('pnl', 0)
            pnl_sign = "📈" if pnl > 0 else "📉"
            status = trade.get('status', 'closed')
            entry = trade.get('entry', 0)
            close_price = trade.get('close_price')
            
            history_text += f"{i}. {symbol} {direction.upper()}\n"
            history_text += f"   Вход: {entry:.2f} USDT"
            if close_price:
                history_text += f" | Выход: {close_price:.2f} USDT"
            history_text += f"\n   {pnl_sign} P&L: {pnl:.2f} USDT | Статус: {status}\n\n"
        
        # Добавляем информацию о закрытых сделках
        closed_count = len([t for t in trades if t.get('status') == 'closed'])
        open_count = len([t for t in trades if t.get('status') == 'open'])
        
        history_text += f"\n📊 Всего: {len(trades)} | Открыто: {open_count} | Закрыто: {closed_count}"
        
        await message.answer(history_text, parse_mode='HTML')
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения истории: {str(e)}")


@router.message(F.text == "📈 Расширенная статистика")
async def show_advanced_statistics(message: Message):
    """Показать расширенную статистику с глубоким анализом"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Загружаю расширенную статистику...")
    
    try:
        if not is_demo and (not data.get('api_key') or not data.get('secret_key')):
            await message.answer("❌ Сначала подключите API BingX в настройках")
            return
        
        stats = StatisticsManager(None, user_id) if is_demo else StatisticsManager(
            BingXAPI(api_key=data.get('api_key'), secret_key=data.get('secret_key'), sandbox=False),
            user_id
        )
        
        # Получаем расширенную статистику
        advanced_stats = await stats.get_advanced_statistics(period='7d', is_demo=is_demo)
        
        # Формируем сообщение
        msg = f"📈 <b>РАСШИРЕННАЯ СТАТИСТИКА</b> (7 дней)\n\n"
        
        # Базовая статистика
        basic = advanced_stats.get('basic_stats', {})
        msg += f"📊 <b>ОСНОВНЫЕ МЕТРИКИ</b>\n"
        msg += f"Сделок: {basic.get('total_trades', 0)}\n"
        msg += f"Win Rate: {basic.get('win_rate', 0)}%\n"
        msg += f"Profit Factor: {basic.get('profit_factor', 0)}\n"
        msg += f"Чистая прибыль: {basic.get('net_profit', 0)} USDT\n\n"
        
        # Анализ по парам
        pair_analysis = advanced_stats.get('pair_analysis', {})
        if pair_analysis:
            msg += f"📊 <b>АНАЛИЗ ПО ПАРАМ</b>\n"
            # Топ-3 лучшие пары
            sorted_pairs = sorted(pair_analysis.items(), key=lambda x: x[1].get('win_rate', 0), reverse=True)
            for symbol, stats_data in sorted_pairs[:3]:
                msg += f"{symbol}: WR {stats_data.get('win_rate', 0)}%, PnL {stats_data.get('total_pnl', 0):.2f} USDT\n"
            msg += "\n"
        
        # Метрики риска
        risk_metrics = advanced_stats.get('risk_metrics', {})
        if risk_metrics:
            msg += f"⚠️ <b>РИСК-МЕТРИКИ</b>\n"
            msg += f"Sortino Ratio: {risk_metrics.get('sortino_ratio', 0)}\n"
            msg += f"Max Losing Streak: {risk_metrics.get('max_losing_streak', 0)}\n"
            msg += f"Recovery Factor: {risk_metrics.get('recovery_factor', 0)}\n\n"
        
        # Рекомендации
        recommendations = advanced_stats.get('recommendations', [])
        if recommendations:
            msg += f"💡 <b>РЕКОМЕНДАЦИИ</b>\n"
            for rec in recommendations[:3]:
                msg += f"• {rec}\n"
        
        await message.answer(msg, parse_mode='HTML')
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения статистики: {str(e)}")


@router.message(F.text == "📉 Анализ по парам")
async def show_pair_analysis(message: Message):
    """Показать детальный анализ по торговым парам"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Анализирую пары...")
    
    try:
        stats = StatisticsManager(None, user_id) if is_demo else StatisticsManager(
            BingXAPI(api_key=data.get('api_key'), secret_key=data.get('secret_key'), sandbox=False),
            user_id
        )
        
        advanced_stats = await stats.get_advanced_statistics(period='30d', is_demo=is_demo)
        pair_analysis = advanced_stats.get('pair_analysis', {})
        
        if not pair_analysis:
            await message.answer("📊 Недостаточно данных для анализа по парам")
            return
        
        msg = "📉 <b>АНАЛИЗ ПО ПАРАМ</b> (30 дней)\n\n"
        
        # Сортируем по win rate
        sorted_pairs = sorted(pair_analysis.items(), key=lambda x: x[1].get('win_rate', 0), reverse=True)
        
        for symbol, stats_data in sorted_pairs[:10]:  # Топ-10
            wr = stats_data.get('win_rate', 0)
            pnl = stats_data.get('total_pnl', 0)
            pf = stats_data.get('profit_factor', 0)
            trades = stats_data.get('total_trades', 0)
            
            emoji = "✅" if wr > 50 and pnl > 0 else "⚠️" if wr < 40 else "📊"
            
            msg += (
                f"{emoji} <b>{symbol}</b>\n"
                f"   Сделок: {trades} | WR: {wr}% | PF: {pf:.2f}\n"
                f"   PnL: {pnl:+.2f} USDT\n\n"
            )
        
        await message.answer(msg, parse_mode='HTML')
        
    except Exception as e:
        await message.answer(f"❌ Ошибка анализа: {str(e)}")


@router.message(F.text == "🎯 Анализ эффективности")
async def show_efficiency_analysis(message: Message):
    """Показать анализ эффективности стратегий"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Анализирую эффективность...")
    
    try:
        stats = StatisticsManager(None, user_id) if is_demo else StatisticsManager(
            BingXAPI(api_key=data.get('api_key'), secret_key=data.get('secret_key'), sandbox=False),
            user_id
        )
        
        advanced_stats = await stats.get_advanced_statistics(period='30d', is_demo=is_demo)
        
        msg = "🎯 <b>АНАЛИЗ ЭФФЕКТИВНОСТИ</b> (30 дней)\n\n"
        
        # Анализ по направлениям
        direction_analysis = advanced_stats.get('direction_analysis', {})
        if direction_analysis:
            msg += f"📊 <b>ПО НАПРАВЛЕНИЯМ</b>\n"
            long_stats = direction_analysis.get('long', {})
            short_stats = direction_analysis.get('short', {})
            
            if long_stats.get('total', 0) > 0:
                msg += (
                    f"🟢 LONG: {long_stats.get('total', 0)} сделок, "
                    f"WR {long_stats.get('win_rate', 0)}%, "
                    f"PnL {long_stats.get('total_pnl', 0):+.2f} USDT\n"
                )
            
            if short_stats.get('total', 0) > 0:
                msg += (
                    f"🔴 SHORT: {short_stats.get('total', 0)} сделок, "
                    f"WR {short_stats.get('win_rate', 0)}%, "
                    f"PnL {short_stats.get('total_pnl', 0):+.2f} USDT\n"
                )
            msg += "\n"
        
        # Анализ по таймфреймам
        timeframe_analysis = advanced_stats.get('timeframe_analysis', {})
        if timeframe_analysis:
            msg += f"⏰ <b>ПО ТАЙМФРЕЙМАМ</b>\n"
            for tf, tf_stats in timeframe_analysis.items():
                if tf_stats.get('total', 0) > 0:
                    msg += (
                        f"{tf}: {tf_stats.get('total', 0)} сделок, "
                        f"WR {tf_stats.get('win_rate', 0)}%, "
                        f"PnL {tf_stats.get('total_pnl', 0):+.2f} USDT\n"
                    )
            msg += "\n"
        
        # Корреляция индикаторов
        indicator_corr = advanced_stats.get('indicator_correlation', {})
        signal_corr = indicator_corr.get('signal_strength_correlation', {})
        if signal_corr:
            msg += f"📈 <b>КОРРЕЛЯЦИЯ СИГНАЛОВ</b>\n"
            for strength, corr_data in signal_corr.items():
                if corr_data.get('total', 0) > 0:
                    msg += (
                        f"{strength.upper()}: WR {corr_data.get('win_rate', 0)}%, "
                        f"Avg PnL {corr_data.get('avg_pnl', 0):+.2f} USDT\n"
                    )
        
        await message.answer(msg, parse_mode='HTML')
        
    except Exception as e:
        await message.answer(f"❌ Ошибка анализа: {str(e)}")


@router.message(F.text == "📤 Экспорт данных")
async def export_data(message: Message):
    """Экспорт данных в CSV"""
    user_id = message.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    await message.answer("⏳ Подготавливаю данные для экспорта...")
    
    try:
        stats = StatisticsManager(None, user_id) if is_demo else StatisticsManager(
            BingXAPI(api_key=data.get('api_key'), secret_key=data.get('secret_key'), sandbox=False),
            user_id
        )
        
        trades = await stats.get_trade_history(limit=1000, is_demo=is_demo)
        
        if not trades:
            await message.answer("❌ Нет данных для экспорта")
            return
        
        # Формируем CSV
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow([
            'Symbol', 'Direction', 'Entry', 'Close', 'Amount',
            'PnL', 'Status', 'Entry Time', 'Close Time', 'Reason'
        ])
        
        # Данные
        for trade in trades:
            writer.writerow([
                trade.get('symbol', ''),
                trade.get('direction', ''),
                trade.get('entry', 0),
                trade.get('close_price', ''),
                trade.get('amount', 0),
                trade.get('pnl', 0),
                trade.get('status', ''),
                trade.get('timestamp', ''),
                trade.get('close_time', ''),
                trade.get('close_reason', '')
            ])
        
        csv_data = output.getvalue()
        output.close()
        
        # Отправляем файл
        from aiogram.types import BufferedInputFile
        csv_file = BufferedInputFile(
            csv_data.encode('utf-8'),
            filename=f"trades_export_{user_id}_{datetime.now().strftime('%Y%m%d')}.csv"
        )
        
        await message.answer_document(
            document=csv_file,
            caption=f"📤 Экспорт данных ({len(trades)} сделок)"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка экспорта: {str(e)}")
        
        # Добавляем кнопку экспорта в CSV
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        export_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Экспорт в CSV", callback_data=f"export_csv_{user_id}")]
        ])
        
        await message.answer(history_text, reply_markup=export_keyboard)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения истории: {str(e)}")


@router.callback_query(F.data.startswith("export_csv_"))
async def export_to_csv(callback_query):
    """Экспорт истории сделок в CSV (из tt.txt)"""
    user_id = callback_query.from_user.id
    data = user_data.get_user_data(user_id)
    is_demo = data.get('is_demo_mode', True)
    
    try:
        if is_demo:
            stats = StatisticsManager(None, user_id)
            trades = await stats.get_trade_history(limit=1000, is_demo=True)
        else:
            api = BingXAPI(
                api_key=data.get('api_key'),
                secret_key=data.get('secret_key'),
                sandbox=False
            )
            stats = StatisticsManager(api, user_id)
            trades = await stats.get_trade_history(limit=1000, is_demo=False)
        
        if not trades:
            await callback_query.answer("Нет данных для экспорта", show_alert=True)
            return
        
        # Создаём CSV
        import csv
        import io
        from datetime import datetime
        
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        
        # Заголовки
        writer.writerow([
            'Timestamp', 'Symbol', 'Direction', 'Entry', 'Close Price',
            'Amount', 'Stop Loss', 'Take Profit', 'PnL', 'Status', 'Close Reason'
        ])
        
        # Данные
        for trade in trades:
            writer.writerow([
                trade.get('timestamp', ''),
                trade.get('symbol', ''),
                trade.get('direction', ''),
                trade.get('entry', 0),
                trade.get('close_price', ''),
                trade.get('amount', 0),
                trade.get('stop_loss', ''),
                trade.get('take_profit', ''),
                trade.get('pnl', 0),
                trade.get('status', ''),
                trade.get('close_reason', '')
            ])
        
        csv_data = csv_buffer.getvalue()
        csv_buffer.close()
        
        # Отправляем файл
        from aiogram.types import BufferedInputFile
        csv_file = BufferedInputFile(
            csv_data.encode('utf-8'),
            filename=f"trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        
        await callback_query.message.answer_document(
            document=csv_file,
            caption=f"📥 Экспорт истории сделок ({len(trades)} записей)"
        )
        await callback_query.answer("✅ Экспорт выполнен")
        
    except Exception as e:
        await callback_query.answer(f"❌ Ошибка экспорта: {str(e)}", show_alert=True)
