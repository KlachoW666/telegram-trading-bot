import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from services.candle_analysis import CandleAnalyzer


class AdvancedMarketAnalyzer:
    """Расширенный анализ рынка на основе Order Flow и структурных паттернов"""
    
    def __init__(self):
        self.candle_analyzer = CandleAnalyzer()
    
    def find_imbalance(self, ohlcv: List[List], timeframe: str = '1h') -> List[Dict[str, Any]]:
        """
        Находит IMB (Imbalance) - зоны несбалансированного объёма (gap в цене)
        
        Returns список найденных IMB зон
        """
        if len(ohlcv) < 3:
            return []
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        imbalances = []
        
        for i in range(1, len(df)):
            prev_candle = df.iloc[i-1]
            curr_candle = df.iloc[i]
            
            # Бычий IMB (gap вверх)
            if curr_candle['low'] > prev_candle['high']:
                imbalance = {
                    'type': 'bullish_imb',
                    'zone_start': prev_candle['high'],
                    'zone_end': curr_candle['low'],
                    'timestamp': curr_candle['timestamp'],
                    'strength': 'strong' if (curr_candle['low'] - prev_candle['high']) > (prev_candle['high'] * 0.002) else 'weak',
                    'direction': 'long'
                }
                imbalances.append(imbalance)
            
            # Медвежий IMB (gap вниз)
            elif curr_candle['high'] < prev_candle['low']:
                imbalance = {
                    'type': 'bearish_imb',
                    'zone_start': curr_candle['high'],
                    'zone_end': prev_candle['low'],
                    'timestamp': curr_candle['timestamp'],
                    'strength': 'strong' if (prev_candle['low'] - curr_candle['high']) > (prev_candle['low'] * 0.002) else 'weak',
                    'direction': 'short'
                }
                imbalances.append(imbalance)
        
        return imbalances
    
    def find_fvg(self, ohlcv: List[List]) -> List[Dict[str, Any]]:
        """
        Находит FVG (Fair Value Gap) - gap в цене для отката
        
        Returns список найденных FVG зон
        """
        if len(ohlcv) < 3:
            return []
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        fvgs = []
        
        for i in range(1, len(df) - 1):
            prev_candle = df.iloc[i-1]
            curr_candle = df.iloc[i]
            next_candle = df.iloc[i+1]
            
            # Бычий FVG (gap между свечами для отката вверх)
            if (curr_candle['low'] > prev_candle['high'] and 
                next_candle['low'] > prev_candle['high']):
                fvg = {
                    'type': 'bullish_fvg',
                    'zone_start': prev_candle['high'],
                    'zone_end': min(curr_candle['low'], next_candle['low']),
                    'timestamp': curr_candle['timestamp'],
                    'mid_point': (prev_candle['high'] + min(curr_candle['low'], next_candle['low'])) / 2,
                    'direction': 'long',
                    'expectation': 'pullback_test'
                }
                fvgs.append(fvg)
            
            # Медвежий FVG (gap между свечами для отката вниз)
            elif (curr_candle['high'] < prev_candle['low'] and 
                  next_candle['high'] < prev_candle['low']):
                fvg = {
                    'type': 'bearish_fvg',
                    'zone_start': max(curr_candle['high'], next_candle['high']),
                    'zone_end': prev_candle['low'],
                    'timestamp': curr_candle['timestamp'],
                    'mid_point': (max(curr_candle['high'], next_candle['high']) + prev_candle['low']) / 2,
                    'direction': 'short',
                    'expectation': 'pullback_test'
                }
                fvgs.append(fvg)
        
        return fvgs
    
    def find_stb_zones(self, ohlcv: List[List], imbalance_zones: List[Dict]) -> List[Dict[str, Any]]:
        """
        Находит STB-зоны (Strong to Break) - зоны прорыва с имбалансом
        """
        if len(ohlcv) < 5:
            return []
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        stb_zones = []
        
        # Ищем зоны, где цена сильно отклонилась от IMB
        for imb in imbalance_zones:
            # Находим свечи рядом с IMB зоной
            zone_start = min(imb['zone_start'], imb['zone_end'])
            zone_end = max(imb['zone_start'], imb['zone_end'])
            
            # Ищем свечи, которые тестируют эту зону
            for i in range(len(df)):
                candle = df.iloc[i]
                if zone_start <= candle['close'] <= zone_end or zone_start <= candle['open'] <= zone_end:
                    # Проверяем силу прорыва
                    volume_ratio = candle['volume'] / df['volume'].tail(20).mean() if len(df) >= 20 else 1.0
                    
                    if volume_ratio > 1.5:  # Объём выше среднего
                        stb = {
                            'type': 'stb_zone',
                            'imb_zone': imb,
                            'test_price': candle['close'],
                            'volume_ratio': volume_ratio,
                            'timestamp': candle['timestamp'],
                            'direction': imb['direction'],
                            'signal': 'strong'
                        }
                        stb_zones.append(stb)
                        break
        
        return stb_zones
    
    def analyze_liquidity_pools(self, ohlcv: List[List], orderbook: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Анализирует пулы ликвидности - крупные скопления ордеров
        """
        if len(ohlcv) < 10:
            return {}
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Находим уровни с наибольшим объёмом (Volume Profile)
        volume_profile = {}
        price_range = df['high'].max() - df['low'].min()
        num_levels = 20
        level_size = price_range / num_levels
        
        for _, candle in df.iterrows():
            price_start = df['low'].min() + int((candle['low'] - df['low'].min()) / level_size) * level_size
            price_start = round(price_start, 2)
            
            if price_start not in volume_profile:
                volume_profile[price_start] = 0
            volume_profile[price_start] += candle['volume']
        
        # Находим POC (Point of Control) - уровень с максимальным объёмом
        if volume_profile:
            poc_level = max(volume_profile, key=volume_profile.get)
            poc_volume = volume_profile[poc_level]
            
            # Находим HVN (High Volume Nodes) - уровни с высоким объёмом
            avg_volume = sum(volume_profile.values()) / len(volume_profile)
            hvn_levels = [level for level, vol in volume_profile.items() if vol > avg_volume * 1.5]
            
            # LVN (Low Volume Nodes) - уровни с низким объёмом
            lvn_levels = [level for level, vol in volume_profile.items() if vol < avg_volume * 0.5]
            
        pool_analysis = self._analyze_pool_position(df['close'].iloc[-1], poc_level, hvn_levels, lvn_levels)
        
        return {
            'poc': poc_level,
            'poc_volume': poc_volume,
            'hvn_levels': sorted(hvn_levels),
            'lvn_levels': sorted(lvn_levels),
            'volume_profile': volume_profile,
            'current_price': df['close'].iloc[-1],
            'analysis': pool_analysis,
            'nearest_pool_below': pool_analysis.get('nearest_pool_below'),
            'nearest_pool_above': pool_analysis.get('nearest_pool_above')
        }
    
    def _analyze_pool_position(self, current_price: float, poc: float, hvn: List[float], lvn: List[float]) -> Dict[str, Any]:
        """Анализирует позицию цены относительно пулов ликвидности"""
        # Определяем ближайшие уровни
        all_levels = sorted([poc] + hvn + lvn)
        
        below_levels = [l for l in all_levels if l < current_price]
        above_levels = [l for l in all_levels if l > current_price]
        
        nearest_below = max(below_levels) if below_levels else None
        nearest_above = min(above_levels) if above_levels else None
        
        return {
            'position': 'above_poc' if current_price > poc else 'below_poc' if current_price < poc else 'at_poc',
            'nearest_pool_below': nearest_below,
            'nearest_pool_above': nearest_above,
            'distance_to_poc': abs(current_price - poc) / poc * 100 if poc > 0 else 0
        }
    
    def detect_liquidity_sweeps(self, ohlcv: List[List], orderbook: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Обнаруживает манипуляции с ликвидностью - свипы лоев/хаев (сбор стопов)
        """
        if len(ohlcv) < 5:
            return []
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        sweeps = []
        
        # Анализируем последние 10 свечей
        recent_candles = df.tail(10)
        
        for i in range(1, len(recent_candles)):
            prev_candle = recent_candles.iloc[i-1]
            curr_candle = recent_candles.iloc[i]
            
            # Свип лоев (sweep lows) - цена пробила минимум, но отскочила вверх
            if (curr_candle['low'] < prev_candle['low'] and 
                curr_candle['close'] > prev_candle['close'] and
                curr_candle['close'] > curr_candle['open']):
                sweep = {
                    'type': 'liquidity_sweep_lows',
                    'sweep_price': curr_candle['low'],
                    'reaction_price': curr_candle['close'],
                    'timestamp': curr_candle['timestamp'],
                    'direction': 'bullish_reversal',
                    'signal': 'long'
                }
                sweeps.append(sweep)
            
            # Свип хаев (sweep highs) - цена пробила максимум, но отскочила вниз
            elif (curr_candle['high'] > prev_candle['high'] and 
                  curr_candle['close'] < prev_candle['close'] and
                  curr_candle['close'] < curr_candle['open']):
                sweep = {
                    'type': 'liquidity_sweep_highs',
                    'sweep_price': curr_candle['high'],
                    'reaction_price': curr_candle['close'],
                    'timestamp': curr_candle['timestamp'],
                    'direction': 'bearish_reversal',
                    'signal': 'short'
                }
                sweeps.append(sweep)
        
        return sweeps
    
    def detect_divergence(self, ohlcv: List[List], rsi_values: List[float]) -> Dict[str, Any]:
        """
        Обнаруживает дивергенцию RSI/Order Flow (согласно analiz.txt)
        
        Дивергенция = цена делает новый минимум/максимум, но RSI/OF не подтверждает
        """
        if len(ohlcv) < 20 or len(rsi_values) < 20:
            return {'has_divergence': False}
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Берём последние 20 свечей для анализа
        recent_prices = df['close'].tail(20).values
        recent_rsi = rsi_values[-20:] if len(rsi_values) >= 20 else rsi_values
        
        if len(recent_prices) < 10 or len(recent_rsi) < 10:
            return {'has_divergence': False}
        
        # Ищем локальные минимумы и максимумы
        price_lows = []
        price_highs = []
        rsi_lows = []
        rsi_highs = []
        
        for i in range(1, len(recent_prices) - 1):
            # Локальный минимум цены
            if recent_prices[i] < recent_prices[i-1] and recent_prices[i] < recent_prices[i+1]:
                price_lows.append((i, recent_prices[i]))
                if i < len(recent_rsi):
                    rsi_lows.append((i, recent_rsi[i]))
            
            # Локальный максимум цены
            if recent_prices[i] > recent_prices[i-1] and recent_prices[i] > recent_prices[i+1]:
                price_highs.append((i, recent_prices[i]))
                if i < len(recent_rsi):
                    rsi_highs.append((i, recent_rsi[i]))
        
        # Проверяем бычью дивергенцию (цена делает новый минимум, RSI - нет)
        bullish_divergence = False
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            last_low_price = price_lows[-1][1]
            prev_low_price = price_lows[-2][1]
            last_low_rsi = rsi_lows[-1][1] if len(rsi_lows) > 0 else None
            prev_low_rsi = rsi_lows[-2][1] if len(rsi_lows) > 1 else None
            
            if last_low_rsi is not None and prev_low_rsi is not None:
                # Цена упала ниже, но RSI выше - бычья дивергенция
                if last_low_price < prev_low_price and last_low_rsi > prev_low_rsi:
                    bullish_divergence = True
        
        # Проверяем медвежью дивергенцию (цена делает новый максимум, RSI - нет)
        bearish_divergence = False
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            last_high_price = price_highs[-1][1]
            prev_high_price = price_highs[-2][1]
            last_high_rsi = rsi_highs[-1][1] if len(rsi_highs) > 0 else None
            prev_high_rsi = rsi_highs[-2][1] if len(rsi_highs) > 1 else None
            
            if last_high_rsi is not None and prev_high_rsi is not None:
                # Цена выросла выше, но RSI ниже - медвежья дивергенция
                if last_high_price > prev_high_price and last_high_rsi < prev_high_rsi:
                    bearish_divergence = True
        
        return {
            'has_divergence': bullish_divergence or bearish_divergence,
            'bullish_divergence': bullish_divergence,
            'bearish_divergence': bearish_divergence,
            'signal': 'long' if bullish_divergence else 'short' if bearish_divergence else 'neutral'
        }
    
    def analyze_order_flow(self, ohlcv: List[List], orderbook: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Анализирует Order Flow (поток ордеров) с Delta из стакана
        """
        if len(ohlcv) < 10:
            return {}
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Простой анализ Order Flow на основе свечей и объёма
        bullish_candles = df[df['close'] > df['open']]
        bearish_candles = df[df['close'] < df['open']]
        
        bullish_volume = bullish_candles['volume'].sum() if len(bullish_candles) > 0 else 0
        bearish_volume = bearish_candles['volume'].sum() if len(bearish_candles) > 0 else 0
        total_volume = df['volume'].sum()
        
        # Delta из стакана (buy/sell volume imbalance)
        # Согласно proverka.txt: используем больше уровней для точности (до 100 для перпетульного API)
        delta = 0
        if orderbook:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            # Суммируем объёмы в стакане (первые 50 уровней для более точного анализа)
            bid_volume = sum([b[1] for b in bids[:50]]) if bids else 0
            ask_volume = sum([a[1] for a in asks[:50]]) if asks else 0
            delta = bid_volume - ask_volume
            delta_percent = (delta / (bid_volume + ask_volume) * 100) if (bid_volume + ask_volume) > 0 else 0
            
            # Согласно proverka.txt: (sum bids / sum asks) >1.2 — buy signal
            bids_asks_ratio = bid_volume / ask_volume if ask_volume > 0 else 1.0
        else:
            delta_percent = 0
            bids_asks_ratio = 1.0
        
        # Определяем направление Order Flow
        # Согласно proverka.txt: используем bids/asks ratio >1.2 как дополнительный сигнал
        if bullish_volume > bearish_volume * 1.2 or bids_asks_ratio > 1.2:
            of_direction = 'bullish'
            base_strength = min(bullish_volume / bearish_volume, 5.0) if bearish_volume > 0 else 5.0
            # Усиливаем если ratio подтверждает (согласно proverka.txt)
            if bids_asks_ratio > 1.2:
                of_strength = base_strength * (1 + (bids_asks_ratio - 1.2) * 0.5)  # Бонус за ratio
            else:
                of_strength = base_strength
        elif bearish_volume > bullish_volume * 1.2 or bids_asks_ratio < 0.83:
            of_direction = 'bearish'
            base_strength = min(bearish_volume / bullish_volume, 5.0) if bullish_volume > 0 else 5.0
            if bids_asks_ratio < 0.83:
                of_strength = base_strength * (1 + (0.83 - bids_asks_ratio) * 0.5)
            else:
                of_strength = base_strength
        else:
            of_direction = 'neutral'
            of_strength = 1.0
        
        # Усиливаем сигнал, если Delta подтверждает
        if delta > 0 and of_direction == 'bullish':
            of_strength *= 1.2
        elif delta < 0 and of_direction == 'bearish':
            of_strength *= 1.2
        
        # Анализ на младшем таймфрейме (последние 3 свечи)
        recent_3 = df.tail(3)
        recent_trend = 'up' if recent_3['close'].iloc[-1] > recent_3['close'].iloc[0] else 'down'
        
        return {
            'direction': of_direction,
            'strength': round(of_strength, 2),
            'bullish_volume': bullish_volume,
            'bearish_volume': bearish_volume,
            'volume_ratio': round(bullish_volume / bearish_volume, 2) if bearish_volume > 0 else 0,
            'recent_trend': recent_trend,
            'delta': delta,
            'delta_percent': round(delta_percent, 2),
            'bids_asks_ratio': round(bids_asks_ratio, 3),  # Согласно proverka.txt
            'signal': 'long' if of_direction == 'bullish' and recent_trend == 'up' else 
                     'short' if of_direction == 'bearish' and recent_trend == 'down' else 'neutral'
        }
    
    def detect_bos_choch(self, ohlcv: List[List]) -> Dict[str, Any]:
        """
        Обнаруживает BOS (Break of Structure) и CHOCH (Change of Character)
        """
        if len(ohlcv) < 20:
            return {}
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Анализируем структуру (Higher Highs / Lower Lows)
        recent_10 = df.tail(10)
        highs = recent_10['high'].values
        lows = recent_10['low'].values
        
        # BOS - прорыв структуры (новый HH или новый LL)
        highest_high = df['high'].max()
        lowest_low = df['low'].min()
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        bos = None
        if current_high > highest_high * 0.99:
            bos = {'type': 'bos_breakout_up', 'level': highest_high, 'direction': 'bullish'}
        elif current_low < lowest_low * 1.01:
            bos = {'type': 'bos_breakdown_down', 'level': lowest_low, 'direction': 'bearish'}
        
        # CHOCH - смена характера тренда
        # Ищем разворот паттерна HH/LL
        higher_highs = sum([1 for i in range(1, len(highs)) if highs[i] > highs[i-1]])
        lower_lows = sum([1 for i in range(1, len(lows)) if lows[i] < lows[i-1]])
        
        choch = None
        if higher_highs >= 3 and lower_lows >= 2:
            # Была восходящая структура, но появились LL
            choch = {'type': 'choch_bearish', 'signal': 'potential_reversal_down'}
        elif lower_lows >= 3 and higher_highs >= 2:
            # Была нисходящая структура, но появились HH
            choch = {'type': 'choch_bullish', 'signal': 'potential_reversal_up'}
        
        return {
            'bos': bos,
            'choch': choch,
            'structure': 'uptrend' if higher_highs > lower_lows else 'downtrend' if lower_lows > higher_highs else 'range'
        }
    
    def comprehensive_analysis(self, ohlcv: List[List], orderbook: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Комплексный анализ рынка с использованием всех техник
        """
        current_price = ohlcv[-1][4] if ohlcv else 0
        
        # Анализ IMB, FVG, STB
        imbalances = self.find_imbalance(ohlcv)
        fvgs = self.find_fvg(ohlcv)
        stb_zones = self.find_stb_zones(ohlcv, imbalances)
        
        # Анализ пулов ликвидности
        liquidity_pools = self.analyze_liquidity_pools(ohlcv, orderbook)
        
        # Анализ свипов ликвидности
        liquidity_sweeps = self.detect_liquidity_sweeps(ohlcv, orderbook)
        
        # Анализ Order Flow
        order_flow = self.analyze_order_flow(ohlcv, orderbook)
        
        # BOS/CHOCH
        structure = self.detect_bos_choch(ohlcv)
        
        # Генерируем торговые сигналы
        signals = self._generate_advanced_signals(
            current_price, imbalances, fvgs, stb_zones, 
            liquidity_pools, liquidity_sweeps, order_flow, structure
        )
        
        return {
            'current_price': current_price,
            'imbalances': imbalances[-5:] if imbalances else [],  # Последние 5
            'fvgs': fvgs[-5:] if fvgs else [],  # Последние 5
            'stb_zones': stb_zones,
            'liquidity_pools': liquidity_pools,
            'liquidity_sweeps': liquidity_sweeps[-3:] if liquidity_sweeps else [],
            'order_flow': order_flow,
            'structure': structure,
            'signals': signals,
            'recommendations': self._generate_recommendations(signals, liquidity_pools, fvgs)
        }
    
    def _generate_advanced_signals(self, current_price: float, imbalances: List, 
                                   fvgs: List, stb_zones: List, liquidity_pools: Dict,
                                   liquidity_sweeps: List, order_flow: Dict, structure: Dict) -> List[Dict]:
        """Генерирует торговые сигналы на основе всех анализов"""
        signals = []
        
        # Сигнал от Order Flow
        if order_flow.get('signal') != 'neutral':
            signals.append({
                'source': 'order_flow',
                'type': order_flow['signal'],
                'strength': order_flow.get('strength', 1),
                'description': f"Order Flow: {order_flow['direction']}"
            })
        
        # Сигнал от FVG (тест снизу для лонга)
        for fvg in fvgs[-3:]:  # Последние 3 FVG
            if fvg['type'] == 'bullish_fvg':
                if current_price <= fvg['zone_end'] * 1.005 and current_price >= fvg['zone_start'] * 0.995:
                    signals.append({
                        'source': 'fvg',
                        'type': 'long',
                        'strength': 2,
                        'description': f"Тест FVG снизу на {fvg['mid_point']:.2f}"
                    })
            elif fvg['type'] == 'bearish_fvg':
                if current_price >= fvg['zone_start'] * 0.995 and current_price <= fvg['zone_end'] * 1.005:
                    signals.append({
                        'source': 'fvg',
                        'type': 'short',
                        'strength': 2,
                        'description': f"Тест FVG сверху на {fvg['mid_point']:.2f}"
                    })
        
        # Сигнал от свипов ликвидности
        for sweep in liquidity_sweeps[-2:]:  # Последние 2 свипа
            if sweep['signal'] == 'long':
                signals.append({
                    'source': 'liquidity_sweep',
                    'type': 'long',
                    'strength': 3,
                    'description': f"Свип лоев - разворот вверх от {sweep['sweep_price']:.2f}"
                })
            elif sweep['signal'] == 'short':
                signals.append({
                    'source': 'liquidity_sweep',
                    'type': 'short',
                    'strength': 3,
                    'description': f"Свип хаев - разворот вниз от {sweep['sweep_price']:.2f}"
                })
        
        # Сигнал от BOS/CHOCH
        if structure.get('bos'):
            signals.append({
                'source': 'structure',
                'type': structure['bos']['direction'],
                'strength': 3,
                'description': f"BOS: {structure['bos']['type']}"
            })
        
        if structure.get('choch'):
            signals.append({
                'source': 'structure',
                'type': structure['choch']['signal'].replace('potential_reversal_', ''),
                'strength': 2,
                'description': f"CHOCH: {structure['choch']['type']}"
            })
        
        return signals
    
    def _generate_recommendations(self, signals: List[Dict], liquidity_pools: Dict, 
                                  fvgs: List[Dict]) -> Dict[str, Any]:
        """Генерирует рекомендации по входу/выходу"""
        if not signals:
            return None
        
        # Подсчитываем силу сигналов
        long_signals = [s for s in signals if s['type'] == 'long']
        short_signals = [s for s in signals if s['type'] == 'short']
        
        long_strength = sum([s['strength'] for s in long_signals])
        short_strength = sum([s['strength'] for s in short_signals])
        
        if long_strength > short_strength and long_strength >= 3:
            direction = 'LONG'
            # Определяем стоп-лосс и тейк-профит на основе пулов
            stop_loss = liquidity_pools.get('nearest_pool_below') if liquidity_pools else None
            take_profit = liquidity_pools.get('nearest_pool_above') if liquidity_pools else None
            
            # Используем FVG как уровень входа
            entry = None
            for fvg in fvgs[-2:]:
                if fvg['type'] == 'bullish_fvg':
                    entry = fvg['mid_point']
                    break
            
            return {
                'direction': direction,
                'strength': long_strength,
                'entry': entry,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'reason': f"{len(long_signals)} сигналов на лонг"
            }
        
        elif short_strength > long_strength and short_strength >= 3:
            direction = 'SHORT'
            stop_loss = liquidity_pools.get('nearest_pool_above') if liquidity_pools else None
            take_profit = liquidity_pools.get('nearest_pool_below') if liquidity_pools else None
            
            entry = None
            for fvg in fvgs[-2:]:
                if fvg['type'] == 'bearish_fvg':
                    entry = fvg['mid_point']
                    break
            
            return {
                'direction': direction,
                'strength': short_strength,
                'entry': entry,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'reason': f"{len(short_signals)} сигналов на шорт"
            }
        
        return None
