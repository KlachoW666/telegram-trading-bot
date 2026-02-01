#!/usr/bin/env python3
"""
Профессиональный анализ торговых позиций с продвинутыми метриками и рекомендациями
Уровень: Senior Developer
"""
import json
import csv
import math
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from data.database import get_database
from data.user_data import UserDataManager


class Priority(Enum):
    """Приоритет рекомендации"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class HoldingTimeStats:
    """Статистика времени удержания"""
    count: int
    mean: float
    median: float
    std_dev: float
    min: float
    max: float
    q25: float  # Первый квартиль
    q75: float  # Третий квартиль
    iqr: float  # Межквартильный размах
    cv: float  # Коэффициент вариации
    mode_range: Tuple[float, float]  # Наиболее частый диапазон
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Recommendation:
    """Рекомендация по улучшению"""
    priority: Priority
    category: str
    issue: str
    current_value: Optional[float]
    target_value: Optional[float]
    recommendation: str
    expected_impact: str
    implementation_effort: str
    confidence: float  # 0.0 - 1.0
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'priority': self.priority.value
        }


class PositionAnalyzer:
    """Профессиональный анализатор позиций"""
    
    def __init__(self, user_id: int = 8486449177):
        self.user_id = user_id
        self.db = get_database()
        self.user_data = UserDataManager()
        self.closed_trades = []
        self.open_trades = []
        self.holding_times_data = []
        
    def load_data(self) -> None:
        """Загрузка данных из БД с fallback на user_data"""
        try:
            # Пробуем получить из БД
            self.closed_trades = self.db.get_closed_trades(self.user_id, limit=10000)
            
            # Если в БД нет данных, пробуем получить из user_data (для обратной совместимости)
            if not self.closed_trades:
                try:
                    # Получаем все демо-позиции и фильтруем закрытые
                    all_trades = self.user_data.get_demo_positions(self.user_id)
                    self.closed_trades = [
                        t for t in all_trades 
                        if t.get('status') == 'closed' and t.get('close_price') is not None
                    ]
                    # Преобразуем формат для совместимости
                    for trade in self.closed_trades:
                        if 'entry' in trade and 'entry_price' not in trade:
                            trade['entry_price'] = trade.get('entry', 0)
                        if 'close_price' not in trade:
                            trade['close_price'] = trade.get('close_price', 0)
                except Exception as fallback_err:
                    print(f"⚠️ Fallback на user_data не удался: {fallback_err}")
            
            # Открытые позиции
            open_trades_raw = self.user_data.get_demo_positions(self.user_id)
            self.open_trades = [t for t in open_trades_raw if t.get('status') == 'open']
            
            print(f"📊 Загружено: {len(self.closed_trades)} закрытых, {len(self.open_trades)} открытых позиций")
            
        except Exception as e:
            print(f"❌ Ошибка загрузки данных: {e}")
            import traceback
            traceback.print_exc()
            # Продолжаем с пустыми данными
            self.closed_trades = []
            self.open_trades = []
    
    def parse_datetime(self, dt_value: Any) -> Optional[datetime]:
        """Парсинг datetime из различных форматов с улучшенной обработкой"""
        if not dt_value:
            return None
        
        try:
            if isinstance(dt_value, datetime):
                return dt_value
            
            if isinstance(dt_value, str):
                # Убираем лишние пробелы
                dt_value = dt_value.strip()
                
                # Пробуем ISO формат (2024-01-22T10:30:00 или 2024-01-22T10:30:00.123456)
                if 'T' in dt_value or ('-' in dt_value and ':' in dt_value):
                    # Обработка различных вариантов ISO формата
                    dt_value = dt_value.replace('Z', '+00:00')
                    # Если нет timezone, добавляем
                    if '+' not in dt_value and dt_value.count(':') >= 2:
                        # Пробуем парсить без timezone
                        try:
                            return datetime.fromisoformat(dt_value)
                        except:
                            # Пробуем добавить timezone
                            if dt_value.endswith('+00:00') or dt_value.endswith('-00:00'):
                                pass
                            else:
                                dt_value = dt_value + '+00:00'
                    return datetime.fromisoformat(dt_value)
                
                # Пробуем timestamp строку
                try:
                    return datetime.fromtimestamp(float(dt_value))
                except (ValueError, OSError):
                    pass
                
                # Пробуем другие форматы
                formats = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M:%S.%f',
                    '%Y-%m-%d',
                ]
                for fmt in formats:
                    try:
                        return datetime.strptime(dt_value, fmt)
                    except ValueError:
                        continue
            
            elif isinstance(dt_value, (int, float)):
                # Unix timestamp
                try:
                    return datetime.fromtimestamp(dt_value)
                except (OSError, ValueError):
                    # Если timestamp слишком большой, может быть в миллисекундах
                    if dt_value > 1e10:
                        return datetime.fromtimestamp(dt_value / 1000)
            
            return None
        except Exception as e:
            # Тихая обработка ошибок для анализа
            return None
    
    def calculate_holding_times(self) -> List[Dict[str, Any]]:
        """Расчет времени удержания для всех позиций с улучшенной обработкой"""
        holding_times = []
        skipped_count = 0
        skipped_reasons = defaultdict(int)
        
        for trade in self.closed_trades:
            # Пробуем разные варианты ключей для времени
            entry_time = trade.get('entry_time') or trade.get('timestamp') or trade.get('entry_timestamp')
            close_time = trade.get('close_time') or trade.get('close_timestamp')
            
            entry_dt = self.parse_datetime(entry_time)
            close_dt = self.parse_datetime(close_time)
            
            if not entry_dt:
                skipped_count += 1
                skipped_reasons['no_entry_time'] += 1
                continue
            
            if not close_dt:
                skipped_count += 1
                skipped_reasons['no_close_time'] += 1
                continue
            
            holding_minutes = (close_dt - entry_dt).total_seconds() / 60
            
            # Валидация времени удержания
            if holding_minutes < 0:
                skipped_count += 1
                skipped_reasons['negative_time'] += 1
                continue
            
            if holding_minutes > 10000:  # Больше ~7 дней - вероятно ошибка
                skipped_count += 1
                skipped_reasons['too_long'] += 1
                continue
            
            # Пробуем разные варианты ключей для данных
            holding_times.append({
                'symbol': trade.get('symbol', 'UNKNOWN'),
                'direction': trade.get('direction', 'long'),
                'pnl': float(trade.get('pnl', trade.get('pnl', 0)) or 0),
                'minutes': holding_minutes,
                'hours': holding_minutes / 60,
                'entry_time': entry_dt,
                'close_time': close_dt,
                'close_reason': trade.get('close_reason', 'Unknown'),
                'entry_price': float(trade.get('entry_price', trade.get('entry', 0)) or 0),
                'close_price': float(trade.get('close_price', 0) or 0),
                'amount': float(trade.get('amount', 0) or 0),
                'probability': float(trade.get('probability', 0) or 0),
                'quality_score': float(trade.get('quality_score', 0) or 0)
            })
        
        if skipped_count > 0:
            print(f"⚠️ Пропущено {skipped_count} позиций: {dict(skipped_reasons)}")
        
        self.holding_times_data = holding_times
        return holding_times
    
    def calculate_advanced_stats(self, data: List[float]) -> HoldingTimeStats:
        """Расчет продвинутых статистических метрик"""
        if not data:
            return HoldingTimeStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, (0, 0))
        
        sorted_data = sorted(data)
        n = len(sorted_data)
        
        mean = statistics.mean(data)
        median = statistics.median(data)
        std_dev = statistics.stdev(data) if n > 1 else 0
        
        q25 = sorted_data[n // 4] if n >= 4 else sorted_data[0]
        q75 = sorted_data[3 * n // 4] if n >= 4 else sorted_data[-1]
        iqr = q75 - q25
        
        cv = (std_dev / mean * 100) if mean > 0 else 0  # Коэффициент вариации
        
        # Находим наиболее частый диапазон (модальный интервал)
        bins = 20
        bin_width = (max(data) - min(data)) / bins if max(data) > min(data) else 1
        histogram = Counter()
        for value in data:
            bin_idx = int((value - min(data)) / bin_width) if bin_width > 0 else 0
            bin_idx = min(bin_idx, bins - 1)
            histogram[bin_idx] += 1
        
        if histogram:
            mode_bin = histogram.most_common(1)[0][0]
            mode_start = min(data) + mode_bin * bin_width
            mode_end = mode_start + bin_width
            mode_range = (mode_start, mode_end)
        else:
            mode_range = (0, 0)
        
        return HoldingTimeStats(
            count=n,
            mean=mean,
            median=median,
            std_dev=std_dev,
            min=min(data),
            max=max(data),
            q25=q25,
            q75=q75,
            iqr=iqr,
            cv=cv,
            mode_range=mode_range
        )
    
    def analyze_time_distribution(self) -> Dict[str, Any]:
        """Анализ распределения времени удержания"""
        if not self.holding_times_data:
            return {}
        
        minutes = [t['minutes'] for t in self.holding_times_data]
        stats = self.calculate_advanced_stats(minutes)
        
        # Категоризация по времени
        categories = {
            'scalping_ultra': [t for t in self.holding_times_data if t['minutes'] <= 2],
            'scalping_fast': [t for t in self.holding_times_data if 2 < t['minutes'] <= 5],
            'scalping_normal': [t for t in self.holding_times_data if 5 < t['minutes'] <= 10],
            'short_term': [t for t in self.holding_times_data if 10 < t['minutes'] <= 60],
            'medium_term': [t for t in self.holding_times_data if 60 < t['minutes'] <= 600],
            'long_term': [t for t in self.holding_times_data if t['minutes'] > 600]
        }
        
        category_stats = {}
        for cat_name, cat_trades in categories.items():
            if cat_trades:
                cat_pnl = sum(t['pnl'] for t in cat_trades)
                cat_wins = len([t for t in cat_trades if t['pnl'] > 0])
                cat_total = len(cat_trades)
                cat_wr = (cat_wins / cat_total * 100) if cat_total > 0 else 0
                
                category_stats[cat_name] = {
                    'count': cat_total,
                    'percentage': (cat_total / len(self.holding_times_data) * 100),
                    'total_pnl': cat_pnl,
                    'avg_pnl': cat_pnl / cat_total if cat_total > 0 else 0,
                    'win_rate': cat_wr,
                    'winning_trades': cat_wins,
                    'losing_trades': cat_total - cat_wins
                }
        
        return {
            'overall_stats': stats.to_dict(),
            'categories': category_stats,
            'total_trades': len(self.holding_times_data)
        }
    
    def analyze_profitability_by_time(self) -> Dict[str, Any]:
        """Анализ корреляции между временем удержания и прибыльностью"""
        if not self.holding_times_data:
            return {}
        
        profitable = [t for t in self.holding_times_data if t['pnl'] > 0]
        losing = [t for t in self.holding_times_data if t['pnl'] < 0]
        
        profitable_minutes = [t['minutes'] for t in profitable]
        losing_minutes = [t['minutes'] for t in losing]
        
        profitable_stats = self.calculate_advanced_stats(profitable_minutes) if profitable_minutes else None
        losing_stats = self.calculate_advanced_stats(losing_minutes) if losing_minutes else None
        
        # Корреляция времени и PnL
        if len(self.holding_times_data) > 1:
            minutes_list = [t['minutes'] for t in self.holding_times_data]
            pnl_list = [t['pnl'] for t in self.holding_times_data]
            
            # Простая корреляция Пирсона
            correlation = self._calculate_correlation(minutes_list, pnl_list)
        else:
            correlation = 0
        
        # Анализ оптимального времени удержания
        optimal_time_ranges = self._find_optimal_time_ranges()
        
        return {
            'profitable_stats': profitable_stats.to_dict() if profitable_stats else None,
            'losing_stats': losing_stats.to_dict() if losing_stats else None,
            'correlation_time_pnl': correlation,
            'optimal_time_ranges': optimal_time_ranges,
            'profitable_count': len(profitable),
            'losing_count': len(losing)
        }
    
    def _calculate_correlation(self, x: List[float], y: List[float]) -> float:
        """Расчет корреляции Пирсона"""
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        
        n = len(x)
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        
        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        sum_sq_x = sum((x[i] - mean_x) ** 2 for i in range(n))
        sum_sq_y = sum((y[i] - mean_y) ** 2 for i in range(n))
        
        denominator = math.sqrt(sum_sq_x * sum_sq_y)
        
        if denominator == 0:
            return 0.0
        
        return numerator / denominator
    
    def _find_optimal_time_ranges(self) -> List[Dict[str, Any]]:
        """Поиск оптимальных диапазонов времени удержания"""
        if not self.holding_times_data:
            return []
        
        # Разбиваем на интервалы по 2 минуты
        intervals = defaultdict(lambda: {'trades': [], 'pnl': 0, 'wins': 0})
        
        for trade in self.holding_times_data:
            interval = int(trade['minutes'] // 2) * 2  # Округляем до четного числа
            intervals[interval]['trades'].append(trade)
            intervals[interval]['pnl'] += trade['pnl']
            if trade['pnl'] > 0:
                intervals[interval]['wins'] += 1
        
        optimal_ranges = []
        for interval in sorted(intervals.keys())[:20]:  # Первые 20 интервалов (до 40 минут)
            data = intervals[interval]
            count = len(data['trades'])
            if count >= 5:  # Минимум 5 сделок для статистической значимости
                wr = (data['wins'] / count * 100) if count > 0 else 0
                avg_pnl = data['pnl'] / count if count > 0 else 0
                
                optimal_ranges.append({
                    'time_range': f"{interval}-{interval+2} мин",
                    'count': count,
                    'win_rate': wr,
                    'avg_pnl': avg_pnl,
                    'total_pnl': data['pnl'],
                    'score': wr * 0.6 + (avg_pnl / 10) * 0.4  # Комплексный скор
                })
        
        return sorted(optimal_ranges, key=lambda x: x['score'], reverse=True)[:5]
    
    def analyze_by_symbol(self) -> Dict[str, Any]:
        """Анализ по торговым парам"""
        if not self.holding_times_data:
            return {}
        
        symbol_stats = defaultdict(lambda: {
            'trades': [],
            'total_pnl': 0,
            'wins': 0,
            'total_minutes': 0
        })
        
        for trade in self.holding_times_data:
            symbol = trade['symbol']
            symbol_stats[symbol]['trades'].append(trade)
            symbol_stats[symbol]['total_pnl'] += trade['pnl']
            symbol_stats[symbol]['total_minutes'] += trade['minutes']
            if trade['pnl'] > 0:
                symbol_stats[symbol]['wins'] += 1
        
        result = {}
        for symbol, data in symbol_stats.items():
            count = len(data['trades'])
            if count > 0:
                result[symbol] = {
                    'count': count,
                    'win_rate': (data['wins'] / count * 100),
                    'total_pnl': data['total_pnl'],
                    'avg_pnl': data['total_pnl'] / count,
                    'avg_holding_minutes': data['total_minutes'] / count,
                    'scalping_percentage': len([t for t in data['trades'] if t['minutes'] <= 10]) / count * 100
                }
        
        return result
    
    def analyze_by_time_of_day(self) -> Dict[str, Any]:
        """Анализ эффективности по времени суток"""
        if not self.holding_times_data:
            return {}
        
        hour_stats = defaultdict(lambda: {'trades': [], 'pnl': 0, 'wins': 0, 'total_minutes': 0})
        
        for trade in self.holding_times_data:
            hour = trade['entry_time'].hour
            hour_stats[hour]['trades'].append(trade)
            hour_stats[hour]['pnl'] += trade['pnl']
            hour_stats[hour]['total_minutes'] += trade['minutes']
            if trade['pnl'] > 0:
                hour_stats[hour]['wins'] += 1
        
        result = {}
        for hour in range(24):
            if hour in hour_stats:
                data = hour_stats[hour]
                count = len(data['trades'])
                result[f"{hour:02d}:00"] = {
                    'count': count,
                    'win_rate': (data['wins'] / count * 100) if count > 0 else 0,
                    'avg_pnl': data['pnl'] / count if count > 0 else 0,
                    'total_pnl': data['pnl'],
                    'avg_holding_minutes': data['total_minutes'] / count if count > 0 else 0
                }
        
        return result
    
    def analyze_by_day_of_week(self) -> Dict[str, Any]:
        """Анализ эффективности по дням недели"""
        if not self.holding_times_data:
            return {}
        
        day_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        day_stats = defaultdict(lambda: {'trades': [], 'pnl': 0, 'wins': 0, 'total_minutes': 0})
        
        for trade in self.holding_times_data:
            weekday = trade['entry_time'].weekday()
            day_stats[weekday]['trades'].append(trade)
            day_stats[weekday]['pnl'] += trade['pnl']
            day_stats[weekday]['total_minutes'] += trade['minutes']
            if trade['pnl'] > 0:
                day_stats[weekday]['wins'] += 1
        
        result = {}
        for day_idx, day_name in enumerate(day_names):
            if day_idx in day_stats:
                data = day_stats[day_idx]
                count = len(data['trades'])
                result[day_name] = {
                    'count': count,
                    'win_rate': (data['wins'] / count * 100) if count > 0 else 0,
                    'avg_pnl': data['pnl'] / count if count > 0 else 0,
                    'total_pnl': data['pnl'],
                    'avg_holding_minutes': data['total_minutes'] / count if count > 0 else 0
                }
        
        return result
    
    def generate_recommendations(self) -> List[Recommendation]:
        """Генерация продвинутых рекомендаций с расчетом impact"""
        recommendations = []
        
        if not self.holding_times_data:
            return recommendations
        
        # 1. Анализ времени удержания
        minutes = [t['minutes'] for t in self.holding_times_data]
        stats = self.calculate_advanced_stats(minutes)
        time_dist = self.analyze_time_distribution()
        
        # Рекомендация по среднему времени
        if stats.mean > 10:
            scalping_pct = time_dist['categories'].get('scalping_normal', {}).get('percentage', 0)
            target_mean = 7.0
            potential_improvement = ((stats.mean - target_mean) / stats.mean * 100) if stats.mean > 0 else 0
            
            recommendations.append(Recommendation(
                priority=Priority.CRITICAL,
                category="Время удержания",
                issue=f"Среднее время удержания {stats.mean:.1f} мин превышает целевое для скальпинга ({target_mean} мин)",
                current_value=stats.mean,
                target_value=target_mean,
                recommendation=f"Установить принудительное закрытие через {target_mean} минут. Текущий процент скальпинга: {scalping_pct:.1f}%",
                expected_impact=f"Увеличение процента скальпинга до 80%+, снижение среднего времени на {potential_improvement:.1f}%",
                implementation_effort="Низкая (уже внедрено)",
                confidence=0.95
            ))
        
        # 2. Анализ долгих позиций
        long_term_count = len([t for t in self.holding_times_data if t['minutes'] > 600])
        if long_term_count > 0:
            long_term_pct = (long_term_count / len(self.holding_times_data) * 100)
            recommendations.append(Recommendation(
                priority=Priority.CRITICAL,
                category="Критические позиции",
                issue=f"{long_term_count} позиций ({long_term_pct:.2f}%) удерживались >10 часов",
                current_value=long_term_pct,
                target_value=0.0,
                recommendation="Принудительное закрытие через 10 минут с наивысшим приоритетом",
                expected_impact=f"Устранение {long_term_count} критических случаев, улучшение дисциплины скальпинга",
                implementation_effort="Низкая (уже внедрено)",
                confidence=1.0
            ))
        
        # 3. Анализ оптимального времени
        profitability_analysis = self.analyze_profitability_by_time()
        optimal_ranges = profitability_analysis.get('optimal_time_ranges', [])
        
        if optimal_ranges:
            best_range = optimal_ranges[0]
            if best_range['win_rate'] > 60 and best_range['avg_pnl'] > 0:
                recommendations.append(Recommendation(
                    priority=Priority.HIGH,
                    category="Оптимизация времени",
                    issue=f"Найдено оптимальное время удержания: {best_range['time_range']} (WR: {best_range['win_rate']:.1f}%, Avg PnL: {best_range['avg_pnl']:.2f})",
                    current_value=stats.mean,
                    target_value=float(best_range['time_range'].split('-')[0]) + 1,
                    recommendation=f"Сфокусироваться на закрытии позиций в диапазоне {best_range['time_range']}",
                    expected_impact=f"Потенциальное улучшение Win Rate на {best_range['win_rate'] - (len([t for t in self.holding_times_data if t['pnl'] > 0]) / len(self.holding_times_data) * 100):.1f}%",
                    implementation_effort="Средняя (требует настройки алгоритма)",
                    confidence=0.75
                ))
        
        # 4. Анализ прибыльности по времени
        if profitability_analysis.get('profitable_stats') and profitability_analysis.get('losing_stats'):
            prof_stats = profitability_analysis['profitable_stats']
            loss_stats = profitability_analysis['losing_stats']
            
            if prof_stats['mean'] < loss_stats['mean']:
                recommendations.append(Recommendation(
                    priority=Priority.MEDIUM,
                    category="Управление убытками",
                    issue=f"Прибыльные позиции закрываются быстрее ({prof_stats['mean']:.1f} мин) чем убыточные ({loss_stats['mean']:.1f} мин)",
                    current_value=loss_stats['mean'],
                    target_value=prof_stats['mean'] * 1.2,
                    recommendation=f"Добавить автоматическое закрытие убыточных позиций через {prof_stats['mean'] * 1.2:.1f} минут",
                    expected_impact=f"Сокращение среднего времени убыточных позиций на {(loss_stats['mean'] - prof_stats['mean'] * 1.2) / loss_stats['mean'] * 100:.1f}%",
                    implementation_effort="Низкая",
                    confidence=0.80
                ))
        
        # 5. Анализ по парам
        symbol_analysis = self.analyze_by_symbol()
        problematic_symbols = [
            (sym, data) for sym, data in symbol_analysis.items()
            if data['avg_holding_minutes'] > 60 and data['win_rate'] < 50
        ]
        
        if problematic_symbols:
            worst = sorted(problematic_symbols, key=lambda x: x[1]['avg_holding_minutes'], reverse=True)[0]
            recommendations.append(Recommendation(
                priority=Priority.MEDIUM,
                category="Проблемные пары",
                issue=f"{worst[0]}: среднее время {worst[1]['avg_holding_minutes']:.1f} мин, WR {worst[1]['win_rate']:.1f}%",
                current_value=worst[1]['avg_holding_minutes'],
                target_value=10.0,
                recommendation=f"Добавить специальные фильтры для {worst[0]} или исключить из торговли",
                expected_impact=f"Улучшение среднего времени удержания для проблемных пар",
                implementation_effort="Средняя",
                confidence=0.70
            ))
        
        # 6. Анализ коэффициента вариации
        if stats.cv > 100:
            recommendations.append(Recommendation(
                priority=Priority.MEDIUM,
                category="Стабильность",
                issue=f"Высокая вариативность времени удержания (CV: {stats.cv:.1f}%)",
                current_value=stats.cv,
                target_value=50.0,
                recommendation="Унифицировать логику закрытия позиций, добавить строгие временные лимиты",
                expected_impact=f"Снижение вариативности на {(stats.cv - 50) / stats.cv * 100:.1f}%, повышение предсказуемости",
                implementation_effort="Средняя",
                confidence=0.65
            ))
        
        # 7. Анализ аномалий
        anomalies = self.detect_anomalies()
        if anomalies.get('time_outliers', {}).get('count', 0) > 10:
            outliers_count = anomalies['time_outliers']['count']
            outliers_pct = (outliers_count / len(self.holding_times_data) * 100) if self.holding_times_data else 0
            recommendations.append(Recommendation(
                priority=Priority.HIGH,
                category="Аномалии",
                issue=f"{outliers_count} позиций ({outliers_pct:.1f}%) являются выбросами по времени удержания",
                current_value=outliers_pct,
                target_value=2.0,  # Не более 2% выбросов
                recommendation="Усилить принудительное закрытие, добавить мониторинг аномалий в реальном времени",
                expected_impact=f"Сокращение выбросов с {outliers_pct:.1f}% до <2%, улучшение дисциплины скальпинга",
                implementation_effort="Средняя",
                confidence=0.85
            ))
        
        # 8. Анализ по времени суток
        time_of_day = self.analyze_by_time_of_day()
        if time_of_day:
            best_hours = sorted(
                [(h, d) for h, d in time_of_day.items() if d['count'] >= 10],
                key=lambda x: x[1]['win_rate'] * 0.6 + (x[1]['avg_pnl'] / 100) * 0.4,
                reverse=True
            )[:3]
            
            worst_hours = sorted(
                [(h, d) for h, d in time_of_day.items() if d['count'] >= 10],
                key=lambda x: x[1]['win_rate'] * 0.6 + (x[1]['avg_pnl'] / 100) * 0.4
            )[:3]
            
            if worst_hours and best_hours:
                worst = worst_hours[0]
                best = best_hours[0]
                wr_diff = best[1]['win_rate'] - worst[1]['win_rate']
                if wr_diff > 15:
                    recommendations.append(Recommendation(
                        priority=Priority.LOW,
                        category="Время суток",
                        issue=f"Значительная разница в эффективности: {worst[0]} (WR: {worst[1]['win_rate']:.1f}%) vs {best[0]} (WR: {best[1]['win_rate']:.1f}%)",
                        current_value=worst[1]['win_rate'],
                        target_value=best[1]['win_rate'],
                        recommendation=f"Рассмотреть снижение активности в {worst[0]} или добавление специальных фильтров. Увеличить активность в {best[0]}",
                        expected_impact=f"Потенциальное улучшение Win Rate на {wr_diff:.1f}% в проблемные часы",
                        implementation_effort="Низкая",
                        confidence=0.60
                    ))
        
        # 9. Анализ по дням недели
        day_of_week = self.analyze_by_day_of_week()
        if day_of_week:
            days_with_data = [(d, data) for d, data in day_of_week.items() if data['count'] >= 20]
            if len(days_with_data) >= 3:
                best_day = max(days_with_data, key=lambda x: x[1]['win_rate'])
                worst_day = min(days_with_data, key=lambda x: x[1]['win_rate'])
                
                if best_day[1]['win_rate'] - worst_day[1]['win_rate'] > 20:
                    recommendations.append(Recommendation(
                        priority=Priority.LOW,
                        category="Дни недели",
                        issue=f"Разница в эффективности: {worst_day[0]} (WR: {worst_day[1]['win_rate']:.1f}%) vs {best_day[0]} (WR: {best_day[1]['win_rate']:.1f}%)",
                        current_value=worst_day[1]['win_rate'],
                        target_value=best_day[1]['win_rate'],
                        recommendation=f"Снизить активность в {worst_day[0]}, увеличить в {best_day[0]}",
                        expected_impact=f"Улучшение среднего Win Rate на {(best_day[1]['win_rate'] - worst_day[1]['win_rate']) / 2:.1f}%",
                        implementation_effort="Низкая",
                        confidence=0.55
                    ))
        
        # 10. Анализ эффективности по вероятности сигнала
        if any(t.get('probability', 0) > 0 for t in self.holding_times_data):
            prob_ranges = {
                'high': [t for t in self.holding_times_data if t.get('probability', 0) >= 60],
                'medium': [t for t in self.holding_times_data if 40 <= t.get('probability', 0) < 60],
                'low': [t for t in self.holding_times_data if 0 < t.get('probability', 0) < 40]
            }
            
            for prob_level, trades in prob_ranges.items():
                if len(trades) >= 20:
                    wins = len([t for t in trades if t['pnl'] > 0])
                    wr = (wins / len(trades) * 100) if trades else 0
                    avg_pnl = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
                    
                    if prob_level == 'low' and wr < 40:
                        recommendations.append(Recommendation(
                            priority=Priority.MEDIUM,
                            category="Фильтрация сигналов",
                            issue=f"Низкая вероятность сигналов (<40%) показывает WR {wr:.1f}% и Avg PnL {avg_pnl:.2f} USDT",
                            current_value=wr,
                            target_value=50.0,
                            recommendation=f"Исключить сигналы с вероятностью <40% из торговли",
                            expected_impact=f"Улучшение Win Rate на {50 - wr:.1f}%, сокращение убыточных сделок",
                            implementation_effort="Низкая",
                            confidence=0.75
                        ))
                        break
        
        # Сортируем рекомендации по приоритету и уверенности
        priority_order_list = [Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM, Priority.LOW, Priority.INFO]
        recommendations.sort(key=lambda r: (
            priority_order_list.index(r.priority),
            -r.confidence
        ))
        
        return recommendations
    
    def _export_to_csv(self, filepath: str) -> None:
        """Экспорт детальных данных в CSV"""
        if not self.holding_times_data:
            return
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'symbol', 'direction', 'entry_time', 'close_time', 'holding_minutes', 
                'holding_hours', 'entry_price', 'close_price', 'pnl', 'close_reason',
                'probability', 'quality_score'
            ])
            writer.writeheader()
            
            for trade in self.holding_times_data:
                writer.writerow({
                    'symbol': trade['symbol'],
                    'direction': trade['direction'],
                    'entry_time': trade['entry_time'].isoformat() if isinstance(trade['entry_time'], datetime) else str(trade['entry_time']),
                    'close_time': trade['close_time'].isoformat() if isinstance(trade['close_time'], datetime) else str(trade['close_time']),
                    'holding_minutes': round(trade['minutes'], 2),
                    'holding_hours': round(trade['hours'], 2),
                    'entry_price': trade['entry_price'],
                    'close_price': trade['close_price'],
                    'pnl': round(trade['pnl'], 2),
                    'close_reason': trade['close_reason'],
                    'probability': trade['probability'],
                    'quality_score': trade['quality_score']
                })
    
    def _export_to_markdown(self, report: Dict[str, Any], filepath: str) -> None:
        """Экспорт отчета в Markdown формат"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("# 📊 Профессиональный анализ торговых позиций\n\n")
            f.write(f"**Дата анализа**: {report['analysis_date']}\n")
            f.write(f"**User ID**: {report['user_id']}\n\n")
            
            # Сводка
            f.write("## 📈 Сводка\n\n")
            f.write(f"- Закрытых позиций: **{report['summary']['total_closed']}**\n")
            f.write(f"- Открытых позиций: **{report['summary']['total_open']}**\n\n")
            
            # Статистика времени
            if report.get('time_distribution'):
                f.write("## ⏱️ Статистика времени удержания\n\n")
                stats = report['time_distribution']['overall_stats']
                f.write(f"- Среднее: **{stats['mean']:.2f}** минут\n")
                f.write(f"- Медиана: **{stats['median']:.2f}** минут\n")
                f.write(f"- Стандартное отклонение: **{stats['std_dev']:.2f}** минут\n")
                f.write(f"- Коэффициент вариации: **{stats['cv']:.2f}%**\n\n")
                
                f.write("### Распределение по категориям\n\n")
                f.write("| Категория | Количество | % | Win Rate | Avg PnL |\n")
                f.write("|-----------|------------|---|----------|----------|\n")
                
                categories = report['time_distribution']['categories']
                for cat_name, cat_data in categories.items():
                    f.write(f"| {cat_name} | {cat_data['count']} | {cat_data['percentage']:.1f}% | "
                           f"{cat_data['win_rate']:.1f}% | {cat_data['avg_pnl']:.2f} USDT |\n")
                f.write("\n")
            
            # Рекомендации
            if report.get('recommendations'):
                f.write("## 💡 Рекомендации\n\n")
                for rec in report['recommendations']:
                    priority_emoji = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(rec['priority'], '⚪')
                    f.write(f"### {priority_emoji} [{rec['priority']}] {rec['category']}\n\n")
                    f.write(f"**Проблема**: {rec['issue']}\n\n")
                    if rec.get('current_value') and rec.get('target_value'):
                        f.write(f"**Текущее значение**: {rec['current_value']:.2f}\n")
                        f.write(f"**Целевое значение**: {rec['target_value']:.2f}\n\n")
                    f.write(f"**Рекомендация**: {rec['recommendation']}\n\n")
                    f.write(f"**Ожидаемый эффект**: {rec['expected_impact']}\n\n")
                    f.write(f"**Сложность**: {rec['implementation_effort']} | **Уверенность**: {rec['confidence']*100:.0f}%\n\n")
                    f.write("---\n\n")
    
    def detect_anomalies(self) -> Dict[str, Any]:
        """Обнаружение аномалий в данных"""
        if not self.holding_times_data:
            return {}
        
        minutes = [t['minutes'] for t in self.holding_times_data]
        stats = self.calculate_advanced_stats(minutes)
        
        # Аномалии по времени (выбросы)
        outliers = []
        for trade in self.holding_times_data:
            # Используем правило 1.5 * IQR
            if trade['minutes'] > stats.q75 + 1.5 * stats.iqr:
                outliers.append(trade)
        
        # Аномалии по PnL (необычно большие прибыли/убытки)
        pnl_values = [t['pnl'] for t in self.holding_times_data]
        if pnl_values:
            pnl_mean = statistics.mean(pnl_values)
            pnl_std = statistics.stdev(pnl_values) if len(pnl_values) > 1 else 0
            
            extreme_pnl = []
            for trade in self.holding_times_data:
                if pnl_std > 0:
                    z_score = abs((trade['pnl'] - pnl_mean) / pnl_std)
                    if z_score > 3:  # Более 3 стандартных отклонений
                        extreme_pnl.append({
                            **trade,
                            'z_score': z_score
                        })
        
        return {
            'time_outliers': {
                'count': len(outliers),
                'threshold_minutes': stats.q75 + 1.5 * stats.iqr,
                'examples': sorted(outliers, key=lambda x: x['minutes'], reverse=True)[:10]
            },
            'extreme_pnl': {
                'count': len(extreme_pnl),
                'examples': sorted(extreme_pnl, key=lambda x: abs(x['pnl']), reverse=True)[:10]
            }
        }
    
    def analyze_open_positions(self) -> Dict[str, Any]:
        """Анализ открытых позиций"""
        if not self.open_trades:
            return {'count': 0, 'positions': []}
        
        current_time = datetime.now()
        positions = []
        
        for trade in self.open_trades:
            entry_dt = self.parse_datetime(trade.get('entry_time'))
            if not entry_dt:
                continue
            
            holding_minutes = (current_time - entry_dt).total_seconds() / 60
            
            positions.append({
                'symbol': trade.get('symbol'),
                'direction': trade.get('direction'),
                'entry': trade.get('entry', 0),
                'minutes': holding_minutes,
                'hours': holding_minutes / 60,
                'entry_time': entry_dt.isoformat(),
                'status': 'CRITICAL' if holding_minutes > 600 else 'WARNING' if holding_minutes > 60 else 'NORMAL'
            })
        
        return {
            'count': len(positions),
            'positions': sorted(positions, key=lambda x: x['minutes'], reverse=True),
            'avg_minutes': sum(p['minutes'] for p in positions) / len(positions) if positions else 0,
            'critical_count': len([p for p in positions if p['minutes'] > 600])
        }
    
    def generate_report(self) -> Dict[str, Any]:
        """Генерация полного отчета"""
        self.load_data()
        holding_times = self.calculate_holding_times()
        
        report = {
            'analysis_date': datetime.now().isoformat(),
            'user_id': self.user_id,
            'summary': {
                'total_closed': len(holding_times),
                'total_open': len(self.open_trades)
            },
            'time_distribution': self.analyze_time_distribution(),
            'profitability_analysis': self.analyze_profitability_by_time(),
            'symbol_analysis': self.analyze_by_symbol(),
            'time_of_day_analysis': self.analyze_by_time_of_day(),
            'day_of_week_analysis': self.analyze_by_day_of_week(),
            'open_positions': self.analyze_open_positions(),
            'anomalies': self.detect_anomalies(),
            'recommendations': [r.to_dict() for r in self.generate_recommendations()]
        }
        
        return report
    
    def print_report(self, report: Dict[str, Any]) -> None:
        """Красивый вывод отчета в консоль"""
        print("=" * 100)
        print("📊 ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ ТОРГОВЫХ ПОЗИЦИЙ")
        print("=" * 100)
        
        # Сводка
        print(f"\n📈 СВОДКА:")
        print(f"  Закрытых позиций: {report['summary']['total_closed']}")
        print(f"  Открытых позиций: {report['summary']['total_open']}")
        
        # Статистика времени
        if report['time_distribution']:
            stats = report['time_distribution']['overall_stats']
            print(f"\n⏱️  СТАТИСТИКА ВРЕМЕНИ УДЕРЖАНИЯ:")
            print(f"  Среднее: {stats['mean']:.2f} мин (медиана: {stats['median']:.2f} мин)")
            print(f"  Стандартное отклонение: {stats['std_dev']:.2f} мин")
            print(f"  Коэффициент вариации: {stats['cv']:.2f}%")
            print(f"  Квартили: Q1={stats['q25']:.1f} мин, Q3={stats['q75']:.1f} мин, IQR={stats['iqr']:.1f} мин")
            print(f"  Наиболее частый диапазон: {stats['mode_range'][0]:.1f}-{stats['mode_range'][1]:.1f} мин")
            
            # Распределение по категориям
            print(f"\n  📊 Распределение:")
            categories = report['time_distribution']['categories']
            for cat_name, cat_data in categories.items():
                emoji = "✅" if "scalping" in cat_name else "⚠️" if "short" in cat_name else "❌"
                print(f"    {emoji} {cat_name:20s}: {cat_data['count']:4d} ({cat_data['percentage']:5.1f}%) | "
                      f"WR: {cat_data['win_rate']:5.1f}% | Avg PnL: {cat_data['avg_pnl']:8.2f} USDT")
        
        # Анализ прибыльности
        if report['profitability_analysis']:
            prof_analysis = report['profitability_analysis']
            print(f"\n💰 АНАЛИЗ ПРИБЫЛЬНОСТИ:")
            if prof_analysis.get('correlation_time_pnl'):
                corr = prof_analysis['correlation_time_pnl']
                corr_interpretation = "сильная" if abs(corr) > 0.7 else "умеренная" if abs(corr) > 0.4 else "слабая"
                direction = "положительная" if corr > 0 else "отрицательная"
                print(f"  Корреляция время-PnL: {corr:.3f} ({corr_interpretation}, {direction})")
            
            if prof_analysis.get('optimal_time_ranges'):
                print(f"\n  🎯 Оптимальные диапазоны времени:")
                for i, opt_range in enumerate(prof_analysis['optimal_time_ranges'][:3], 1):
                    print(f"    {i}. {opt_range['time_range']:15s} | "
                          f"WR: {opt_range['win_rate']:5.1f}% | "
                          f"Avg PnL: {opt_range['avg_pnl']:8.2f} USDT | "
                          f"Сделок: {opt_range['count']}")
        
        # Анализ по дням недели
        if report.get('day_of_week_analysis'):
            print(f"\n📅 АНАЛИЗ ПО ДНЯМ НЕДЕЛИ:")
            day_analysis = report['day_of_week_analysis']
            for day_name, day_data in sorted(day_analysis.items(), key=lambda x: x[1]['win_rate'], reverse=True):
                if day_data['count'] >= 10:  # Минимум 10 сделок для статистики
                    print(f"  {day_name:15s} | Сделок: {day_data['count']:3d} | "
                          f"WR: {day_data['win_rate']:5.1f}% | "
                          f"Avg PnL: {day_data['avg_pnl']:8.2f} USDT | "
                          f"Ср. время: {day_data['avg_holding_minutes']:5.1f} мин")
        
        # Анализ аномалий
        if report.get('anomalies'):
            anomalies = report['anomalies']
            print(f"\n🔍 ОБНАРУЖЕНИЕ АНОМАЛИЙ:")
            
            if anomalies.get('time_outliers', {}).get('count', 0) > 0:
                outliers = anomalies['time_outliers']
                print(f"  ⚠️ Выбросы по времени: {outliers['count']} позиций > {outliers['threshold_minutes']:.1f} мин")
                if outliers.get('examples'):
                    print(f"    Топ-3 примера:")
                    for ex in outliers['examples'][:3]:
                        print(f"      {ex['symbol']:20s} | {ex['hours']:6.1f} часов | PnL: {ex['pnl']:8.2f} USDT")
            
            if anomalies.get('extreme_pnl', {}).get('count', 0) > 0:
                extreme = anomalies['extreme_pnl']
                print(f"  💰 Экстремальные PnL: {extreme['count']} позиций (Z-score > 3)")
                if extreme.get('examples'):
                    print(f"    Топ-3 примера:")
                    for ex in extreme['examples'][:3]:
                        print(f"      {ex['symbol']:20s} | PnL: {ex['pnl']:8.2f} USDT | Z-score: {ex.get('z_score', 0):.2f}")
        
        # Открытые позиции
        if report['open_positions']['count'] > 0:
            print(f"\n🔴 ОТКРЫТЫЕ ПОЗИЦИИ ({report['open_positions']['count']}):")
            for pos in report['open_positions']['positions'][:10]:
                status_emoji = "🔴" if pos['status'] == 'CRITICAL' else "🟡" if pos['status'] == 'WARNING' else "🟢"
                print(f"  {status_emoji} {pos['symbol']:20s} | {pos['hours']:6.1f} часов | {pos['direction'].upper()}")
        
        # Рекомендации
        if report['recommendations']:
            print(f"\n" + "=" * 100)
            print(f"💡 РЕКОМЕНДАЦИИ (приоритизированы по impact):")
            print("=" * 100)
            
            priority_order = [Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM, Priority.LOW, Priority.INFO]
            priority_emoji = {
                Priority.CRITICAL: '🔴',
                Priority.HIGH: '🟠',
                Priority.MEDIUM: '🟡',
                Priority.LOW: '🟢',
                Priority.INFO: '⚪'
            }
            
            for priority in priority_order:
                recs = [r for r in report['recommendations'] if r['priority'] == priority.value]
                if recs:
                    print(f"\n{priority_emoji[priority]} [{priority.value}]")
                    for rec in recs:
                        print(f"  📌 {rec['category']}: {rec['issue']}")
                        if rec.get('current_value') and rec.get('target_value'):
                            print(f"     Текущее: {rec['current_value']:.2f} → Целевое: {rec['target_value']:.2f}")
                        print(f"     💡 {rec['recommendation']}")
                        print(f"     📈 Ожидаемый эффект: {rec['expected_impact']}")
                        print(f"     ⚙️  Сложность: {rec['implementation_effort']} | Уверенность: {rec['confidence']*100:.0f}%")
                        print()


def analyze_positions_detailed(user_id: int = 8486449177):
    """Главная функция анализа"""
    try:
        analyzer = PositionAnalyzer(user_id)
        report = analyzer.generate_report()
        analyzer.print_report(report)
        
        # Сохранение отчета в разных форматах
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # JSON отчет
        json_path = f'positions_analysis_report_{timestamp}.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n✅ JSON отчет сохранен: {json_path}")
        
        # CSV экспорт позиций
        if analyzer.holding_times_data:
            csv_path = f'positions_detailed_{timestamp}.csv'
            analyzer._export_to_csv(csv_path)
            print(f"✅ CSV экспорт сохранен: {csv_path}")
        
        # Markdown отчет
        md_path = f'positions_analysis_report_{timestamp}.md'
        analyzer._export_to_markdown(report, md_path)
        print(f"✅ Markdown отчет сохранен: {md_path}")
        
        print("=" * 100)
        
    except Exception as e:
        print(f"❌ Ошибка анализа: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    analyze_positions_detailed()
