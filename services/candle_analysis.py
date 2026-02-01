import pandas as pd
import pandas_ta as ta
from typing import Dict, List, Tuple, Optional
import numpy as np


class CandleAnalyzer:
    """Класс для анализа японских свечей и паттернов"""
    
    def __init__(self):
        self.patterns = {
            'bullish': ['hammer', 'bullish_engulfing', 'morning_star', 'piercing_pattern'],
            'bearish': ['hanging_man', 'bearish_engulfing', 'evening_star', 'shooting_star'],
            'neutral': ['doji', 'spinning_top']
        }
    
    def analyze_candles(self, ohlcv: List[List]) -> Dict[str, any]:
        """
        Анализирует свечи и определяет паттерны
        
        Args:
            ohlcv: Список свечей [timestamp, open, high, low, close, volume]
        
        Returns:
            Словарь с результатами анализа
        """
        if len(ohlcv) < 3:
            return {'error': 'Недостаточно данных для анализа'}
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Анализ последних свечей
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2] if len(df) > 1 else None
        prev2_candle = df.iloc[-3] if len(df) > 2 else None
        
        patterns = []
        signals = []
        
        # Определение паттернов
        if prev_candle is not None:
            # Молот (Hammer)
            if self._is_hammer(last_candle):
                patterns.append('Молот (бычий)')
                signals.append('bullish')
            
            # Повешенный (Hanging Man)
            if self._is_hanging_man(last_candle):
                patterns.append('Повешенный (медвежий)')
                signals.append('bearish')
            
            # Поглощение
            if self._is_engulfing(prev_candle, last_candle):
                if last_candle['close'] > last_candle['open'] and prev_candle['close'] < prev_candle['open']:
                    patterns.append('Бычье поглощение')
                    signals.append('bullish')
                elif last_candle['close'] < last_candle['open'] and prev_candle['close'] > prev_candle['open']:
                    patterns.append('Медвежье поглощение')
                    signals.append('bearish')
            
            # Doji
            if self._is_doji(last_candle):
                patterns.append('Doji (нерешительность)')
                signals.append('neutral')
            
            # Падающая звезда
            if self._is_shooting_star(last_candle):
                patterns.append('Падающая звезда (медвежий)')
                signals.append('bearish')
            
            # Пин-бар
            pin_bar = self._is_pin_bar(last_candle)
            if pin_bar:
                patterns.append(f'Пин-бар ({pin_bar})')
                signals.append(pin_bar)
        
        # Анализ теней
        upper_shadow = last_candle['high'] - max(last_candle['open'], last_candle['close'])
        lower_shadow = min(last_candle['open'], last_candle['close']) - last_candle['low']
        body = abs(last_candle['close'] - last_candle['open'])
        
        shadow_analysis = {
            'upper_shadow': upper_shadow,
            'lower_shadow': lower_shadow,
            'body': body,
            'long_lower_shadow': lower_shadow > body * 2,
            'long_upper_shadow': upper_shadow > body * 2,
        }
        
        # Определение общего сигнала
        bullish_count = signals.count('bullish')
        bearish_count = signals.count('bearish')
        
        if bullish_count > bearish_count:
            overall_signal = 'bullish'
            signal_strength = min(bullish_count * 25, 100)
        elif bearish_count > bullish_count:
            overall_signal = 'bearish'
            signal_strength = min(bearish_count * 25, 100)
        else:
            overall_signal = 'neutral'
            signal_strength = 0
        
        return {
            'patterns': patterns,
            'signals': list(set(signals)),
            'overall_signal': overall_signal,
            'signal_strength': signal_strength,
            'shadow_analysis': shadow_analysis,
            'last_candle': {
                'open': last_candle['open'],
                'high': last_candle['high'],
                'low': last_candle['low'],
                'close': last_candle['close'],
                'volume': last_candle['volume'],
                'is_bullish': last_candle['close'] > last_candle['open'],
            }
        }
    
    def _is_hammer(self, candle: pd.Series) -> bool:
        """Определяет молот"""
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        return (lower_shadow > body * 2 and 
                upper_shadow < body * 0.3 and
                candle['close'] > candle['open'] * 0.99)  # Почти бычья свеча
    
    def _is_hanging_man(self, candle: pd.Series) -> bool:
        """Определяет повешенного"""
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        return (lower_shadow > body * 2 and 
                upper_shadow < body * 0.3)
    
    def _is_engulfing(self, prev: pd.Series, curr: pd.Series) -> bool:
        """Определяет поглощение"""
        prev_body = abs(prev['close'] - prev['open'])
        curr_body = abs(curr['close'] - curr['open'])
        
        return (curr_body > prev_body * 1.1 and
                curr['open'] < prev['close'] and
                curr['close'] > prev['open'])
    
    def _is_doji(self, candle: pd.Series) -> bool:
        """Определяет Doji"""
        body = abs(candle['close'] - candle['open'])
        total_range = candle['high'] - candle['low']
        
        return body < total_range * 0.1
    
    def _is_shooting_star(self, candle: pd.Series) -> bool:
        """Определяет падающую звезду"""
        body = abs(candle['close'] - candle['open'])
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        
        return (upper_shadow > body * 2 and
                lower_shadow < body * 0.3)
    
    def _is_pin_bar(self, candle: pd.Series) -> Optional[str]:
        """Определяет пин-бар"""
        body = abs(candle['close'] - candle['open'])
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        total_range = candle['high'] - candle['low']
        
        if upper_shadow > total_range * 0.6 and lower_shadow < total_range * 0.2:
            return 'bearish'
        elif lower_shadow > total_range * 0.6 and upper_shadow < total_range * 0.2:
            return 'bullish'
        
        return None
