"""
Генератор графиков свечей с индикаторами для отправки в Telegram
"""
import io
import matplotlib
matplotlib.use('Agg')  # Используем Agg backend для работы без GUI
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from typing import List, Dict, Optional


class ChartGenerator:
    """Генератор графиков свечей с индикаторами"""
    
    @staticmethod
    def create_candle_chart(ohlcv_data: List[List], symbol: str, 
                           indicators: Optional[Dict] = None) -> io.BytesIO:
        """
        Создаёт график свечей с индикаторами
        
        Args:
            ohlcv_data: Список OHLCV данных [[timestamp, open, high, low, close, volume], ...]
            symbol: Название торговой пары
            indicators: Словарь с индикаторами (RSI, MACD, BB и т.д.)
        
        Returns:
            BytesIO объект с изображением графика
        """
        try:
            # Проверяем валидность данных
            if not ohlcv_data or len(ohlcv_data) < 2:
                raise ValueError("Недостаточно данных для создания графика")
            
            # Преобразуем данные в DataFrame
            df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Проверяем, что все необходимые колонки присутствуют и не пустые
            if df.empty or df['close'].isna().all():
                raise ValueError("Данные свечей пусты или некорректны")
            
            # Преобразуем timestamp
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
            
            # Удаляем строки с невалидными timestamp
            df = df.dropna(subset=['timestamp'])
            
            if df.empty:
                raise ValueError("Нет валидных данных после обработки timestamp")
            
            df.set_index('timestamp', inplace=True)
            
            # Берем последние 100 свечей для читаемости
            df = df.tail(100)
            
            # Проверяем, что остались данные
            if df.empty:
                raise ValueError("Нет данных после выборки последних 100 свечей")
            
            # Создаём стиль для графика - используем стандартный стиль для надежности
            # Кастомные стили могут вызывать ошибки в некоторых версиях mplfinance
            style = 'nightclouds'  # Стандартный тёмный стиль
            
            # Подготовка дополнительных графиков (plots)
            addplots = []
            
            # Добавляем индикаторы, если они есть
            if indicators:
                # Bollinger Bands
                if 'bb_upper' in indicators and 'bb_lower' in indicators:
                    bb_upper = indicators['bb_upper'][-100:]
                    bb_middle = indicators.get('bb_middle', [None] * len(bb_upper))[-100:]
                    bb_lower = indicators['bb_lower'][-100:]
                    
                    addplots.append(
                        mpf.make_addplot(
                            pd.Series(bb_upper, index=df.index),
                            color='#888888',
                            linestyle='--',
                            width=0.8,
                            secondary_y=False
                        )
                    )
                    addplots.append(
                        mpf.make_addplot(
                            pd.Series(bb_lower, index=df.index),
                            color='#888888',
                            linestyle='--',
                            width=0.8,
                            secondary_y=False
                        )
                    )
                    if bb_middle and all(x is not None for x in bb_middle):
                        addplots.append(
                            mpf.make_addplot(
                                pd.Series(bb_middle, index=df.index),
                                color='#666666',
                                linestyle=':',
                                width=0.6,
                                secondary_y=False
                            )
                        )
                
                # EMA/SMA
                if 'ema_20' in indicators:
                    ema20 = indicators['ema_20'][-100:]
                    addplots.append(
                        mpf.make_addplot(
                            pd.Series(ema20, index=df.index),
                            color='#00aaff',
                            width=1.0,
                            secondary_y=False
                        )
                    )
                
                if 'sma_50' in indicators:
                    sma50 = indicators['sma_50'][-100:]
                    addplots.append(
                        mpf.make_addplot(
                            pd.Series(sma50, index=df.index),
                            color='#ffaa00',
                            width=1.0,
                            secondary_y=False
                        )
                    )
            
            # Создаём график
            # addplot не может быть None, передаём только если есть индикаторы
            plot_params = {
                'type': 'candle',
                'style': style,
                'volume': True,
                'returnfig': True,
                'figsize': (12, 8),
                'tight_layout': True,
                'title': f"{symbol} - Candlestick Chart",
                'ylabel': 'Price (USDT)',
                'ylabel_lower': 'Volume'
            }
            
            if addplots:
                plot_params['addplot'] = addplots
            
            fig, axes = mpf.plot(df, **plot_params)
            
            # Сохраняем в BytesIO
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', 
                       facecolor='#1a1a1a', edgecolor='none')
            buf.seek(0)
            plt.close(fig)
            
            return buf
            
        except Exception as e:
            # В случае ошибки возвращаем пустой BytesIO
            import traceback
            error_details = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            print(f"[ChartGenerator] Ошибка создания графика: {e}")
            print(f"[ChartGenerator] Детали ошибки: {error_details[:200]}")
            buf = io.BytesIO()
            return buf
    
    @staticmethod
    def create_rsi_chart(rsi_data: List[float], symbol: str) -> io.BytesIO:
        """
        Создаёт отдельный график RSI (если нужен)
        """
        try:
            fig, ax = plt.subplots(figsize=(12, 4), facecolor='#1a1a1a')
            ax.set_facecolor('#1a1a1a')
            
            # Берем последние 100 значений
            rsi_plot = rsi_data[-100:] if len(rsi_data) > 100 else rsi_data
            x = range(len(rsi_plot))
            
            ax.plot(x, rsi_plot, color='#00aaff', linewidth=2, label='RSI')
            ax.axhline(y=70, color='#ff4444', linestyle='--', alpha=0.5, label='Overbought')
            ax.axhline(y=30, color='#00ff88', linestyle='--', alpha=0.5, label='Oversold')
            ax.axhline(y=50, color='#888888', linestyle=':', alpha=0.3)
            
            ax.set_title(f"{symbol} - RSI", color='white', fontsize=14)
            ax.set_ylabel('RSI', color='white')
            ax.set_ylim(0, 100)
            ax.grid(True, alpha=0.3, color='#3a3a3a')
            ax.legend(loc='upper right')
            
            ax.tick_params(colors='white')
            ax.spines['bottom'].set_color('#3a3a3a')
            ax.spines['top'].set_color('#3a3a3a')
            ax.spines['left'].set_color('#3a3a3a')
            ax.spines['right'].set_color('#3a3a3a')
            
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                       facecolor='#1a1a1a', edgecolor='none')
            buf.seek(0)
            plt.close(fig)
            
            return buf
            
        except Exception as e:
            print(f"[ChartGenerator] Ошибка создания RSI графика: {e}")
            buf = io.BytesIO()
            return buf
