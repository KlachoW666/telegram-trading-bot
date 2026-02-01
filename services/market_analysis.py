import pandas as pd
import pandas_ta as ta
from typing import Dict, List, Any
from services.candle_analysis import CandleAnalyzer
from services.advanced_analysis import AdvancedMarketAnalyzer


class MarketAnalyzer:
    """Класс для комплексного анализа рынка"""
    
    def __init__(self):
        self.candle_analyzer = CandleAnalyzer()
        self.advanced_analyzer = AdvancedMarketAnalyzer()
    
    def calculate_indicators(self, ohlcv: List[List]) -> Dict[str, Any]:
        """
        Рассчитывает технические индикаторы
        
        Args:
            ohlcv: Список свечей [timestamp, open, high, low, close, volume]
        
        Returns:
            Словарь с индикаторами
        """
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Для корректной работы некоторых индикаторов pandas_ta (например, VWAP)
        # требуется упорядоченный DatetimeIndex.
        try:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
            df = df.set_index('timestamp').sort_index()
        except Exception:
            # Если что-то пошло не так, продолжаем с обычным индексом
            pass
        
        indicators = {}
        
        # RSI
        rsi = ta.rsi(df['close'], length=14)
        rsi_values = rsi.tolist() if not rsi.empty else []
        rsi_value = float(rsi.iloc[-1]) if not rsi.empty else None
        
        indicators['rsi'] = {
            'value': rsi_value,
            'signal': self._get_rsi_signal(rsi_value),
            'values': rsi_values[-20:] if len(rsi_values) >= 20 else rsi_values  # Для дивергенции
        }
        
        # MACD
        macd = ta.macd(df['close'])
        if macd is not None and not macd.empty:
            indicators['macd'] = {
                'macd': float(macd['MACD_12_26_9'].iloc[-1]),
                'signal': float(macd['MACDs_12_26_9'].iloc[-1]),
                'histogram': float(macd['MACDh_12_26_9'].iloc[-1]),
                'signal_type': 'bullish' if macd['MACDh_12_26_9'].iloc[-1] > 0 else 'bearish'
            }
        else:
            indicators['macd'] = None
        
        # EMA
        ema_9 = ta.ema(df['close'], length=9)
        ema_21 = ta.ema(df['close'], length=21)
        ema_50 = ta.ema(df['close'], length=50)
        ema_200 = ta.ema(df['close'], length=200)
        
        indicators['ema'] = {
            'ema_9': float(ema_9.iloc[-1]) if not ema_9.empty else None,
            'ema_21': float(ema_21.iloc[-1]) if not ema_21.empty else None,
            'ema_50': float(ema_50.iloc[-1]) if not ema_50.empty else None,
            'ema_200': float(ema_200.iloc[-1]) if not ema_200.empty else None,
            'trend': self._get_ema_trend(ema_9, ema_21, ema_50, ema_200, df['close'].iloc[-1])
        }
        
        # Bollinger Bands
        bb = ta.bbands(df['close'], length=20)
        if bb is not None and not bb.empty:
            try:
                # Проверяем, какие столбцы есть в DataFrame
                # pandas_ta может вернуть разные имена столбцов в зависимости от версии
                bb_columns = bb.columns.tolist()
                
                # Ищем столбцы для верхней, средней и нижней полос
                upper_col = None
                middle_col = None
                lower_col = None
                
                for col in bb_columns:
                    if 'BBU' in str(col) or 'upper' in str(col).lower():
                        upper_col = col
                    elif 'BBM' in str(col) or 'middle' in str(col).lower():
                        middle_col = col
                    elif 'BBL' in str(col) or 'lower' in str(col).lower():
                        lower_col = col
                
                # Если не нашли столбцы по стандартным именам, используем первые 3 столбца
                if not upper_col or not middle_col or not lower_col:
                    if len(bb_columns) >= 3:
                        upper_col = bb_columns[0]
                        middle_col = bb_columns[1]
                        lower_col = bb_columns[2]
                    else:
                        raise ValueError("Недостаточно столбцов в Bollinger Bands")
                
                indicators['bollinger'] = {
                    'upper': float(bb[upper_col].iloc[-1]),
                    'middle': float(bb[middle_col].iloc[-1]),
                    'lower': float(bb[lower_col].iloc[-1]),
                    'position': self._get_bb_position(df['close'].iloc[-1], bb.iloc[-1], upper_col, lower_col)
                }
            except (KeyError, IndexError, ValueError) as e:
                # Если не удалось получить данные Bollinger Bands, возвращаем None
                indicators['bollinger'] = None
        else:
            indicators['bollinger'] = None
        
        # Stochastic
        stoch = ta.stoch(df['high'], df['low'], df['close'])
        if stoch is not None and not stoch.empty:
            indicators['stochastic'] = {
                'k': float(stoch['STOCHk_14_3_3'].iloc[-1]),
                'd': float(stoch['STOCHd_14_3_3'].iloc[-1]),
                'signal': self._get_stoch_signal(stoch['STOCHk_14_3_3'].iloc[-1])
            }
        else:
            indicators['stochastic'] = None
        
        # Volume
        indicators['volume'] = {
            'current': float(df['volume'].iloc[-1]),
            'average': float(df['volume'].tail(20).mean()),
            'ratio': float(df['volume'].iloc[-1] / df['volume'].tail(20).mean()) if len(df) >= 20 else 1.0
        }

        # VWAP (из идей Crypto-Signal: VWAP/OBV/MFI/Ichimoku как базовый слой)
        try:
            vwap = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
            if vwap is not None and not vwap.empty:
                vwap_val = float(vwap.iloc[-1])
                price = float(df["close"].iloc[-1])
                indicators["vwap"] = {
                    "value": vwap_val,
                    "position": "above" if price > vwap_val else "below" if price < vwap_val else "at",
                }
            else:
                indicators["vwap"] = None
        except Exception:
            indicators["vwap"] = None

        # MFI
        try:
            mfi = ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=14)
            if mfi is not None and not mfi.empty:
                mfi_val = float(mfi.iloc[-1])
                indicators["mfi"] = {
                    "value": mfi_val,
                    "signal": "oversold" if mfi_val < 20 else "overbought" if mfi_val > 80 else "neutral",
                }
            else:
                indicators["mfi"] = None
        except Exception:
            indicators["mfi"] = None

        # OBV
        try:
            obv = ta.obv(df["close"], df["volume"])
            if obv is not None and not obv.empty:
                obv_tail = obv.tail(10)
                obv_val = float(obv.iloc[-1])
                # простой тренд OBV по наклону последних значений
                obv_trend = "up" if len(obv_tail) >= 2 and float(obv_tail.iloc[-1]) > float(obv_tail.iloc[0]) else "down"
                indicators["obv"] = {"value": obv_val, "trend": obv_trend}
            else:
                indicators["obv"] = None
        except Exception:
            indicators["obv"] = None

        # Ichimoku
        try:
            ichi = ta.ichimoku(df["high"], df["low"], df["close"])
            # pandas-ta возвращает tuple(DataFrame, DataFrame) или DataFrame (зависит от версии)
            ichi_df = None
            if isinstance(ichi, tuple) and len(ichi) > 0:
                ichi_df = ichi[0]
            elif hasattr(ichi, "columns"):
                ichi_df = ichi

            if ichi_df is not None and not ichi_df.empty:
                cols = {c.lower(): c for c in ichi_df.columns}
                tenkan_col = next((cols[k] for k in cols if "its" in k or "tenkan" in k), None)
                kijun_col = next((cols[k] for k in cols if "iks" in k or "kijun" in k), None)
                span_a_col = next((cols[k] for k in cols if "isa" in k or "spana" in k), None)
                span_b_col = next((cols[k] for k in cols if "isb" in k or "spanb" in k), None)

                tenkan = float(ichi_df[tenkan_col].iloc[-1]) if tenkan_col else None
                kijun = float(ichi_df[kijun_col].iloc[-1]) if kijun_col else None
                span_a = float(ichi_df[span_a_col].iloc[-1]) if span_a_col else None
                span_b = float(ichi_df[span_b_col].iloc[-1]) if span_b_col else None

                price = float(df["close"].iloc[-1])
                cloud_top = max([x for x in [span_a, span_b] if x is not None], default=None)
                cloud_bottom = min([x for x in [span_a, span_b] if x is not None], default=None)

                position = "unknown"
                if cloud_top is not None and cloud_bottom is not None:
                    if price > cloud_top:
                        position = "above_cloud"
                    elif price < cloud_bottom:
                        position = "below_cloud"
                    else:
                        position = "in_cloud"

                indicators["ichimoku"] = {
                    "tenkan": tenkan,
                    "kijun": kijun,
                    "span_a": span_a,
                    "span_b": span_b,
                    "position": position,
                }
            else:
                indicators["ichimoku"] = None
        except Exception:
            indicators["ichimoku"] = None
        
        return indicators
    
    def _get_rsi_signal(self, rsi_value: float) -> str:
        """Определяет сигнал RSI"""
        if rsi_value is None:
            return 'neutral'
        if rsi_value < 30:
            return 'oversold'  # Перепроданность
        elif rsi_value > 70:
            return 'overbought'  # Перекупленность
        else:
            return 'neutral'
    
    def _get_ema_trend(self, ema_9, ema_21, ema_50, ema_200, current_price: float) -> str:
        """Определяет тренд по EMA"""
        if ema_9.empty or ema_21.empty:
            return 'neutral'
        
        ema9_val = ema_9.iloc[-1]
        ema21_val = ema_21.iloc[-1]
        
        if current_price > ema9_val > ema21_val:
            return 'strong_bullish'
        elif current_price > ema9_val and ema9_val < ema21_val:
            return 'weak_bullish'
        elif current_price < ema9_val < ema21_val:
            return 'strong_bearish'
        elif current_price < ema9_val and ema9_val > ema21_val:
            return 'weak_bearish'
        else:
            return 'neutral'
    
    def _get_bb_position(self, price: float, bb_row: pd.Series, upper_col: str = None, lower_col: str = None) -> str:
        """Определяет позицию цены относительно Bollinger Bands"""
        try:
            # Если столбцы не указаны, пытаемся найти их автоматически
            if not upper_col or not lower_col:
                bb_columns = bb_row.index.tolist()
                for col in bb_columns:
                    if not upper_col and ('BBU' in str(col) or 'upper' in str(col).lower()):
                        upper_col = col
                    if not lower_col and ('BBL' in str(col) or 'lower' in str(col).lower()):
                        lower_col = col
                
                # Если не нашли, используем первые столбцы
                if not upper_col or not lower_col:
                    if len(bb_columns) >= 3:
                        upper_col = bb_columns[0]
                        lower_col = bb_columns[2]
                    elif len(bb_columns) >= 2:
                        upper_col = bb_columns[0]
                        lower_col = bb_columns[1]
            
            if upper_col and lower_col:
                upper_val = float(bb_row[upper_col])
                lower_val = float(bb_row[lower_col])
                
                if price > upper_val:
                    return 'above_upper'
                elif price < lower_val:
                    return 'below_lower'
                else:
                    return 'inside'
            else:
                return 'unknown'
        except (KeyError, IndexError, ValueError, TypeError) as e:
            # Если не удалось определить позицию, возвращаем unknown
            return 'unknown'
    
    def _get_stoch_signal(self, k_value: float) -> str:
        """Определяет сигнал Stochastic"""
        if k_value < 20:
            return 'oversold'
        elif k_value > 80:
            return 'overbought'
        else:
            return 'neutral'
    
    def analyze_market(self, ohlcv: List[List], orderbook: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Комплексный анализ рынка с расширенными техниками (IMB, FVG, STB, Order Flow, пулы ликвидности)
        
        Args:
            ohlcv: Список свечей
            orderbook: Стакан (опционально)
        
        Returns:
            Полный отчёт анализа
        """
        current_price = ohlcv[-1][4] if ohlcv else None
        
        # Базовый анализ свечей
        candle_analysis = self.candle_analyzer.analyze_candles(ohlcv)
        
        # Индикаторы
        indicators = self.calculate_indicators(ohlcv)
        
        # Расширенный анализ (IMB, FVG, STB, Order Flow, пулы ликвидности)
        advanced_analysis = self.advanced_analyzer.comprehensive_analysis(ohlcv, orderbook)
        
        # Анализ стакана (если есть)
        orderbook_analysis = None
        if orderbook:
            orderbook_analysis = self._analyze_orderbook(orderbook)
        
        # Формирование общего сигнала
        signals = []
        signal_strength = 0
        
        # Сигналы от свечей
        if candle_analysis.get('overall_signal') == 'bullish':
            signals.append('bullish_candle')
            signal_strength += 20
        elif candle_analysis.get('overall_signal') == 'bearish':
            signals.append('bearish_candle')
            signal_strength -= 20
        
        # Сигналы от RSI
        if indicators['rsi']['signal'] == 'oversold':
            signals.append('rsi_oversold')
            signal_strength += 15
        elif indicators['rsi']['signal'] == 'overbought':
            signals.append('rsi_overbought')
            signal_strength -= 15
        
        # Сигналы от MACD
        if indicators.get('macd') and indicators['macd']['signal_type'] == 'bullish':
            signals.append('macd_bullish')
            signal_strength += 15
        elif indicators.get('macd') and indicators['macd']['signal_type'] == 'bearish':
            signals.append('macd_bearish')
            signal_strength -= 15

        # Сигналы от VWAP
        vwap = indicators.get("vwap")
        if vwap and vwap.get("position") == "above":
            signals.append("vwap_above")
            signal_strength += 10
        elif vwap and vwap.get("position") == "below":
            signals.append("vwap_below")
            signal_strength -= 10

        # Сигналы от MFI
        mfi = indicators.get("mfi")
        if mfi and mfi.get("signal") == "oversold":
            signals.append("mfi_oversold")
            signal_strength += 10
        elif mfi and mfi.get("signal") == "overbought":
            signals.append("mfi_overbought")
            signal_strength -= 10

        # Сигналы от Ichimoku (положение относительно облака)
        ichi = indicators.get("ichimoku")
        if ichi and ichi.get("position") == "above_cloud":
            signals.append("ichimoku_above_cloud")
            signal_strength += 12
        elif ichi and ichi.get("position") == "below_cloud":
            signals.append("ichimoku_below_cloud")
            signal_strength -= 12
        
        # Сигналы от EMA
        ema_trend = indicators['ema']['trend']
        if 'bullish' in ema_trend:
            signals.append('ema_bullish')
            signal_strength += 10
        elif 'bearish' in ema_trend:
            signals.append('ema_bearish')
            signal_strength -= 10
        
        # Сигналы от расширенного анализа
        advanced_signals = advanced_analysis.get('signals', [])
        for adv_signal in advanced_signals:
            signal_type = adv_signal.get('type', 'neutral')
            signal_source = adv_signal.get('source', 'unknown')
            
            if signal_type == 'long':
                signals.append(f"{signal_source}_long")
                signal_strength += adv_signal.get('strength', 1) * 5
            elif signal_type == 'short':
                signals.append(f"{signal_source}_short")
                signal_strength -= adv_signal.get('strength', 1) * 5
        
        # Order Flow сигналы
        of_direction = advanced_analysis.get('order_flow', {}).get('direction', 'neutral')
        if of_direction == 'bullish':
            signals.append('order_flow_bullish')
            signal_strength += 15
        elif of_direction == 'bearish':
            signals.append('order_flow_bearish')
            signal_strength -= 15
        
        # Свипы ликвидности
        sweeps = advanced_analysis.get('liquidity_sweeps', [])
        if sweeps:
            for sweep in sweeps[-1:]:  # Последний свип
                if sweep.get('signal') == 'long':
                    signal_strength += 20
                elif sweep.get('signal') == 'short':
                    signal_strength -= 20
        
        # Дивергенция RSI/OF (согласно tt.txt и analiz.txt)
        rsi_values = indicators.get('rsi', {}).get('values', [])
        if rsi_values:
            divergence = self.advanced_analyzer.detect_divergence(ohlcv, rsi_values)
            if divergence.get('has_divergence'):
                div_signal = divergence.get('signal', 'neutral')
                if div_signal == 'long':
                    signals.append('divergence_bullish')
                    signal_strength += 25  # Дивергенция - сильный сигнал
                elif div_signal == 'short':
                    signals.append('divergence_bearish')
                    signal_strength -= 25
        
        # Подсчитываем количество подтверждений для требования "3+ подтверждений"
        confirmations = []
        # 1. Подтверждение от свечей
        if candle_analysis.get('overall_signal') in ['bullish', 'bearish']:
            confirmations.append('candle')
        # 2. Подтверждение от уровня (IMB/FVG/STB)
        has_level_confirmation = False
        fvgs = advanced_analysis.get('fvgs', [])
        imbalances = advanced_analysis.get('imbalances', [])
        stb_zones = advanced_analysis.get('stb_zones', [])
        if fvgs or imbalances or stb_zones:
            # Проверяем, находится ли цена рядом с зоной
            for fvg in fvgs[-2:]:
                if fvg.get('type') == 'bullish_fvg' and current_price:
                    zone_start = fvg.get('zone_start', 0)
                    zone_end = fvg.get('zone_end', 0)
                    if zone_start <= current_price <= zone_end * 1.01:
                        has_level_confirmation = True
                        break
                elif fvg.get('type') == 'bearish_fvg' and current_price:
                    zone_start = fvg.get('zone_start', 0)
                    zone_end = fvg.get('zone_end', 0)
                    if zone_end <= current_price <= zone_start * 1.01:
                        has_level_confirmation = True
                        break
        if has_level_confirmation:
            confirmations.append('level')
        # 3. Подтверждение от Order Flow
        of_signal = advanced_analysis.get('order_flow', {}).get('signal', 'neutral')
        if of_signal != 'neutral':
            confirmations.append('order_flow')
        # 4. Подтверждение от индикаторов (RSI/MACD)
        if indicators.get('rsi', {}).get('signal') in ['oversold', 'overbought']:
            confirmations.append('indicator')
        if indicators.get('macd', {}).get('signal_type') in ['bullish', 'bearish']:
            confirmations.append('indicator')
        
        confirmation_count = len(confirmations)
        
        # Определение финального сигнала с учётом требования "3+ подтверждений" (из tt.txt)
        # Для авто-режима требуем минимум 3 подтверждения для входа
        min_confirmations_required = 3
        
        # Улучшенный расчет вероятности с учетом множества факторов
        # Базовая вероятность от силы сигнала (НЕ снижаем signal_strength заранее)
        base_probability = min(abs(signal_strength) * 1.5, 70)  # Максимум 70% от силы сигнала
        
        # Бонус за количество подтверждений
        confirmation_bonus = min(confirmation_count * 5, 20)  # До 20% за подтверждения
        
        # Бонус за качество сигналов (дивергенция, свипы ликвидности)
        quality_bonus = 0
        if any('divergence' in s for s in signals):
            quality_bonus += 10  # Дивергенция - сильный сигнал
        if any('liquidity_sweep' in s for s in signals):
            quality_bonus += 8  # Свип ликвидности
        
        # Штраф за недостаточное количество подтверждений
        confirmation_penalty = max(0, (min_confirmations_required - confirmation_count) * 10)
        
        # Рассчитываем финальную вероятность
        raw_probability = base_probability + confirmation_bonus + quality_bonus - confirmation_penalty
        
        # Определение финального сигнала с улучшенной логикой
        # Рассчитываем вероятность независимо от количества подтверждений
        has_enough_confirmations = confirmation_count >= min_confirmations_required
        
        if signal_strength > 30:
            final_signal = 'strong_long'
            if has_enough_confirmations:
                probability = min(60 + raw_probability * 0.4, 92)
            else:
                # Снижаем вероятность, но не обнуляем
                probability = max(35, min(45 + raw_probability * 0.3, 75))
        elif signal_strength > 15:
            final_signal = 'long'
            if has_enough_confirmations:
                probability = min(45 + raw_probability * 0.35, 75)
            else:
                probability = max(30, min(35 + raw_probability * 0.25, 60))
        elif signal_strength < -30:
            final_signal = 'strong_short'
            if has_enough_confirmations:
                probability = min(60 + raw_probability * 0.4, 92)
            else:
                probability = max(35, min(45 + raw_probability * 0.3, 75))
        elif signal_strength < -15:
            final_signal = 'short'
            if has_enough_confirmations:
                probability = min(45 + raw_probability * 0.35, 75)
            else:
                probability = max(30, min(35 + raw_probability * 0.25, 60))
        elif abs(signal_strength) > 5:
            # Слабые сигналы
            if signal_strength > 0:
                final_signal = 'long'
            else:
                final_signal = 'short'
            # Для слабых сигналов вероятность зависит от подтверждений
            if has_enough_confirmations:
                probability = max(30, min(30 + raw_probability * 0.3, 55))
            else:
                # Даже при недостаточных подтверждениях даем минимальную вероятность
                confirmation_ratio = max(0.3, confirmation_count / min_confirmations_required)
                probability = max(20, min(25 + raw_probability * 0.2 * confirmation_ratio, 45))
        else:
            final_signal = 'neutral'
            probability = 0
        
        # Дополнительная корректировка вероятности при недостаточных подтверждениях
        if not has_enough_confirmations and probability > 0:
            # Снижаем вероятность пропорционально, но сохраняем минимум
            confirmation_ratio = max(0.4, confirmation_count / min_confirmations_required)
            probability = max(probability * confirmation_ratio, 20)  # Минимум 20% даже при 1 подтверждении
        
        # Генерируем рекомендацию с учётом расширенного анализа
        recommendation = advanced_analysis.get('recommendations')
        if not recommendation:
            recommendation = self._generate_recommendation(final_signal, current_price)
        elif isinstance(recommendation, dict):
            # Если recommendation есть, но нет entry/stop_loss/take_profit, дополняем
            if not recommendation.get('entry') and current_price:
                recommendation['entry'] = current_price * 0.999 if final_signal in ['long', 'strong_long'] else current_price * 1.001
            if not recommendation.get('stop_loss') and current_price:
                recommendation['stop_loss'] = current_price * 0.985 if final_signal in ['long', 'strong_long'] else current_price * 1.015
            if not recommendation.get('take_profit') and current_price:
                recommendation['take_profit'] = current_price * 1.03 if final_signal in ['long', 'strong_long'] else current_price * 0.97
        
        return {
            'current_price': current_price,
            'candle_analysis': candle_analysis,
            'indicators': indicators,
            'orderbook_analysis': orderbook_analysis,
            'advanced_analysis': advanced_analysis,
            'signals': signals,
            'final_signal': final_signal,
            'probability': probability,
            'recommendation': recommendation,
            'confirmations': {
                'count': confirmation_count,
                'sources': confirmations,
                'required': min_confirmations_required
            }
        }
    
    def _analyze_orderbook(self, orderbook: Dict[str, Any]) -> Dict[str, Any]:
        """
        Анализирует стакан согласно рекомендациям proverka.txt
        
        Согласно proverka.txt:
        - Использовать больше уровней (до 100 для перпетульного API)
        - Мониторить depth imbalance: (sum bids / sum asks) >1.2 — buy signal
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # Используем больше уровней для более точного анализа (рекомендация proverka.txt)
        # Для перпетульного API рекомендуется до 100 уровней, используем 50 для баланса
        total_bid_volume = sum([bid[1] for bid in bids[:50]])  # Увеличено с 10 до 50
        total_ask_volume = sum([ask[1] for ask in asks[:50]])  # Увеличено с 10 до 50
        
        # Имбаланс в процентах
        imbalance = (total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume) * 100
        
        # Согласно proverka.txt: (sum bids / sum asks) >1.2 — buy signal
        bids_asks_ratio = total_bid_volume / total_ask_volume if total_ask_volume > 0 else 1.0
        
        # Стены (анализируем больше уровней)
        walls = []
        avg_bid_volume = total_bid_volume / len(bids[:50]) if bids else 0
        avg_ask_volume = total_ask_volume / len(asks[:50]) if asks else 0
        
        for bid in bids[:20]:  # Проверяем больше уровней
            if bid[1] > avg_bid_volume * 2.5:  # Стена - больше 2.5x среднего
                walls.append({'type': 'bid', 'price': bid[0], 'volume': bid[1]})
        
        for ask in asks[:20]:
            if ask[1] > avg_ask_volume * 2.5:
                walls.append({'type': 'ask', 'price': ask[0], 'volume': ask[1]})
        
        # Сигнал на основе ratio (согласно proverka.txt)
        if bids_asks_ratio > 1.2:  # Порог из proverka.txt
            signal = 'bullish'
        elif bids_asks_ratio < 0.83:  # Обратный порог (1/1.2)
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return {
            'total_bid_volume': total_bid_volume,
            'total_ask_volume': total_ask_volume,
            'imbalance': imbalance,
            'bids_asks_ratio': bids_asks_ratio,  # Новое поле согласно proverka.txt
            'walls': walls,
            'signal': signal
        }
    
    def _generate_recommendation(self, signal: str, current_price: float) -> Dict[str, Any]:
        """Генерирует рекомендацию по входу"""
        if signal == 'neutral' or current_price is None:
            return None
        
        is_long = 'long' in signal
        
        if is_long:
            entry = current_price * 0.999  # Немного ниже текущей цены
            stop_loss = current_price * 0.985  # -1.5%
            take_profit = current_price * 1.03  # +3%
        else:
            entry = current_price * 1.001  # Немного выше текущей цены
            stop_loss = current_price * 1.015  # +1.5%
            take_profit = current_price * 0.97  # -3%
        
        return {
            'direction': 'LONG' if is_long else 'SHORT',
            'entry': entry,
            'stop_loss': stop_loss,
            'take_profit': take_profit
        }
