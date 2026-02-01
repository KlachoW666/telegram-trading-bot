from typing import Dict, List, Optional, Any
from services.bingx_api import BingXAPI
from services.market_analysis import MarketAnalyzer
from config.settings import DEFAULT_LEVERAGE
import math


class TradingEngine:
    """
    Движок автоматической торговли
    
    Согласно proverka.txt:
    - Использует анализ стакана с глубиной до 50-100 уровней
    - Мониторит depth imbalance: (sum bids / sum asks) >1.2 — buy signal
    - Для 5m скальпа использует готовые свечи (можно улучшить агрегацией из 1m stream)
    """
    
    def __init__(self, api: BingXAPI, is_demo: bool = False):
        self.api = api
        self.is_demo = is_demo
        self.analyzer = MarketAnalyzer()
        self.active_strategies = []

    async def calculate_scalping_sl_tp(
        self,
        symbol: str,
        entry: float,
        direction: str,
        leverage: int,
        timeframe: str = "5m",
        candles_limit: int = 1440,
    ) -> Dict[str, Any]:
        """
        Скальперский SL/TP от волатильности (ATR по свечам) + минимальные дистанции.

        Важно: это не "анализ всей крипты". Это калибровка под КАЖДУЮ пару отдельно
        по последним свечам (в пределах лимита API).
        """
        if entry <= 0:
            return {"stop_loss": None, "take_profit": None, "meta": {"reason": "entry<=0"}}

        # BingX ограничивает limit (обычно <= 1440). Страхуемся.
        safe_limit = min(int(candles_limit), 1440)

        # Берём побольше свечей, чтобы ATR был адекватнее
        ohlcv = await self.api.get_ohlcv(symbol, timeframe, limit=safe_limit)
        if not ohlcv or len(ohlcv) < 50:
            return {"stop_loss": None, "take_profit": None, "meta": {"reason": "not_enough_ohlcv"}}

        highs = [float(x[2]) for x in ohlcv]
        lows = [float(x[3]) for x in ohlcv]
        closes = [float(x[4]) for x in ohlcv]

        # True Range
        tr: List[float] = []
        prev_close = closes[0]
        for h, l, c in zip(highs, lows, closes):
            tr.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
            prev_close = c

        # Улучшенный расчет ATR с использованием экспоненциального сглаживания
        period = 14
        if len(tr) < period + 1:
            return {"stop_loss": None, "take_profit": None, "meta": {"reason": "not_enough_tr"}}
        
        # Используем EMA для ATR (более чувствителен к последним изменениям)
        alpha = 2.0 / (period + 1)  # Коэффициент сглаживания для EMA
        atr_ema = tr[0]
        for tr_val in tr[1:]:
            atr_ema = alpha * tr_val + (1 - alpha) * atr_ema
        
        # Также рассчитываем простой ATR для сравнения
        atr_sma = sum(tr[-period:]) / period
        
        # Используем среднее между EMA и SMA для более стабильного результата
        atr = (atr_ema + atr_sma) / 2
        atr_pct = (atr / entry) * 100 if entry > 0 else 0
        
        # Анализ волатильности за разные периоды для адаптации
        recent_atr = sum(tr[-7:]) / 7 if len(tr) >= 7 else atr  # Последние 7 свечей
        long_atr = sum(tr[-period:]) / period  # Полный период
        
        # Коэффициент волатильности (если недавняя волатильность выше - увеличиваем SL/TP)
        volatility_ratio = recent_atr / long_atr if long_atr > 0 else 1.0
        volatility_ratio = max(0.8, min(1.5, volatility_ratio))  # Ограничиваем диапазон
        
        # Адаптивные минимальные пороги в зависимости от волатильности
        base_min_sl_pct = 0.30
        base_min_tp_pct = 0.55
        
        # Для высоковолатильных пар увеличиваем минимальные пороги
        if atr_pct > 1.5:
            min_sl_pct = base_min_sl_pct * 1.3
            min_tp_pct = base_min_tp_pct * 1.3
        elif atr_pct < 0.5:
            min_sl_pct = base_min_sl_pct * 0.9
            min_tp_pct = base_min_tp_pct * 0.9
        else:
            min_sl_pct = base_min_sl_pct
            min_tp_pct = base_min_tp_pct

        # Привязка к волатильности с учетом коэффициента
        # УВЕЛИЧЕНА дистанция SL на основе анализа (слишком много закрытий по SL)
        # Используем 1.2x вместо 0.85x для большей дистанции от входа
        sl_pct = max(min_sl_pct, atr_pct * 1.2 * volatility_ratio)  # Было 0.85, стало 1.2
        tp_pct = max(min_tp_pct, atr_pct * 1.5 * volatility_ratio)
        
        # Оптимизация соотношения риск/прибыль (целевое соотношение 1:3.0 для большей прибыли)
        # Увеличиваем целевое соотношение для более прибыльных сделок
        target_rr = 3.0  # Увеличено с 2.5 до 3.0 для большей прибыли
        if tp_pct / sl_pct < target_rr:
            tp_pct = sl_pct * target_rr
        
        # Дополнительная оптимизация: если волатильность позволяет, увеличиваем TP
        # Для высоковолатильных пар можем позволить больший TP
        if atr_pct > 1.0 and tp_pct < 5.0:
            # Для волатильных пар увеличиваем TP до 5% если позволяет волатильность
            max_tp_for_volatile = min(atr_pct * 2.0, 5.0)
            if tp_pct < max_tp_for_volatile:
                tp_pct = max_tp_for_volatile
                # Пересчитываем для сохранения соотношения
                if tp_pct / sl_pct > target_rr * 1.2:  # Если соотношение стало слишком большим
                    sl_pct = tp_pct / target_rr  # Корректируем SL

        # Доп. защита: слишком большие значения тоже режем (скальпинг)
        # Но учитываем волатильность - для волатильных пар разрешаем больше
        max_sl_pct = 2.5 if atr_pct > 1.0 else 2.0
        max_tp_pct = 5.0 if atr_pct > 1.0 else 4.0
        
        sl_pct = min(sl_pct, max_sl_pct)
        tp_pct = min(tp_pct, max_tp_pct)

        is_long = direction == "long"
        if is_long:
            stop_loss = entry * (1 - sl_pct / 100)
            take_profit = entry * (1 + tp_pct / 100)
        else:
            stop_loss = entry * (1 + sl_pct / 100)
            take_profit = entry * (1 - tp_pct / 100)

        # Гарантия корректного направления (на всякий случай)
        if is_long and not (stop_loss < entry < take_profit):
            stop_loss = entry * (1 - sl_pct / 100)
            take_profit = entry * (1 + tp_pct / 100)
        if (not is_long) and not (take_profit < entry < stop_loss):
            stop_loss = entry * (1 + sl_pct / 100)
            take_profit = entry * (1 - tp_pct / 100)

        # Рассчитываем риск-ривард соотношение
        risk_reward_ratio = tp_pct / sl_pct if sl_pct > 0 else 0
        
        # Рассчитываем вероятность достижения TP на основе исторических данных
        # Анализируем, как часто цена достигала TP до SL за последние свечи
        tp_hit_rate = None
        if len(ohlcv) >= 20:
            tp_hits = 0
            sl_hits = 0
            for i in range(len(ohlcv) - 20, len(ohlcv) - 1):
                candle = ohlcv[i]
                candle_high = float(candle[2])
                candle_low = float(candle[3])
                candle_close = float(candle[4])
                
                # Проверяем для long позиции
                if is_long:
                    # Проверяем, достигли ли TP (цена поднялась выше TP)
                    if candle_high >= take_profit:
                        tp_hits += 1
                    # Проверяем, достигли ли SL (цена упала ниже SL)
                    elif candle_low <= stop_loss:
                        sl_hits += 1
                else:  # short
                    if candle_low <= take_profit:
                        tp_hits += 1
                    elif candle_high >= stop_loss:
                        sl_hits += 1
            
            total_checks = tp_hits + sl_hits
            if total_checks > 0:
                tp_hit_rate = (tp_hits / total_checks) * 100
        
        return {
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "meta": {
                "atr": round(atr, 6),
                "atr_pct": round(atr_pct, 3),
                "atr_ema": round(atr_ema, 6),
                "atr_sma": round(atr_sma, 6),
                "volatility_ratio": round(volatility_ratio, 3),
                "sl_pct": round(sl_pct, 3),
                "tp_pct": round(tp_pct, 3),
                "risk_reward_ratio": round(risk_reward_ratio, 2),
                "tp_hit_rate": round(tp_hit_rate, 2) if tp_hit_rate is not None else None,
                "timeframe": timeframe,
                "candles_used": len(ohlcv),
                "candles_limit": safe_limit,
                "leverage": leverage,
            },
        }
    
    async def analyze_and_trade(self, symbol: str, timeframe: str = '5m') -> Dict[str, Any]:
        """
        Анализирует рынок и принимает решение о торговле
        
        Использует двухэтапный анализ:
        1. HTF (1H/4H) - поиск зон (IMB, FVG, STB, пулы ликвидности)
        2. LTF (5m) - подтверждение сигнала на младшем таймфрейме
        
        Returns:
            Результат анализа и решение
        """
        try:
            # Получаем данные для LTF (5m) - основной таймфрейм
            ohlcv_ltf = await self.api.get_ohlcv(symbol, timeframe, limit=300)
            # Согласно proverka.txt: для перпетульного API рекомендуется глубина до 100 уровней
            # Используем 50 для баланса между точностью и производительностью
            orderbook = await self.api.get_order_book(symbol, limit=50)
            ticker = await self.api.get_ticker(symbol)
            
            # Получаем данные для HTF (1H) - для поиска зон
            ohlcv_htf = await self.api.get_ohlcv(symbol, '1h', limit=200)
            
            # Получаем данные для 4H таймфрейма - для проверки тренда (улучшение на основе анализа)
            ohlcv_4h = await self.api.get_ohlcv(symbol, '4h', limit=100)
            
            # Анализ LTF (основной)
            analysis_ltf = self.analyzer.analyze_market(ohlcv_ltf, orderbook)
            
            # Анализ HTF (зоны)
            analysis_htf = self.analyzer.advanced_analyzer.comprehensive_analysis(ohlcv_htf, orderbook)
            
            # Анализ тренда на 4H (для фильтрации сигналов)
            trend_4h = self._check_trend_4h(ohlcv_4h) if ohlcv_4h and len(ohlcv_4h) >= 20 else None
            
            # Объединяем анализы
            analysis = analysis_ltf
            analysis['htf_zones'] = {
                'imbalances': analysis_htf.get('imbalances', []),
                'fvgs': analysis_htf.get('fvgs', []),
                'stb_zones': analysis_htf.get('stb_zones', []),
                'liquidity_pools': analysis_htf.get('liquidity_pools', {})
            }
            
            # Проверяем правила отмены сигналов
            analysis = self._check_signal_cancellation(analysis, ohlcv_ltf, orderbook)
            
            # Проверяем, не был ли сигнал отменен
            cancellation_reason = analysis.get('cancellation_reason')
            if cancellation_reason:
                return {
                    'analysis': analysis,
                    'decision': {
                        'action': 'skip',
                        'reason': f'Сигнал отменен: {cancellation_reason}'
                    },
                    'symbol': symbol,
                    'current_price': ticker['last']
                }
            
            # Фильтр по тренду на 4H (улучшение на основе анализа)
            if trend_4h:
                final_signal = analysis.get('final_signal', 'neutral')
                # Если сигнал противоречит тренду на 4H - снижаем вероятность или отменяем
                if final_signal in ['long', 'strong_long'] and trend_4h == 'bearish':
                    # Бычий сигнал против медвежьего тренда - снижаем вероятность
                    current_prob = analysis.get('probability', 0)
                    analysis['probability'] = max(0, current_prob - 15)
                    if analysis['probability'] < 50:
                        analysis['final_signal'] = 'neutral'
                        analysis['cancellation_reason'] = 'Сигнал противоречит тренду на 4H (медвежий)'
                elif final_signal in ['short', 'strong_short'] and trend_4h == 'bullish':
                    # Медвежий сигнал против бычьего тренда - снижаем вероятность
                    current_prob = analysis.get('probability', 0)
                    analysis['probability'] = max(0, current_prob - 15)
                    if analysis['probability'] < 50:
                        analysis['final_signal'] = 'neutral'
                        analysis['cancellation_reason'] = 'Сигнал противоречит тренду на 4H (бычий)'
            
            # Принимаем решение
            decision = self._make_decision(analysis)
            
            return {
                'analysis': analysis,
                'decision': decision,
                'symbol': symbol,
                'current_price': ticker['last']
            }
        except Exception as e:
            return {
                'error': str(e),
                'decision': {'action': 'skip'}
            }

    async def scan_market(self, pairs: List[str], timeframe: str = "5m", top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Мини-сканер "как в pycryptobot": прогоняем пары и ранжируем по probability/силе сигнала.
        Возвращает топ-N результатов.
        """
        results: List[Dict[str, Any]] = []
        for sym in pairs:
            try:
                r = await self.analyze_and_trade(sym, timeframe=timeframe)
                analysis = r.get("analysis") or {}
                final_signal = analysis.get("final_signal", "neutral")
                probability = float(analysis.get("probability", 0) or 0)
                if final_signal != "neutral" and probability > 0:
                    results.append(
                        {
                            "symbol": sym,
                            "final_signal": final_signal,
                            "probability": probability,
                            "confirmations": (analysis.get("confirmations") or {}).get("count", 0),
                            "current_price": analysis.get("current_price"),
                        }
                    )
            except Exception:
                continue

        results.sort(key=lambda x: (x.get("probability", 0), x.get("confirmations", 0)), reverse=True)
        return results[: max(1, int(top_n))]
    
    def _check_signal_cancellation(self, analysis: Dict[str, Any], ohlcv: List[List], orderbook: Dict) -> Dict[str, Any]:
        """
        Проверяет правила отмены сигналов согласно analiz.txt:
        - Снятие пула ликвидности
        - Пробой зоны без реакции
        """
        final_signal = analysis.get('final_signal', 'neutral')
        
        if final_signal == 'neutral':
            return analysis
        
        # Получаем данные для проверки
        advanced = analysis.get('advanced_analysis', {})
        liquidity_pools = advanced.get('liquidity_pools', {})
        htf_zones = analysis.get('htf_zones', {})
        current_price = ohlcv[-1][4] if ohlcv else 0
        
        # Правило 1: Снятие пула ликвидности
        # ПУЛЫ ЛИКВИДНОСТИ - это исторические уровни из Volume Profile, а не текущие ордера
        # Проверяем только если пул был очень близко к текущей цене и исчез
        # (это может означать, что ликвидность была собрана)
        if final_signal in ['long', 'strong_long']:
            target_pool = liquidity_pools.get('nearest_pool_above')
            if target_pool and current_price > 0:
                # Проверяем только если пул был очень близко (в пределах 0.5% от цены)
                distance_to_pool = abs(target_pool - current_price) / current_price * 100
                if distance_to_pool < 0.5:  # Пул был очень близко
                    asks = orderbook.get('asks', [])
                    # Проверяем наличие крупных ордеров в районе пула (в пределах 0.2%)
                    pool_has_liquidity = any(
                        abs(ask[0] - target_pool) < target_pool * 0.002 and ask[1] > 0.1
                        for ask in asks[:20]  # Проверяем больше уровней
                    )
                    if not pool_has_liquidity:
                        # Пул был близко, но ликвидность исчезла - отменяем
                        analysis['final_signal'] = 'neutral'
                        analysis['probability'] = 0
                        analysis['cancellation_reason'] = f'Пул ликвидности снят (был на {target_pool:.2f})'
                        return analysis
        
        if final_signal in ['short', 'strong_short']:
            target_pool = liquidity_pools.get('nearest_pool_below')
            if target_pool and current_price > 0:
                distance_to_pool = abs(target_pool - current_price) / current_price * 100
                if distance_to_pool < 0.5:  # Пул был очень близко
                    bids = orderbook.get('bids', [])
                    pool_has_liquidity = any(
                        abs(bid[0] - target_pool) < target_pool * 0.002 and bid[1] > 0.1
                        for bid in bids[:20]
                    )
                    if not pool_has_liquidity:
                        analysis['final_signal'] = 'neutral'
                        analysis['probability'] = 0
                        analysis['cancellation_reason'] = f'Пул ликвидности снят (был на {target_pool:.2f})'
                        return analysis
        
        # Правило 2: Пробой зоны без реакции
        # Если цена пробрала IMB/FVG без подтверждения - отменяем
        fvgs = htf_zones.get('fvgs', [])
        imbalances = htf_zones.get('imbalances', [])
        
        # Проверяем последние свечи на пробой без реакции
        if len(ohlcv) >= 3:
            last_3_candles = ohlcv[-3:]
            for candle in last_3_candles:
                candle_high = candle[2]
                candle_low = candle[3]
                
                # Проверяем FVG
                for fvg in fvgs[-2:]:
                    if fvg['type'] == 'bullish_fvg':
                        # Если цена пробрала FVG вниз без реакции - отменяем лонг
                        if final_signal in ['long', 'strong_long'] and candle_low < fvg['zone_start']:
                            # Проверяем, была ли реакция (свеча с длинной нижней тенью)
                            has_reaction = (candle[1] - candle[3]) > (candle[1] - candle[4]) * 2  # Длинная нижняя тень
                            if not has_reaction:
                                analysis['final_signal'] = 'neutral'
                                analysis['probability'] = 0
                                analysis['cancellation_reason'] = f"Пробой FVG без реакции на {fvg['mid_point']:.2f}"
                                return analysis
                    
                    elif fvg['type'] == 'bearish_fvg':
                        # Если цена пробрала FVG вверх без реакции - отменяем шорт
                        if final_signal in ['short', 'strong_short'] and candle_high > fvg['zone_end']:
                            has_reaction = (candle[2] - candle[1]) > (candle[1] - candle[4]) * 2  # Длинная верхняя тень
                            if not has_reaction:
                                analysis['final_signal'] = 'neutral'
                                analysis['probability'] = 0
                                analysis['cancellation_reason'] = f"Пробой FVG без реакции на {fvg['mid_point']:.2f}"
                                return analysis
        
        return analysis
    
    def _check_trend_4h(self, ohlcv_4h: List[List]) -> Optional[str]:
        """
        Определяет тренд на 4H таймфрейме для фильтрации сигналов
        
        Returns:
            'bullish', 'bearish', или None если неопределенно
        """
        if not ohlcv_4h or len(ohlcv_4h) < 20:
            return None
        
        try:
            # Берем последние 20 свечей для определения тренда
            closes = [float(c[4]) for c in ohlcv_4h[-20:]]
            
            # Простой метод: сравнение первой и последней цены + EMA
            first_price = closes[0]
            last_price = closes[-1]
            
            # Рассчитываем простую EMA для сглаживания
            ema_period = 9
            if len(closes) >= ema_period:
                # Простая EMA
                ema = sum(closes[-ema_period:]) / ema_period
                
                # Определяем тренд
                price_change = (last_price - first_price) / first_price * 100
                ema_position = (last_price - ema) / ema * 100
                
                # Если цена выше EMA и растет - бычий тренд
                if price_change > 2 and ema_position > 1:
                    return 'bullish'
                # Если цена ниже EMA и падает - медвежий тренд
                elif price_change < -2 and ema_position < -1:
                    return 'bearish'
                # Иначе - флэт или неопределенно
                else:
                    return None
            else:
                # Если недостаточно данных, используем простое сравнение
                if (last_price - first_price) / first_price > 0.03:  # 3% рост
                    return 'bullish'
                elif (last_price - first_price) / first_price < -0.03:  # 3% падение
                    return 'bearish'
                return None
        except Exception as e:
            print(f"[TradingEngine] ⚠️ Ошибка определения тренда 4H: {e}")
            return None
    
    def _make_decision(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Принимает решение о торговле на основе анализа с улучшенной фильтрацией"""
        final_signal = analysis.get('final_signal', 'neutral')
        probability = analysis.get('probability', 0)
        
        # Проверяем количество подтверждений (требование из tt.txt: 3+ подтверждений)
        confirmations = analysis.get('confirmations', {})
        confirmation_count = confirmations.get('count', 0)
        min_confirmations = confirmations.get('required', 3)
        
        # Расширенная логика принятия решений с адаптивными порогами
        # Базовые пороги зависят от качества сигналов
        # УВЕЛИЧЕНО на основе анализа: слишком много закрытий по SL
        base_min_probability_strong = 55  # Для strong_long/strong_short (было 45)
        base_min_probability_normal = 60  # Для long/short (было 50)
        
        # Проверяем расширенный анализ для дополнительных сигналов
        advanced_analysis = analysis.get('advanced_analysis', {})
        signals = advanced_analysis.get('signals', [])
        
        # Подсчитываем дополнительные сигналы и их силу
        long_signals_count = len([s for s in signals if s.get('type') == 'long'])
        short_signals_count = len([s for s in signals if s.get('type') == 'short'])
        long_signals_strength = sum([s.get('strength', 1) for s in signals if s.get('type') == 'long'])
        short_signals_strength = sum([s.get('strength', 1) for s in signals if s.get('type') == 'short'])
        
        # Order Flow сигнал
        order_flow = advanced_analysis.get('order_flow', {})
        of_signal = order_flow.get('signal', 'neutral')
        of_strength = order_flow.get('strength', 1.0)
        
        # Свипы ликвидности
        sweeps = advanced_analysis.get('liquidity_sweeps', [])
        has_liquidity_sweep = len(sweeps) > 0
        
        # Дивергенция
        has_divergence = any('divergence' in s for s in analysis.get('signals', []))
        
        # Анализ структуры (BOS/CHOCH)
        structure = advanced_analysis.get('structure', {})
        has_bos = structure.get('bos') is not None
        has_choch = structure.get('choch') is not None
        
        # Адаптивные пороги на основе качества сигналов
        quality_bonus = 0
        
        # Бонусы за качественные сигналы
        if has_liquidity_sweep:
            quality_bonus += 8  # Свип ликвидности - сильный сигнал
        if has_divergence:
            quality_bonus += 10  # Дивергенция - очень сильный сигнал
        if has_bos:
            quality_bonus += 6  # BOS - прорыв структуры
        if has_choch:
            quality_bonus += 5  # CHOCH - смена характера
        
        # Бонус за силу Order Flow
        if of_strength > 2.0:
            quality_bonus += 5
        
        # Бонус за количество сигналов
        total_signals = long_signals_count + short_signals_count
        if total_signals >= 3:
            quality_bonus += 7
        elif total_signals >= 2:
            quality_bonus += 4
        
        # Штраф за недостаточное количество подтверждений
        confirmation_penalty = max(0, (min_confirmations - confirmation_count) * 8)
        
        # Финальные пороги
        min_probability_strong = base_min_probability_strong - quality_bonus + confirmation_penalty
        min_probability_normal = base_min_probability_normal - quality_bonus + confirmation_penalty
        
        # Минимальные пороги не должны быть слишком низкими
        min_probability_strong = max(35, min_probability_strong)
        min_probability_normal = max(40, min_probability_normal)
        
        # Если подтверждений недостаточно - пропускаем слабые сигналы
        if confirmation_count < min_confirmations and probability < min_probability_normal:
            return {
                'action': 'skip',
                'reason': f'Недостаточно подтверждений ({confirmation_count}/{min_confirmations}) для слабого сигнала (вероятность {probability}%)'
            }
        
        # Дополнительные проверки для фильтрации ложных сигналов
        indicators = analysis.get('indicators', {})
        
        # Проверка конфликта индикаторов
        rsi_signal = indicators.get('rsi', {}).get('signal', 'neutral')
        macd_signal = indicators.get('macd', {}).get('signal_type', 'neutral') if indicators.get('macd') else 'neutral'
        
        # Если основные индикаторы конфликтуют с сигналом - снижаем вероятность
        signal_conflict = False
        if final_signal in ['long', 'strong_long']:
            if rsi_signal == 'overbought' or macd_signal == 'bearish':
                signal_conflict = True
                probability = max(probability * 0.7, 30)  # Снижаем вероятность на 30%
        elif final_signal in ['short', 'strong_short']:
            if rsi_signal == 'oversold' or macd_signal == 'bullish':
                signal_conflict = True
                probability = max(probability * 0.7, 30)
        
        # Проверка объема (низкий объем = слабый сигнал)
        volume_ratio = indicators.get('volume', {}).get('ratio', 1.0)
        if volume_ratio < 0.7:  # Объем ниже среднего
            probability = max(probability * 0.85, 25)  # Снижаем вероятность
        
        # Принимаем решение с улучшенной логикой
        if final_signal == 'strong_long' and probability >= min_probability_strong:
            reason_parts = [f'Сильный бычий сигнал (вероятность {probability}%)']
            if long_signals_count > 0:
                reason_parts.append(f'сигналов: {long_signals_count}')
            if has_divergence:
                reason_parts.append('дивергенция')
            if has_liquidity_sweep:
                reason_parts.append('свип ликвидности')
            
            return {
                'action': 'open_long',
                'reason': ', '.join(reason_parts),
                'recommendation': analysis.get('recommendation'),
                'quality_score': quality_bonus,
                'signal_strength': long_signals_strength
            }
        elif final_signal == 'strong_short' and probability >= min_probability_strong:
            reason_parts = [f'Сильный медвежий сигнал (вероятность {probability}%)']
            if short_signals_count > 0:
                reason_parts.append(f'сигналов: {short_signals_count}')
            if has_divergence:
                reason_parts.append('дивергенция')
            if has_liquidity_sweep:
                reason_parts.append('свип ликвидности')
            
            return {
                'action': 'open_short',
                'reason': ', '.join(reason_parts),
                'recommendation': analysis.get('recommendation'),
                'quality_score': quality_bonus,
                'signal_strength': short_signals_strength
            }
        elif final_signal in ['long', 'short'] and probability >= min_probability_normal:
            signal_count = long_signals_count if final_signal == 'long' else short_signals_count
            signal_strength_val = long_signals_strength if final_signal == 'long' else short_signals_strength
            
            reason_parts = [f'Сигнал {final_signal} (вероятность {probability}%)']
            if signal_count > 0:
                reason_parts.append(f'сигналов: {signal_count}')
            if signal_conflict:
                reason_parts.append('⚠️ конфликт индикаторов')
            
            return {
                'action': f'open_{final_signal}',
                'reason': ', '.join(reason_parts),
                'recommendation': analysis.get('recommendation'),
                'quality_score': quality_bonus,
                'signal_strength': signal_strength_val
            }
        else:
            # Дополнительная проверка: если Order Flow очень сильный, можем открыть при меньшей вероятности
            if of_signal == 'long' and of_strength >= 2.5 and probability >= 40:
                return {
                    'action': 'open_long',
                    'reason': f'Сильный Order Flow лонг (сила: {of_strength:.1f}, вероятность {probability}%)',
                    'recommendation': analysis.get('recommendation'),
                    'quality_score': quality_bonus
                }
            elif of_signal == 'short' and of_strength >= 2.5 and probability >= 40:
                return {
                    'action': 'open_short',
                    'reason': f'Сильный Order Flow шорт (сила: {of_strength:.1f}, вероятность {probability}%)',
                    'recommendation': analysis.get('recommendation'),
                    'quality_score': quality_bonus
                }
            
            # Если есть очень качественные сигналы (дивергенция + свип), можем открыть при меньшей вероятности
            if (has_divergence and has_liquidity_sweep) and probability >= 45:
                return {
                    'action': f'open_{final_signal}' if final_signal != 'neutral' else 'skip',
                    'reason': f'Высококачественный сигнал (дивергенция + свип, вероятность {probability}%)',
                    'recommendation': analysis.get('recommendation'),
                    'quality_score': quality_bonus
                }
            
            return {
                'action': 'skip',
                'reason': f'Недостаточная вероятность ({probability}%) или нейтральный сигнал. Пороги: strong={min_probability_strong}%, normal={min_probability_normal}%'
            }
    
    async def execute_trade(self, symbol: str, direction: str, amount: float, 
                           stop_loss: Optional[float] = None, 
                           take_profit: Optional[float] = None,
                           leverage: int = DEFAULT_LEVERAGE) -> Dict[str, Any]:
        """
        Выполняет сделку
        
        Args:
            symbol: Торговая пара
            direction: 'long' или 'short'
            amount: Объём
            stop_loss: Цена стоп-лосса
            take_profit: Цена тейк-профита
            leverage: Плечо
        """
        if self.is_demo:
            # В демо-режиме получаем текущую цену для правильного расчета PnL
            try:
                ticker = await self.api.get_ticker(symbol)
                current_price = float(ticker.get('last', 0))
                # Если цена не получена, используем среднюю между bid и ask
                if current_price == 0:
                    bid = float(ticker.get('bid', 0))
                    ask = float(ticker.get('ask', 0))
                    if bid > 0 and ask > 0:
                        current_price = (bid + ask) / 2
                    elif bid > 0:
                        current_price = bid
                    elif ask > 0:
                        current_price = ask
            except Exception as e:
                print(f"[TradingEngine] ⚠️ Не удалось получить цену для демо-сделки: {e}")
                current_price = 0
            
            # В демо-режиме просто логируем
            return {
                'success': True,
                'demo': True,
                'symbol': symbol,
                'direction': direction,
                'amount': amount,
                'price': current_price,  # Важно: возвращаем цену для правильного расчета PnL
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'message': 'Демо-сделка выполнена (виртуально)'
            }
        
        try:
            # Устанавливаем плечо
            await self.api.set_leverage(symbol, leverage)
            
            # Открываем позицию
            side = 'buy' if direction == 'long' else 'sell'
            order = await self.api.create_market_order(symbol, side, amount)
            entry_price = order.get('price') or order.get('average', 0)
            
            stop_loss_order_id = None
            take_profit_order_id = None
            
            # Устанавливаем стоп-лосс и тейк-профит, если указаны
            if stop_loss:
                try:
                    # Для long позиции стоп-лосс - sell ордер
                    # Для short позиции стоп-лосс - buy ордер
                    sl_side = 'sell' if direction == 'long' else 'buy'
                    stop_order = await self.api.create_stop_loss_order(
                        symbol, sl_side, amount, stop_loss
                    )
                    stop_loss_order_id = stop_order.get('id')
                except Exception as sl_error:
                    print(f"[TradingEngine] ⚠️ Не удалось установить стоп-лосс: {sl_error}")
                    # Продолжаем без стоп-лосса
            
            if take_profit:
                try:
                    # Для long позиции тейк-профит - sell ордер
                    # Для short позиции тейк-профит - buy ордер
                    tp_side = 'sell' if direction == 'long' else 'buy'
                    tp_order = await self.api.create_take_profit_order(
                        symbol, tp_side, amount, take_profit
                    )
                    take_profit_order_id = tp_order.get('id')
                except Exception as tp_error:
                    print(f"[TradingEngine] ⚠️ Не удалось установить тейк-профит: {tp_error}")
                    # Продолжаем без тейк-профита
            
            return {
                'success': True,
                'order_id': order.get('id'),
                'symbol': symbol,
                'direction': direction,
                'amount': amount,
                'price': entry_price,
                'stop_loss': stop_loss,
                'stop_loss_order_id': stop_loss_order_id,
                'take_profit': take_profit,
                'take_profit_order_id': take_profit_order_id
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def calculate_position_size(self, balance: float, risk_percent: float, 
                                     entry_price: float, stop_loss: float, 
                                     leverage: int = 1) -> float:
        """
        Рассчитывает размер позиции на основе риск-менеджмента
        
        Улучшенная версия: учитывает плечо правильно и позволяет большие позиции
        при сильных сигналах.
        
        Args:
            balance: Баланс
            risk_percent: % риска от баланса (может быть увеличен через scale_factor)
            entry_price: Цена входа
            stop_loss: Цена стоп-лосса
            leverage: Плечо (учитывается для расчёта)
        
        Returns:
            Размер позиции
        """
        if balance <= 0 or entry_price <= 0:
            return 0
        
        # Сумма риска в USDT (это максимальный убыток, который мы готовы принять)
        risk_amount = balance * (risk_percent / 100)
        
        # Разница в цене между входом и стоп-лоссом
        price_diff = abs(entry_price - stop_loss)
        
        if price_diff == 0:
            return 0
        
        # Размер позиции БЕЗ учета плеча (плечо влияет только на маржу, не на риск)
        # Риск рассчитывается от номинала позиции, а не от маржи
        position_size = risk_amount / price_diff
        
        # Номинальный размер позиции
        position_value = position_size * entry_price
        
        # Ограничиваем максимальный размер позиции
        # Увеличено с 10% до 25% от баланса для более агрессивной торговли
        # при сильных сигналах (но это безопасно, т.к. риск контролируется через SL)
        max_position_value = balance * 0.25 * leverage  # До 25% от баланса с учетом плеча
        max_position_size = max_position_value / entry_price
        
        position_size = min(position_size, max_position_size)
        
        return round(position_size, 8)
