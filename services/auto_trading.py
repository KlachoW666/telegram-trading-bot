import asyncio
import time
import traceback
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, timezone
from services.bingx_api import BingXAPI
from services.trading import TradingEngine
from services.statistics import StatisticsManager
from data.user_data import UserDataManager
from config.settings import (
    DEFAULT_PAIRS,
    SCALPING_BLOCKED_PAIRS,
    SCALPING_BLOCKED_HOURS,
    SCALPING_BLOCKED_WEEKDAYS,
)
from services.chart_generator import ChartGenerator
from aiogram.types import BufferedInputFile

if TYPE_CHECKING:
    from aiogram import Bot


class AutoTradingManager:
    """Менеджер автоматической торговли"""
    
    def __init__(self):
        self.active_tasks: Dict[int, asyncio.Task] = {}  # user_id -> task
        self.user_data = UserDataManager()
        self.bot: Optional['Bot'] = None  # Бот для отправки сообщений
        # Cooldown после SL по паре (symbol -> timestamp последнего SL)
        self.sl_cooldowns: Dict[str, float] = {}  # symbol -> timestamp
        self.sl_cooldown_minutes = 15  # Минут cooldown после SL
    
    def set_bot(self, bot: 'Bot'):
        """Установить экземпляр бота для отправки сообщений"""
        self.bot = bot
    
    async def start_auto_trading(self, user_id: int):
        """Запустить автоматическую торговлю для пользователя"""
        if user_id in self.active_tasks:
            return False  # Уже запущено
        
        task = asyncio.create_task(self._auto_trading_loop(user_id))
        self.active_tasks[user_id] = task
        return True
    
    async def stop_auto_trading(self, user_id: int):
        """Остановить автоматическую торговлю для пользователя"""
        if user_id not in self.active_tasks:
            return False
        
        task = self.active_tasks[user_id]
        task.cancel()
        del self.active_tasks[user_id]
        return True
    
    async def _auto_trading_loop(self, user_id: int):
        """Основной цикл автоматической торговли"""
        print(f"[Авто-торговля] Запуск для пользователя {user_id}")
        
        # Запускаем отдельный цикл мониторинга позиций (каждые 30 секунд)
        monitoring_task = asyncio.create_task(self._monitoring_loop(user_id))
        
        try:
            cycle_count = 0
            while True:
                try:
                    cycle_count += 1
                    data = self.user_data.get_user_data(user_id)
                
                    # Проверяем, что авто-торговля всё ещё включена
                    if not data.get('auto_trading_enabled', False):
                        print(f"[Авто-торговля] Остановка для пользователя {user_id} - авто-торговля выключена")
                        break
                
                    # Проверяем API
                    if not data.get('api_key') or not data.get('secret_key'):
                        print(f"[Авто-торговля] Пользователь {user_id}: API не подключен, ожидание...")
                        await asyncio.sleep(60)  # Ждём минуту и проверяем снова
                        continue

                    # ===== ФИЛЬТРЫ СКАЛЬПИНГА ПО ВРЕМЕНИ (UTC) =====
                    # Используем UTC-время, так как биржа и анализ отчётов ведутся в UTC.
                    now_utc = datetime.now(timezone.utc)
                    current_hour = now_utc.hour
                    current_weekday = now_utc.weekday()  # 0 = Понедельник

                    # Блокируем авто-торговлю в проблемные часы и дни недели
                    if current_hour in SCALPING_BLOCKED_HOURS or current_weekday in SCALPING_BLOCKED_WEEKDAYS:
                        reason_parts = []
                        if current_hour in SCALPING_BLOCKED_HOURS:
                            reason_parts.append(f"час {current_hour:02d}:00 (UTC)")
                        if current_weekday in SCALPING_BLOCKED_WEEKDAYS:
                            reason_parts.append("день недели с пониженной эффективностью")
                        reason = ", ".join(reason_parts)
                        print(
                            f"[Авто-торговля] ⏸ Скальпинг приостановлен для пользователя {user_id}: "
                            f"анализ показывает низкую эффективность ({reason}). Ожидание 15 минут..."
                        )
                        await asyncio.sleep(900)  # 15 минут пауза перед следующей попыткой
                        continue
                
                    print(f"[Авто-торговля] Цикл #{cycle_count} для пользователя {user_id}")
                
                    # Проверяем drawdown и авто-стоп
                    is_demo = data.get('is_demo_mode', True)
                    max_drawdown_percent = data.get('max_drawdown_percent', 20.0)
                    if is_demo:
                        initial_balance = 10000.0
                        current_balance = data.get('demo_balance', initial_balance)
                        drawdown = ((initial_balance - current_balance) / initial_balance * 100) if initial_balance > 0 else 0
                        if drawdown > max_drawdown_percent:
                            print(f"[Авто-торговля] ⛔ Авто-стоп: Drawdown {drawdown:.2f}% > {max_drawdown_percent}%")
                            self.user_data.update_user_setting(user_id, 'auto_trading_enabled', False)
                            if self.bot:
                                try:
                                    await self.bot.send_message(
                                        chat_id=user_id,
                                        text=(
                                            f"⛔ <b>АВТО-СТОП АКТИВИРОВАН</b>\n\n"
                                            f"Drawdown: {drawdown:.2f}% (лимит: {max_drawdown_percent}%)\n"
                                            f"Авто-торговля автоматически отключена для защиты депозита.\n\n"
                                            f"Включить снова можно в меню Торговля."
                                        ),
                                        parse_mode='HTML'
                                    )
                                except Exception:
                                    pass
                            break

                    # Авто-обновление скальпинг-пар: убираем "пустые" и заменяем на топ по объёму
                    # Делаем не каждый раз, чтобы не грузить API (раз в 5 циклов ≈ 15 минут)
                    if cycle_count == 1 or cycle_count % 5 == 0:
                        try:
                            await self._refresh_scalping_pairs(user_id, data)
                            # Перечитываем данные после обновления
                            data = self.user_data.get_user_data(user_id)
                        except Exception as e:
                            print(f"[Авто-торговля] ⚠️ Не удалось обновить список пар: {e}")
                
                    # Получаем список пар
                    # Используем сохранённые пары пользователя, если есть и их достаточно, иначе все DEFAULT_PAIRS
                    user_pairs = data.get("trading_pairs") or []
                    if user_pairs and len(user_pairs) >= len(DEFAULT_PAIRS):
                        pairs = user_pairs
                    else:
                        # Если у пользователя нет сохранённых пар или их меньше чем DEFAULT_PAIRS, используем все DEFAULT_PAIRS
                        pairs = DEFAULT_PAIRS.copy()
                        # Обновляем пары пользователя на все DEFAULT_PAIRS
                        if user_pairs != pairs:
                            self.user_data.update_user_setting(user_id, "trading_pairs", pairs)
                            print(f"[Авто-торговля] ✅ Обновлены пары пользователя на все {len(pairs)} пар из DEFAULT_PAIRS")

                    # Фильтруем пары, которые показали устойчиво плохие результаты для скальпинга
                    original_len = len(pairs)
                    pairs = [p for p in pairs if p not in SCALPING_BLOCKED_PAIRS]
                    if len(pairs) < original_len:
                        removed = original_len - len(pairs)
                        print(
                            f"[Авто-торговля] ⚠️ Исключено {removed} проблемных пар для скальпинга "
                            f"по результатам анализа (см. SCALPING_BLOCKED_PAIRS)"
                        )

                    if not pairs:
                        print("[Авто-торговля] ⛔ Нет доступных пар для скальпинга после фильтрации, ожидание 15 минут...")
                        await asyncio.sleep(900)
                        continue

                    preview = ", ".join([p.split('/')[0] for p in pairs[:10]])
                    dots = "..." if len(pairs) > 10 else ""
                    print(f"[Авто-торговля] Анализ {len(pairs)} пар: {preview}{dots}")
                
                    # Анализируем каждую пару
                    analyzed = 0
                    errors_count = 0
                
                    for symbol in pairs:
                        try:
                            await self._analyze_and_trade(user_id, symbol, data)
                            analyzed += 1
                            errors_count = 0  # Сбрасываем счётчик ошибок при успехе
                        except Exception as e:
                            errors_count += 1
                            error_msg = str(e)
                        
                            # Пропускаем ошибки соединения (временные проблемы с сетью)
                            if "Не удалось подключиться" in error_msg or "No route to host" in error_msg or "Request timeout" in error_msg:
                                print(f"[Авто-торговля] ⚠️ {symbol}: Проблемы с соединением (ошибка #{errors_count}) - пропускаем пару")
                                # Если много ошибок подряд - уведомляем пользователя (из tt.txt: обработка ошибок)
                                if errors_count >= 3 and self.bot:
                                    try:
                                        await self.bot.send_message(
                                            chat_id=user_id,
                                            text=(
                                                f"⚠️ <b>BingX API недоступен</b>\n\n"
                                                f"Множественные ошибки соединения ({errors_count}).\n"
                                                f"Авто-торговля продолжает работу, но некоторые пары могут быть пропущены.\n\n"
                                                f"Проверьте интернет-соединение и доступность BingX API."
                                            ),
                                            parse_mode='HTML'
                                        )
                                    except Exception:
                                        pass
                            elif "Signature verification" in error_msg:
                                print(f"[Авто-торговля] ⚠️ {symbol}: Ошибка подписи API (пробуем следующую пару)")
                            elif "Ошибка получения свечей" in error_msg or "Ошибка получения стакана" in error_msg:
                                # Проблемы с конкретной парой - пропускаем её, но не останавливаем весь цикл
                                print(f"[Авто-торговля] ⚠️ {symbol}: Проблемы с получением данных - пропускаем пару")
                            elif "Домен" in error_msg:
                                print(f"[Авто-торговля] ⚠️ {symbol}: Проблемы с доступностью домена (ошибка #{errors_count}) - пропускаем пару")
                            else:
                                print(f"[Авто-торговля] ❌ Ошибка при анализе {symbol}: {error_msg[:150]}")
                        
                            # Продолжаем со следующей парой даже при ошибках
                            # Если слишком много ошибок подряд - делаем короткую паузу, но продолжаем
                            if errors_count >= 5:
                                print(f"[Авто-торговля] ⚠️ Много ошибок подряд ({errors_count}), делаю паузу 15 сек перед следующей парой...")
                                await asyncio.sleep(15)
                                errors_count = 0  # Сбрасываем после паузы
                    
                        # Небольшая задержка между парами для снижения нагрузки
                        await asyncio.sleep(2)
                
                    print(f"[Авто-торговля] Цикл #{cycle_count} завершён ({analyzed}/{len(pairs)} пар проанализировано), ожидание 3 минуты...")
                
                    # Сокращено ожидание между циклами для более частого анализа
                    await asyncio.sleep(180)  # 3 минуты вместо 5
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    traceback.print_exc()
                    print(f"[Авто-торговля] ❌ Ошибка в цикле для {user_id}: {e}")
                    await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            print(f"[Авто-торговля] Остановлена пользователем для {user_id}")
            monitoring_task.cancel()
            raise
        finally:
            # Удаляем задачу из активных только при завершении цикла
            # (это может быть из-за отмены или отключения авто-торговли)
            if user_id in self.active_tasks:
                del self.active_tasks[user_id]

    async def _refresh_scalping_pairs(self, user_id: int, data: Dict, desired: int = None):
        """
        Убираем "пустые" пары и заменяем на пары с большим объёмом для скальпинга.

        Критерии "пустых":
        - Не удаётся получить тикер/свечи
        - 24h volume слишком маленький (если доступен)
        """
        api = BingXAPI(
            api_key=data.get('api_key'),
            secret_key=data.get('secret_key'),
            sandbox=False
        )

        current_pairs = data.get("trading_pairs") or []
        # Если desired не указан или у пользователя нет пар — используем все DEFAULT_PAIRS
        if desired is None:
            desired = len(DEFAULT_PAIRS)
        if not current_pairs or len(current_pairs) < desired:
            current_pairs = DEFAULT_PAIRS.copy()

        valid_pairs: List[str] = []
        removed_pairs: List[str] = []

        for sym in current_pairs:
            # Сразу пропускаем пары, которые показали устойчиво плохие результаты для скальпинга
            if sym in SCALPING_BLOCKED_PAIRS:
                removed_pairs.append(sym)
                continue

            try:
                ticker = await api.get_ticker(sym)
                vol = float(ticker.get("volume", 0) or 0)

                # Лёгкая проверка свечей, чтобы не было "пусто"
                _ = await api.get_ohlcv(sym, "5m", limit=100)

                # Фильтр по объёму: если совсем низкий объём — выкидываем
                # (порог мягкий, чтобы не убивать пары без volume в ответе)
                if vol > 0 and vol < 1_000_000:  # 1m USDT 24h
                    removed_pairs.append(sym)
                    continue

                valid_pairs.append(sym)
            except Exception:
                removed_pairs.append(sym)

        # Добиваем до нужного количества топом по объёму (только если desired указан)
        if desired is not None and len(valid_pairs) < desired:
            try:
                top = await api.get_top_usdt_perp_pairs_by_volume(limit=50)
            except Exception as e:
                print(f"[Авто-торговля] ⚠️ Не удалось получить топ-пары по объёму: {e}")
                top = []

            for sym in top:
                if sym in valid_pairs:
                    continue
                valid_pairs.append(sym)
                if len(valid_pairs) >= desired:
                    break

        # Финально режем до desired только если он указан, иначе используем все валидные пары
        if desired is not None:
            final_pairs = valid_pairs[:desired]
        else:
            final_pairs = valid_pairs

        if final_pairs != (data.get("trading_pairs") or []):
            self.user_data.update_user_setting(user_id, "trading_pairs", final_pairs)
            print(
                f"[Авто-торговля] ✅ Обновил пары для скальпинга: {len(final_pairs)} шт. "
                f"(убрано: {len(removed_pairs)}, добавлено топ-объёмом: {max(0, len(final_pairs) - (len(current_pairs) - len(removed_pairs)))})"
            )
    
    async def _monitoring_loop(self, user_id: int):
        """Отдельный цикл для частого мониторинга позиций (каждые 30 секунд)"""
        print(f"[Авто-торговля] 🔍 Запуск мониторинга позиций для пользователя {user_id}")
        try:
            while True:
                try:
                    data = self.user_data.get_user_data(user_id)
                    
                    # Проверяем, что авто-торговля всё ещё включена
                    if not data.get('auto_trading_enabled', False):
                        break
                    
                    # Проверяем API
                    if data.get('api_key') and data.get('secret_key'):
                        await self._monitor_positions(user_id, data)
                    
                    # Ждём 30 секунд перед следующей проверкой
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Авто-торговля] ⚠️ Ошибка в цикле мониторинга: {e}")
                    await asyncio.sleep(30)  # Продолжаем даже при ошибках
        except asyncio.CancelledError:
            print(f"[Авто-торговля] Мониторинг остановлен для {user_id}")
        except Exception as e:
            print(f"[Авто-торговля] ❌ Критическая ошибка в цикле мониторинга: {e}")
    
    async def _analyze_and_trade(self, user_id: int, symbol: str, data: Dict):
        """Анализирует и открывает позицию при необходимости"""
        try:
            is_demo = data.get('is_demo_mode', True)
            # Параметры из профиля (как в pycryptobot: конфиг управляет стратегией)
            timeframe = data.get("timeframe", "5m")
            atr_min_percent = float(data.get("atr_min_percent", 0.25) or 0.25)
            sl_cooldown_minutes = int(data.get("sl_cooldown_minutes", self.sl_cooldown_minutes) or self.sl_cooldown_minutes)
            
            # Проверяем cooldown после SL (из tt.txt: анти-оверторговля)
            cooldown_key = f"{user_id}_{symbol}"
            if cooldown_key in self.sl_cooldowns:
                last_sl_time = self.sl_cooldowns[cooldown_key]
                minutes_passed = (time.time() - last_sl_time) / 60
                if minutes_passed < sl_cooldown_minutes:
                    print(f"[Авто-торговля] ⏸️ {symbol}: Cooldown после SL ({minutes_passed:.1f}/{sl_cooldown_minutes} мин)")
                    return
            
            # BingX не имеет testnet API, всегда используем реальный API
            # Демо-режим контролируется на уровне логики бота
            api = BingXAPI(
                api_key=data.get('api_key'),
                secret_key=data.get('secret_key'),
                sandbox=False
            )
            
            trading_engine = TradingEngine(api, is_demo=is_demo)
            
            # Анализируем рынок
            result = await trading_engine.analyze_and_trade(symbol, timeframe=timeframe)
            
            if 'error' in result:
                # Пробрасываем ошибку, чтобы она была обработана в основном цикле
                raise Exception(f"Ошибка получения свечей: {result['error']}")
            
            decision = result.get('decision', {})
            action = decision.get('action', 'skip')
            reason = decision.get('reason', '')
            
            print(f"[Авто-торговля] {symbol}: {action} - {reason}")
            
            # Если сигнал на открытие позиции
            if action.startswith('open_'):
                # В ДЕМО-режиме не обращаемся к BingX за позициями (это paper trading)
                if not is_demo:
                    # Проверяем, нет ли уже открытых позиций (если проверка возможна)
                    try:
                        positions = await api.get_positions()
                        open_positions = [p for p in positions if p.get('contracts', 0) != 0]
                        
                        max_positions = data.get('max_open_positions', 5)
                        if len(open_positions) >= max_positions:
                            print(f"[Авто-торговля] {symbol}: Достигнут лимит позиций ({max_positions})")
                            return  # Достигнут лимит позиций
                        
                        # Проверяем, нет ли уже позиции по этой паре
                        for pos in open_positions:
                            if pos.get('symbol') == symbol:
                                print(f"[Авто-торговля] {symbol}: Позиция уже открыта")
                                return  # Позиция уже открыта
                    except Exception as pos_error:
                        # Если не удалось получить позиции (подпись/сеть) — продолжаем,
                        # чтобы не стопорить торговлю (особенно при временных проблемах).
                        error_msg = str(pos_error)
                        if "Signature" in error_msg or "100001" in error_msg:
                            print(f"[Авто-торговля] ⚠️ {symbol}: Не удалось проверить существующие позиции (ошибка API подписи), продолжаем открытие позиции")
                        elif "Не удалось подключиться" in error_msg or "No route to host" in error_msg:
                            print(f"[Авто-торговля] ⚠️ {symbol}: Не удалось подключиться к BingX при проверке позиций, продолжаем")
                        else:
                            # Для других ошибок тоже продолжаем, но логируем
                            print(f"[Авто-торговля] ⚠️ {symbol}: Ошибка при проверке позиций: {error_msg[:120]}, продолжаем открытие позиции")
                
                # Рассчитываем размер позиции и открываем позицию (выполняется всегда, независимо от результата проверки позиций)
                try:
                    balance_info = await api.get_balance() if not is_demo else {'total': data.get('demo_balance', 10000)}
                    balance = balance_info.get('total', 10000)
                    
                    risk_percent = data.get('risk_per_trade', 1.5)
                    recommendation = result.get('analysis', {}).get('recommendation')
                    current_price = result.get('analysis', {}).get('current_price') or result.get('current_price', 0)
                    
                    # Если current_price = 0, получаем цену напрямую из API
                    if current_price == 0 or current_price is None:
                        try:
                            ticker = await api.get_ticker(symbol)
                            current_price = float(ticker.get('last', 0))
                            if current_price == 0:
                                bid = float(ticker.get('bid', 0))
                                ask = float(ticker.get('ask', 0))
                                if bid > 0 and ask > 0:
                                    current_price = (bid + ask) / 2
                                elif bid > 0:
                                    current_price = bid
                                elif ask > 0:
                                    current_price = ask
                        except Exception as price_err:
                            print(f"[Авто-торговля] ⚠️ {symbol}: Не удалось получить цену: {price_err}")
                            current_price = 0
                    
                    # Используем рекомендации из анализа (на основе пулов ликвидности)
                    # Если recommendation есть - используем его, иначе рассчитываем сами
                    advanced_analysis = result.get('analysis', {}).get('advanced_analysis', {})
                    liquidity_pools = advanced_analysis.get('liquidity_pools', {})
                    
                    if recommendation:
                        entry = recommendation.get('entry', current_price)
                        stop_loss = recommendation.get('stop_loss')
                        take_profit = recommendation.get('take_profit')
                    else:
                        entry = current_price
                        stop_loss = None
                        take_profit = None

                    # Скальперский SL/TP от волатильности (ATR) — чтобы уровни были реалистичными
                    leverage = data.get('leverage', 5)
                    direction = 'long' if 'long' in action else 'short'
                    
                    # ATR-фильтр: если волатильность слишком низкая - пропускаем (из tt.txt)
                    try:
                        levels = await trading_engine.calculate_scalping_sl_tp(
                            symbol=symbol,
                            entry=entry,
                            direction=direction,
                            leverage=leverage,
                            timeframe=timeframe,
                            candles_limit=1440,
                        )
                        meta = levels.get("meta", {})
                        atr_pct = meta.get('atr_pct', 0)
                        
                        # Фильтр по ATR: если волатильность слишком низкая - пропускаем
                        if atr_pct < atr_min_percent:
                            print(
                                f"[Авто-торговля] ⏸️ {symbol}: Пропуск - низкая волатильность "
                                f"(ATR%={atr_pct:.2f}% < {atr_min_percent}%)"
                            )
                            return
                        
                        if levels.get("stop_loss") and levels.get("take_profit"):
                            stop_loss = float(levels["stop_loss"])
                            take_profit = float(levels["take_profit"])
                            print(
                                f"[Авто-торговля] {symbol}: ATR SL/TP калибровка "
                                f"(ATR%={atr_pct:.2f}%, SL%={meta.get('sl_pct', 0):.2f}%, TP%={meta.get('tp_pct', 0):.2f}%)"
                            )
                    except Exception as lvl_err:
                        print(f"[Авто-торговля] ⚠️ {symbol}: не удалось рассчитать ATR SL/TP: {lvl_err}")
                    
                    # Если entry не был установлен из recommendation, используем текущую цену
                    if not entry or entry == 0:
                        entry = current_price
                    
                    # ФИКСИРОВАННЫЙ размер позиции: ровно 100 USDT на каждую позицию
                    position_value = 100.0  # Фиксированный размер позиции в USDT
                    
                    # Рассчитываем количество монет/токенов для позиции размером 100 USDT
                    if entry > 0:
                        amount = position_value / entry
                    else:
                        print(f"[Авто-торговля] ❌ {symbol}: Невозможно рассчитать размер позиции - entry = 0")
                        return
                    
                    # Получаем данные для логирования (не влияют на размер позиции)
                    analysis_data = result.get('analysis', {})
                    probability = analysis_data.get('probability', 0)
                    decision_data = result.get('decision', {})
                    quality_score = decision_data.get('quality_score', 0) or 0
                    signal_strength = decision_data.get('signal_strength', 0) or 0
                    scale_factor = 1.0  # Для совместимости с уведомлениями (не влияет на размер)
                    
                    # Рассчитываем ожидаемую прибыль и риск
                    if stop_loss and take_profit:
                        risk_amount = abs(entry - stop_loss) * amount
                        potential_profit = abs(take_profit - entry) * amount
                        risk_reward_ratio = potential_profit / risk_amount if risk_amount > 0 else 0
                    else:
                        risk_amount = 0
                        potential_profit = 0
                        risk_reward_ratio = 0
                    
                    print(
                        f"[Авто-торговля] {symbol}: Рассчитанные параметры:\n"
                        f"  Entry: {entry:.2f}, SL: {stop_loss:.2f}, TP: {take_profit:.2f}\n"
                        f"  Amount: {amount:.6f}, Position Value: {position_value:.2f} USDT (фиксировано: $100)\n"
                        f"  Risk: {risk_amount:.2f} USDT, Potential Profit: {potential_profit:.2f} USDT\n"
                        f"  R/R Ratio: {risk_reward_ratio:.2f}\n"
                        f"  Probability: {probability}%, Quality Score: {quality_score}"
                    )
                    
                    # Минимальный размер позиции (защита от слишком маленьких позиций)
                    # Для фиксированного размера 100 USDT проверяем только минимальный объём монет
                    min_amount = 0.001  # Минимальный объём для крипты
                    if amount < min_amount:
                        print(f"[Авто-торговля] {symbol}: Размер позиции слишком мал ({amount:.6f} < {min_amount}) - возможно, цена слишком высокая")
                        return
                    
                    if amount > 0:
                        direction = 'long' if 'long' in action else 'short'
                        
                        print(f"[Авто-торговля] {symbol}: Открываю {direction.upper()} позицию - объём: {amount:.6f}, размер позиции: {position_value:.2f} USDT (фиксировано: $100), баланс: {balance:.2f} USDT")
                        
                        # Открываем позицию
                        trade_result = await trading_engine.execute_trade(
                            symbol=symbol,
                            direction=direction,
                            amount=amount,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            leverage=data.get('leverage', 5)
                        )
                        
                        # Логируем результат
                        if trade_result.get('success'):
                            entry_price_actual = trade_result.get('price', entry)
                            # Если цена все еще 0, используем entry или current_price
                            if entry_price_actual == 0 or entry_price_actual is None:
                                if entry and entry > 0:
                                    entry_price_actual = entry
                                else:
                                    # Получаем текущую цену как последний резерв
                                    try:
                                        ticker = await api.get_ticker(symbol)
                                        entry_price_actual = float(ticker.get('last', 0))
                                        if entry_price_actual == 0:
                                            bid = float(ticker.get('bid', 0))
                                            ask = float(ticker.get('ask', 0))
                                            if bid > 0 and ask > 0:
                                                entry_price_actual = (bid + ask) / 2
                                            elif bid > 0:
                                                entry_price_actual = bid
                                            elif ask > 0:
                                                entry_price_actual = ask
                                    except Exception as price_err:
                                        print(f"[Авто-торговля] ⚠️ Не удалось получить цену для {symbol}: {price_err}")
                                        entry_price_actual = current_price if current_price > 0 else 0
                            
                            # Критическая проверка: если цена все еще 0, не сохраняем позицию
                            if entry_price_actual == 0 or entry_price_actual is None:
                                print(f"[Авто-торговля] ❌ {symbol}: Невозможно открыть позицию - цена входа = 0")
                                return  # Выходим из функции, не открываем позицию
                            
                            order_id = trade_result.get('order_id')
                            
                            print(f"[Авто-торговля] ✅ {symbol}: Позиция открыта - {direction.upper()} {amount:.6f} @ {entry_price_actual:.2f}")
                            
                            stats = StatisticsManager(api, user_id)
                            if is_demo:
                                trade_data = {
                                    'symbol': symbol,
                                    'direction': direction,
                                    'amount': amount,
                                    'entry': entry_price_actual,
                                    'stop_loss': stop_loss,
                                    'take_profit': take_profit,
                                    'pnl': 0,
                                    'status': 'open',
                                    'leverage': leverage,
                                    'position_value': position_value,
                                    'risk_amount': risk_amount,
                                    'potential_profit': potential_profit,
                                    'risk_reward_ratio': risk_reward_ratio,
                                    'probability': probability,
                                    'quality_score': quality_score,
                                    'signal_strength': signal_strength,
                                    'scale_factor': scale_factor,
                                    'order_id': order_id,
                                    'is_demo': is_demo,
                                    'entry_time': datetime.now().isoformat()  # КРИТИЧНО: сохраняем время открытия для скальпинга
                                }
                                stats.add_demo_trade(trade_data)
                            
                            # Отправляем уведомление в Telegram с графиком
                            await self._send_trade_notification(
                                user_id, symbol, direction, amount, entry_price_actual,
                                stop_loss, take_profit, leverage, balance, reason,
                                result.get('analysis', {}), api, is_demo, order_id,
                                scale_factor=scale_factor, risk_percent=risk_percent
                            )
                        else:
                            error_msg = trade_result.get('error', 'Unknown error')
                            print(f"[Авто-торговля] ❌ {symbol}: Ошибка открытия позиции - {error_msg}")
                    else:
                        print(f"[Авто-торговля] {symbol}: Неверный размер позиции ({amount})")
                        
                except Exception as e:
                    print(f"[Авто-торговля] ❌ Ошибка при открытии позиции {symbol}: {e}")
                    traceback.print_exc()
        except Exception as e:
            # Пробрасываем ошибку наверх для обработки в основном цикле
            raise
    
    async def _send_trade_notification(self, user_id: int, symbol: str, direction: str,
                                      amount: float, entry: float, stop_loss: float,
                                      take_profit: float, leverage: int, balance: float,
                                      reason: str, analysis: Dict, api: BingXAPI,
                                      is_demo: bool, order_id: Optional[str] = None,
                                      scale_factor: float = 1.0, risk_percent: float = 0.0):
        """Отправляет уведомление о открытии позиции с графиком"""
        if not self.bot:
            return  # Бот не установлен, пропускаем отправку
        
        try:
            # Формируем сообщение
            mode_text = "🔴 ДЕМО" if is_demo else "🟢 РЕАЛЬНЫЙ"
            direction_emoji = "📈" if direction == 'long' else "📉"
            
            # Рассчитываем суммы в USDT
            # Размер позиции (номинал) = динамический расчет
            position_value = amount * entry  # Номинальный размер позиции
            # Маржа = размер позиции / плечо
            margin_used = position_value / leverage
            # Риск и прибыль рассчитываем от номинала позиции
            risk_amount = abs(entry - stop_loss) * amount
            potential_profit = abs(take_profit - entry) * amount
            
            # Процентные значения
            # risk_percent - это процент риска от баланса (из настроек пользователя)
            # sl_percent - это процент расстояния от входа до SL (для отображения)
            sl_percent = abs((entry - stop_loss) / entry * 100) if entry > 0 else 0
            profit_percent = abs((take_profit - entry) / entry * 100) if entry > 0 else 0
            risk_reward_ratio = potential_profit / risk_amount if risk_amount > 0 else 0
            
            # Если risk_percent не передан или равен 0, используем значение по умолчанию
            if risk_percent <= 0:
                risk_percent = 1.5  # Значение по умолчанию
            
            # Рассчитываем уровни для LONG и SHORT
            if direction == 'long':
                sl_distance = entry - stop_loss
                tp_distance = take_profit - entry
            else:  # short
                sl_distance = stop_loss - entry
                tp_distance = entry - take_profit
            
            # Доступный баланс после открытия позиции
            available_balance = balance - margin_used
            
            # Потенциальный PnL в процентах от маржи
            pnl_percent_of_margin = (potential_profit / margin_used * 100) if margin_used > 0 else 0
            
            message_text = (
                f"{direction_emoji} <b>ПОЗИЦИЯ ОТКРЫТА</b> {mode_text}\n"
                f"{'=' * 35}\n\n"
                
                f"<b>📊 ТОРГОВАЯ ПАРА</b>\n"
                f"<b>Пара:</b> {symbol}\n"
                f"<b>Направление:</b> {'🟢 LONG (покупка)' if direction == 'long' else '🔴 SHORT (продажа)'}\n"
                f"<b>Таймфрейм анализа:</b> 5m\n\n"
                
                f"<b>💰 ПАРАМЕТРЫ ПОЗИЦИИ</b>\n"
                f"<b>Объём:</b> {amount:.6f} {symbol.split('/')[0]}\n"
                f"<b>Цена входа:</b> {entry:.2f} USDT\n"
                f"<b>Размер позиции (номинал):</b> {position_value:.2f} USDT\n"
                f"<b>Плечо:</b> {leverage}x\n"
                f"<b>Использованная маржа:</b> {margin_used:.2f} USDT ({margin_used/position_value*100:.1f}% от номинала)\n"
                f"<b>Риск на сделку:</b> {risk_percent * scale_factor:.2f}% от баланса\n\n"
                
                f"<b>⚖️ РИСК-МЕНЕДЖМЕНТ</b>\n"
                f"<b>Stop Loss:</b> {stop_loss:.2f} USDT\n"
                f"<b>  └─ Расстояние:</b> {sl_distance:.2f} USDT ({sl_percent:.2f}%)\n"
                f"<b>Take Profit:</b> {take_profit:.2f} USDT\n"
                f"<b>  └─ Расстояние:</b> {tp_distance:.2f} USDT ({profit_percent:.2f}%)\n\n"
                
                f"<b>💵 ФИНАНСОВЫЕ ПАРАМЕТРЫ</b>\n"
                f"<b>Текущий баланс:</b> {balance:.2f} USDT\n"
                f"<b>Доступно после позиции:</b> {available_balance:.2f} USDT\n"
                f"<b>Плечо:</b> {leverage}x\n\n"
                
                f"<b>📈 РИСК И ПРИБЫЛЬ</b>\n"
                f"<b>Риск (при SL):</b> {risk_amount:.2f} USDT ({risk_amount / balance * 100:.2f}% от баланса)\n"
                f"<b>Потенциальная прибыль (при TP):</b> {potential_profit:.2f} USDT ({profit_percent:.2f}%)\n"
                f"<b>Соотношение риск/прибыль:</b> 1 : {risk_reward_ratio:.2f}\n"
                f"<b>PnL от маржи:</b> {pnl_percent_of_margin:.2f}%\n\n"
                
                f"<b>🎯 СИГНАЛ И АНАЛИЗ</b>\n"
                f"<b>Причина открытия:</b> {reason}\n"
                f"<b>Режим:</b> {'🔴 Демо-режим (виртуальные средства)' if is_demo else '🟢 Реальная торговля'}\n"
            )
            
            if order_id:
                message_text += f"\n<b>Order ID:</b> {order_id}"
            
            # Генерируем график
            chart_sent = False
            try:
                ohlcv = await api.get_ohlcv(symbol, '5m', limit=100)
                
                # Проверяем валидность данных
                if not ohlcv or len(ohlcv) < 2:
                    raise ValueError("Недостаточно данных для графика")
                
                indicators_data = {}
                
                # Извлекаем индикаторы из анализа, если они есть
                if 'indicators' in analysis and analysis['indicators']:
                    ind = analysis['indicators']
                    if 'bollinger' in ind and ind['bollinger']:
                        bb = ind['bollinger']
                        # Проверяем, что данные есть и это списки
                        bb_upper = bb.get('upper', [])
                        bb_lower = bb.get('lower', [])
                        bb_middle = bb.get('middle', [])
                        
                        # Преобразуем в списки чисел, если это не списки
                        if bb_upper and isinstance(bb_upper, list) and len(bb_upper) > 0:
                            indicators_data['bb_upper'] = [float(x) for x in bb_upper if x is not None]
                        if bb_lower and isinstance(bb_lower, list) and len(bb_lower) > 0:
                            indicators_data['bb_lower'] = [float(x) for x in bb_lower if x is not None]
                        if bb_middle and isinstance(bb_middle, list) and len(bb_middle) > 0:
                            indicators_data['bb_middle'] = [float(x) for x in bb_middle if x is not None]
                    
                    if 'ema' in ind and ind['ema']:
                        ema = ind['ema']
                        # Получаем EMA21, если есть
                        ema21_value = ema.get('ema_21')
                        if ema21_value is not None:
                            # Создаём список с последним значением EMA (для простоты используем последнее значение для всех свечей)
                            # В реальности нужно было бы хранить полный ряд EMA, но для визуализации достаточно последнего
                            pass  # Пропускаем EMA, так как нужен полный ряд данных
                
                chart_buffer = ChartGenerator.create_candle_chart(ohlcv, symbol, indicators_data if indicators_data else None)
                
                # Проверяем, что график создан успешно (buffer не пустой)
                chart_data = chart_buffer.read()
                chart_buffer.seek(0)  # Возвращаемся в начало для чтения
                
                if chart_data and len(chart_data) > 0:
                    chart_file = BufferedInputFile(chart_data, filename=f"{symbol.replace('/', '_')}_chart.png")
                    
                    # Отправляем сообщение с графиком
                    await self.bot.send_photo(
                        chat_id=user_id,
                        photo=chart_file,
                        caption=message_text,
                        parse_mode='HTML'
                    )
                    chart_sent = True
                else:
                    print(f"[Авто-торговля] ⚠️ График пустой, отправляю только текст")
                    # Не поднимаем исключение - просто отправляем текст
                
                # Закрываем buffer после использования
                chart_buffer.close()
                    
            except Exception as chart_error:
                import traceback
                print(f"[Авто-торговля] ⚠️ Ошибка генерации графика: {chart_error}")
                traceback.print_exc()
            
            # Если график не был отправлен, отправляем только текст
            if not chart_sent:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    parse_mode='HTML'
                )
        except Exception as e:
            print(f"[Авто-торговля] ⚠️ Ошибка отправки уведомления: {e}")
    
    async def _monitor_positions(self, user_id: int, data: Dict):
        """Мониторит позиции и закрывает их при достижении SL/TP"""
        try:
            is_demo = data.get('is_demo_mode', True)
            api = BingXAPI(
                api_key=data.get('api_key'),
                secret_key=data.get('secret_key'),
                sandbox=False
            )
            
            # Получаем статистику (хранит информацию о позициях с SL/TP)
            # StatisticsManager теперь загружает демо-позиции из user_data автоматически
            stats = StatisticsManager(api, user_id)
            
            # Для демо: проверяем демо-сделки (теперь они загружаются из user_data)
            if is_demo:
                open_trades = stats.get_demo_trades(status='open')
                if open_trades:
                    print(f"[Авто-торговля] 🔍 Мониторинг {len(open_trades)} открытых демо-позиций...")
                
                for trade in open_trades:
                    if trade.get('status') == 'open' and trade.get('close_price') is None:
                        symbol = trade['symbol']
                        entry = trade.get('entry', 0)
                        stop_loss = trade.get('stop_loss')
                        take_profit = trade.get('take_profit')
                        direction = trade.get('direction')
                        entry_time_str = trade.get('entry_time')
                        
                        if not entry or (not stop_loss and not take_profit):
                            continue
                        
                        # КРИТИЧНО: Проверка времени удержания для скальпинга
                        # Позиции должны закрываться через 5-10 минут максимум
                        max_holding_minutes = data.get('max_holding_minutes', 7)  # Рекомендуемое закрытие (по умолчанию 7 минут)
                        force_close_minutes = data.get('force_close_minutes', 10)  # Принудительное закрытие (по умолчанию 10 минут)
                        
                        holding_time_minutes = 0
                        should_close_time = False
                        time_close_reason = ""
                        
                        if entry_time_str:
                            try:
                                if isinstance(entry_time_str, str):
                                    entry_dt = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                                else:
                                    entry_dt = datetime.fromtimestamp(entry_time_str)
                                
                                current_dt = datetime.now(entry_dt.tzinfo) if entry_dt.tzinfo else datetime.now()
                                holding_time_minutes = (current_dt - entry_dt).total_seconds() / 60
                                
                                # Принудительное закрытие через 10 минут (максимум для скальпинга)
                                if holding_time_minutes >= force_close_minutes:
                                    should_close_time = True
                                    time_close_reason = f"Принудительное закрытие по времени ({holding_time_minutes:.1f} мин > {force_close_minutes} мин)"
                                # Рекомендуемое закрытие через 5-7 минут для скальпинга
                                elif holding_time_minutes >= max_holding_minutes:
                                    should_close_time = True
                                    time_close_reason = f"Рекомендуемое закрытие по времени ({holding_time_minutes:.1f} мин > {max_holding_minutes} мин)"
                            except Exception as time_err:
                                print(f"[Авто-торговля] ⚠️ Ошибка расчета времени удержания для {symbol}: {time_err}")
                        
                        try:
                            ticker = await api.get_ticker(symbol)
                            current_price = ticker.get('last', 0)
                            
                            if not current_price:
                                continue
                            
                            # Проверяем достижение SL/TP
                            should_close = False
                            close_reason = ""
                            
                            if direction == 'long':
                                if stop_loss and current_price <= stop_loss:
                                    should_close = True
                                    close_reason = f"Stop Loss достигнут ({stop_loss:.2f})"
                                elif take_profit and current_price >= take_profit:
                                    should_close = True
                                    close_reason = f"Take Profit достигнут ({take_profit:.2f})"
                            else:  # short
                                if stop_loss and current_price >= stop_loss:
                                    should_close = True
                                    close_reason = f"Stop Loss достигнут ({stop_loss:.2f})"
                                elif take_profit and current_price <= take_profit:
                                    should_close = True
                                    close_reason = f"Take Profit достигнут ({take_profit:.2f})"
                            
                            # Приоритет: сначала проверяем SL/TP, потом время
                            # Но если время критично (>10 мин) - закрываем принудительно
                            if should_close_time and holding_time_minutes >= force_close_minutes:
                                should_close = True
                                close_reason = time_close_reason
                            elif should_close_time and not should_close:
                                # Если позиция открыта >5-7 минут и не достигла TP/SL - закрываем
                                should_close = True
                                close_reason = time_close_reason
                            
                            if should_close:
                                # Закрываем демо-позицию
                                stats.close_demo_trade(symbol, current_price, close_reason)
                                print(f"[Авто-торговля] ✅ {symbol}: Демо-позиция закрыта - {close_reason} (цена: {current_price:.2f})")
                                
                                # Если закрытие по SL - устанавливаем cooldown (анти-оверторговля)
                                if "Stop Loss" in close_reason:
                                    import time
                                    cooldown_key = f"{user_id}_{symbol}"
                                    self.sl_cooldowns[cooldown_key] = time.time()
                                    sl_cooldown_minutes = data.get("sl_cooldown_minutes", self.sl_cooldown_minutes)
                                    print(f"[Авто-торговля] ⏸️ {symbol}: Cooldown {sl_cooldown_minutes} мин после SL")
                                
                                # Рассчитываем PnL
                                amount = trade.get('amount', 0)
                                # Критическая проверка: если entry = 0, PnL будет неправильным
                                if entry == 0 or entry is None:
                                    print(f"[Авто-торговля] ⚠️ Ошибка: entry = 0 для {symbol}, используем current_price как entry")
                                    entry = current_price
                                
                                if direction == 'long':
                                    pnl = (current_price - entry) * amount
                                else:
                                    pnl = (entry - current_price) * amount
                                
                                # Рассчитываем процент PnL
                                position_value = entry * amount if amount > 0 else 1
                                pnl_percent = (pnl / position_value * 100) if position_value > 0 else 0
                                
                                # Отправляем улучшенное уведомление о закрытии
                                if self.bot:
                                    try:
                                        await self._send_close_notification(
                                            user_id, symbol, direction, entry, current_price,
                                            stop_loss, take_profit, amount, pnl, pnl_percent,
                                            close_reason, is_demo
                                        )
                                        print(f"[Авто-торговля] ✅ Уведомление о закрытии {symbol} отправлено в Telegram")
                                    except Exception as notif_error:
                                        print(f"[Авто-торговля] ⚠️ Ошибка отправки уведомления о закрытии: {notif_error}")
                                        import traceback
                                        traceback.print_exc()
                                else:
                                    print(f"[Авто-торговля] ⚠️ Бот не установлен, уведомление не отправлено")
                        
                        except Exception as price_error:
                            # Игнорируем ошибки получения цены
                            continue
            
            # Для реальных позиций: проверяем статус через API
            if not is_demo:
                try:
                    positions = await api.get_positions()
                    open_real_positions = [p for p in positions if p.get('contracts', 0) != 0]
                    if open_real_positions:
                        print(f"[Авто-торговля] 🔍 Мониторинг {len(open_real_positions)} реальных позиций...")
                        # BingX автоматически закрывает через условные ордера (SL/TP)
                        # Но можем логировать статус для отладки
                        for pos in open_real_positions:
                            pos_symbol = pos.get('symbol', 'N/A')
                            unrealized_pnl = pos.get('unrealizedPnl', 0) or 0
                            print(f"[Авто-торговля] 📊 {pos_symbol}: PnL={unrealized_pnl:.2f} USDT")
                except Exception as real_pos_error:
                    # Не критично, если не удалось получить реальные позиции
                    error_msg = str(real_pos_error)
                    if "Signature" not in error_msg and "100001" not in error_msg:
                        print(f"[Авто-торговля] ⚠️ Ошибка проверки реальных позиций: {error_msg[:100]}")
            
        except Exception as e:
            # Игнорируем ошибки мониторинга, чтобы не блокировать основной цикл
            print(f"[Авто-торговля] ⚠️ Ошибка мониторинга позиций: {e}")
            traceback.print_exc()
    
    async def _send_close_notification(
        self, user_id: int, symbol: str, direction: str,
        entry: float, close_price: float, stop_loss: float,
        take_profit: float, amount: float, pnl: float,
        pnl_percent: float, close_reason: str, is_demo: bool
    ):
        """Отправляет улучшенное уведомление о закрытии позиции"""
        if not self.bot:
            return
        
        try:
            mode_text = "🔴 ДЕМО" if is_demo else "🟢 РЕАЛЬНЫЙ"
            pnl_emoji = "📈" if pnl >= 0 else "📉"
            close_type_emoji = "🛑" if "Stop Loss" in close_reason else "🎯"
            
            # Рассчитываем дополнительные метрики
            position_value = entry * amount if amount > 0 else 0
            risk_amount = abs(entry - stop_loss) * amount if stop_loss else 0
            potential_profit = abs(take_profit - entry) * amount if take_profit else 0
            
            # Процент от маржи
            leverage = self.user_data.get_user_data(user_id).get('leverage', 5)
            margin_used = position_value / leverage if leverage > 0 else position_value
            pnl_percent_of_margin = (pnl / margin_used * 100) if margin_used > 0 else 0
            
            # Длительность позиции (если есть timestamp)
            duration_text = ""
            # Можно добавить расчет длительности если есть timestamp входа
            
            message_text = (
                f"{close_type_emoji} <b>ПОЗИЦИЯ ЗАКРЫТА</b> {mode_text}\n"
                f"{'=' * 35}\n\n"
                
                f"<b>📊 ТОРГОВАЯ ПАРА</b>\n"
                f"<b>Пара:</b> {symbol}\n"
                f"<b>Направление:</b> {'🟢 LONG' if direction == 'long' else '🔴 SHORT'}\n"
                f"<b>Таймфрейм:</b> 5m\n\n"
                
                f"<b>💰 ЦЕНЫ</b>\n"
                f"<b>Вход:</b> {entry:.2f} USDT\n"
                f"<b>Выход:</b> {close_price:.2f} USDT\n"
                f"<b>Stop Loss:</b> {stop_loss:.2f} USDT\n"
                f"<b>Take Profit:</b> {take_profit:.2f} USDT\n\n"
                
                f"<b>📈 РЕЗУЛЬТАТ</b>\n"
                f"<b>PnL:</b> {pnl_emoji} {pnl:.2f} USDT ({pnl_percent:.2f}%)\n"
                f"<b>PnL от маржи:</b> {pnl_percent_of_margin:.2f}%\n"
                f"<b>Причина:</b> {close_reason}\n\n"
                
                f"<b>⚖️ РИСК-МЕНЕДЖМЕНТ</b>\n"
                f"<b>Риск (при SL):</b> {risk_amount:.2f} USDT\n"
                f"<b>Потенциальная прибыль (при TP):</b> {potential_profit:.2f} USDT\n"
            )
            
            # Добавляем информацию о балансе
            try:
                from services.statistics import StatisticsManager
                stats = StatisticsManager(None, user_id)
                balance_info = await stats.get_balance_info(is_demo=is_demo)
                if balance_info:
                    new_balance = balance_info.get('total', 0)
                    message_text += f"\n<b>💵 Новый баланс:</b> {new_balance:.2f} USDT\n"
            except:
                pass
            
            # Отправляем уведомление
            await self.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode='HTML'
            )
            
            # Логируем в БД если используется
            try:
                from data.database import get_database
                db = get_database()
                # Находим trade_id для логирования
                open_trades = db.get_open_trades(user_id, symbol=symbol)
                trade_id = open_trades[0].get('trade_id') if open_trades else None
                db.log_notification(
                    user_id,
                    'trade_close',
                    message_text,
                    trade_id
                )
            except:
                pass
                
        except Exception as e:
            print(f"[Авто-торговля] ⚠️ Ошибка отправки уведомления о закрытии: {e}")
            traceback.print_exc()
