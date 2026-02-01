#!/usr/bin/env python3
"""
Глубокий анализ торговых сделок и рекомендации по улучшению бота
"""
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict
from data.database import get_database
from data.user_data import UserDataManager

def analyze_trades(user_id: int = 8486449177):
    """Анализирует сделки и генерирует рекомендации"""
    
    db = get_database()
    user_data = UserDataManager()
    
    # Получаем все закрытые сделки
    closed_trades = db.get_closed_trades(user_id, limit=10000)
    
    if not closed_trades:
        print("❌ Нет закрытых сделок для анализа")
        return
    
    print(f"📊 АНАЛИЗ {len(closed_trades)} ЗАКРЫТЫХ СДЕЛОК\n")
    print("=" * 80)
    
    # Базовые метрики
    total_trades = len(closed_trades)
    winning_trades = [t for t in closed_trades if t.get('pnl', 0) > 0]
    losing_trades = [t for t in closed_trades if t.get('pnl', 0) < 0]
    
    total_profit = sum([t.get('pnl', 0) for t in winning_trades])
    total_loss = abs(sum([t.get('pnl', 0) for t in losing_trades]))
    net_profit = total_profit - total_loss
    
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else 0
    
    avg_win = total_profit / len(winning_trades) if winning_trades else 0
    avg_loss = total_loss / len(losing_trades) if losing_trades else 0
    
    print(f"\n📈 БАЗОВЫЕ МЕТРИКИ:")
    print(f"  Всего сделок: {total_trades}")
    print(f"  Прибыльных: {len(winning_trades)} ({win_rate:.2f}%)")
    print(f"  Убыточных: {len(losing_trades)} ({100-win_rate:.2f}%)")
    print(f"  Чистая прибыль: {net_profit:.2f} USDT")
    print(f"  Profit Factor: {profit_factor:.2f}")
    print(f"  Средний выигрыш: {avg_win:.2f} USDT")
    print(f"  Средний проигрыш: {avg_loss:.2f} USDT")
    print(f"  Соотношение Win/Loss: {avg_win/avg_loss:.2f}" if avg_loss > 0 else "  Соотношение Win/Loss: N/A")
    
    # Анализ по парам
    pair_stats = defaultdict(lambda: {'total': 0, 'wins': 0, 'losses': 0, 'pnl': 0, 'long': 0, 'short': 0})
    
    for trade in closed_trades:
        symbol = trade.get('symbol', 'UNKNOWN')
        pnl = trade.get('pnl', 0)
        direction = trade.get('direction', 'long')
        
        pair_stats[symbol]['total'] += 1
        pair_stats[symbol]['pnl'] += pnl
        if direction == 'long':
            pair_stats[symbol]['long'] += 1
        else:
            pair_stats[symbol]['short'] += 1
        
        if pnl > 0:
            pair_stats[symbol]['wins'] += 1
        else:
            pair_stats[symbol]['losses'] += 1
    
    print(f"\n📊 АНАЛИЗ ПО ПАРАМ:")
    print("-" * 80)
    sorted_pairs = sorted(pair_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
    
    for symbol, stats in sorted_pairs[:10]:
        wr = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"  {symbol:20s} | Сделок: {stats['total']:3d} | Win Rate: {wr:5.1f}% | PnL: {stats['pnl']:8.2f} USDT | LONG: {stats['long']:2d} | SHORT: {stats['short']:2d}")
    
    # Анализ по направлениям
    long_trades = [t for t in closed_trades if t.get('direction') == 'long']
    short_trades = [t for t in closed_trades if t.get('direction') == 'short']
    
    long_wins = [t for t in long_trades if t.get('pnl', 0) > 0]
    short_wins = [t for t in short_trades if t.get('pnl', 0) > 0]
    
    long_wr = (len(long_wins) / len(long_trades) * 100) if long_trades else 0
    short_wr = (len(short_wins) / len(short_trades) * 100) if short_trades else 0
    
    long_pnl = sum([t.get('pnl', 0) for t in long_trades])
    short_pnl = sum([t.get('pnl', 0) for t in short_trades])
    
    print(f"\n🔄 АНАЛИЗ ПО НАПРАВЛЕНИЯМ:")
    print(f"  LONG:")
    print(f"    Сделок: {len(long_trades)} | Win Rate: {long_wr:.2f}% | PnL: {long_pnl:.2f} USDT")
    print(f"  SHORT:")
    print(f"    Сделок: {len(short_trades)} | Win Rate: {short_wr:.2f}% | PnL: {short_pnl:.2f} USDT")
    
    # Анализ причин закрытия
    close_reasons = defaultdict(int)
    for trade in closed_trades:
        reason = trade.get('close_reason', 'Unknown')
        close_reasons[reason] += 1
    
    print(f"\n🎯 ПРИЧИНЫ ЗАКРЫТИЯ:")
    for reason, count in sorted(close_reasons.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_trades * 100) if total_trades > 0 else 0
        print(f"  {reason:40s}: {count:3d} ({pct:.1f}%)")
    
    # Анализ времени удержания (если есть данные)
    holding_times = []
    for trade in closed_trades:
        entry_time = trade.get('entry_time')
        close_time = trade.get('close_time')
        if entry_time and close_time:
            try:
                if isinstance(entry_time, str):
                    entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                else:
                    entry_dt = datetime.fromtimestamp(entry_time)
                
                if isinstance(close_time, str):
                    close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                else:
                    close_dt = datetime.fromtimestamp(close_time)
                
                holding_time = (close_dt - entry_dt).total_seconds() / 60  # в минутах
                holding_times.append((holding_time, trade.get('pnl', 0)))
            except:
                pass
    
    if holding_times:
        avg_holding = sum([t[0] for t in holding_times]) / len(holding_times)
        winning_holding = [t[0] for t in holding_times if t[1] > 0]
        losing_holding = [t[0] for t in holding_times if t[1] < 0]
        
        avg_win_holding = sum(winning_holding) / len(winning_holding) if winning_holding else 0
        avg_loss_holding = sum(losing_holding) / len(losing_holding) if losing_holding else 0
        
        print(f"\n⏱️  ВРЕМЯ УДЕРЖАНИЯ:")
        print(f"  Среднее время удержания: {avg_holding:.1f} минут")
        print(f"  Среднее время прибыльных: {avg_win_holding:.1f} минут")
        print(f"  Среднее время убыточных: {avg_loss_holding:.1f} минут")
    
    # Генерация рекомендаций
    print(f"\n" + "=" * 80)
    print(f"💡 РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ:")
    print("=" * 80)
    
    recommendations = []
    
    # 1. Win Rate
    if win_rate < 40:
        recommendations.append({
            'priority': 'HIGH',
            'issue': f'Низкий Win Rate ({win_rate:.1f}%)',
            'recommendation': 'Увеличить порог вероятности для открытия позиций (минимум 55-60%), добавить больше фильтров подтверждения сигналов'
        })
    elif win_rate < 50:
        recommendations.append({
            'priority': 'MEDIUM',
            'issue': f'Win Rate ниже 50% ({win_rate:.1f}%)',
            'recommendation': 'Улучшить фильтрацию сигналов, добавить проверку тренда на старших таймфреймах'
        })
    
    # 2. Profit Factor
    if profit_factor < 1.0:
        recommendations.append({
            'priority': 'CRITICAL',
            'issue': f'Profit Factor < 1.0 ({profit_factor:.2f}) - бот убыточен',
            'recommendation': 'Срочно пересмотреть стратегию. Увеличить соотношение R/R до 1:4 или выше, улучшить точность входов'
        })
    elif profit_factor < 1.5:
        recommendations.append({
            'priority': 'HIGH',
            'issue': f'Profit Factor низкий ({profit_factor:.2f})',
            'recommendation': 'Улучшить соотношение риск/прибыль, увеличить TP или уменьшить SL'
        })
    
    # 3. Соотношение Win/Loss
    if avg_loss > 0 and avg_win / avg_loss < 1.5:
        recommendations.append({
            'priority': 'HIGH',
            'issue': f'Средний выигрыш слишком мал относительно проигрыша ({avg_win/avg_loss:.2f})',
            'recommendation': 'Увеличить целевое соотношение R/R с 1:3 до 1:4 или выше, использовать trailing stop для прибыльных позиций'
        })
    
    # 4. Анализ по парам
    worst_pairs = [p for p in sorted_pairs if p[1]['pnl'] < -50]
    if worst_pairs:
        recommendations.append({
            'priority': 'MEDIUM',
            'issue': f'Проблемные пары: {", ".join([p[0] for p in worst_pairs[:3]])}',
            'recommendation': 'Исключить эти пары из торговли или добавить специальные фильтры для них'
        })
    
    best_pairs = [p for p in sorted_pairs[:5] if p[1]['pnl'] > 0 and p[1]['wins'] / p[1]['total'] > 0.5]
    if best_pairs:
        recommendations.append({
            'priority': 'LOW',
            'issue': f'Лучшие пары: {", ".join([p[0] for p in best_pairs[:3]])}',
            'recommendation': 'Увеличить приоритет этих пар, возможно увеличить размер позиции для них'
        })
    
    # 5. Направления
    if len(long_trades) > 0 and len(short_trades) > 0:
        if abs(long_wr - short_wr) > 15:
            better = 'LONG' if long_wr > short_wr else 'SHORT'
            recommendations.append({
                'priority': 'MEDIUM',
                'issue': f'Значительная разница в Win Rate между LONG ({long_wr:.1f}%) и SHORT ({short_wr:.1f}%)',
                'recommendation': f'Сфокусироваться на {better} позициях, добавить фильтры для улучшения слабого направления'
            })
    
    # 6. Причины закрытия
    sl_count = sum([count for reason, count in close_reasons.items() if 'Stop Loss' in reason or 'SL' in reason])
    tp_count = sum([count for reason, count in close_reasons.items() if 'Take Profit' in reason or 'TP' in reason])
    
    if sl_count > tp_count * 1.5:
        recommendations.append({
            'priority': 'HIGH',
            'issue': f'Слишком много закрытий по SL ({sl_count}) vs TP ({tp_count})',
            'recommendation': 'Улучшить точность входов, добавить фильтр по тренду, увеличить дистанцию SL на основе ATR'
        })
    
    # 7. Время удержания
    if holding_times and avg_win_holding > 0 and avg_loss_holding > 0:
        if avg_loss_holding > avg_win_holding * 1.5:
            recommendations.append({
                'priority': 'MEDIUM',
                'issue': f'Убыточные позиции удерживаются дольше ({avg_loss_holding:.1f} мин) чем прибыльные ({avg_win_holding:.1f} мин)',
                'recommendation': 'Добавить автоматическое закрытие убыточных позиций через определенное время, улучшить trailing stop'
            })
    
    # Выводим рекомендации
    for i, rec in enumerate(recommendations, 1):
        priority_emoji = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(rec['priority'], '⚪')
        print(f"\n{priority_emoji} [{rec['priority']}] {rec['issue']}")
        print(f"   💡 {rec['recommendation']}")
    
    if not recommendations:
        print("\n✅ Все метрики в норме! Бот работает хорошо.")
    
    # Дополнительные улучшения
    print(f"\n" + "=" * 80)
    print(f"🚀 ДОПОЛНИТЕЛЬНЫЕ УЛУЧШЕНИЯ:")
    print("=" * 80)
    
    improvements = [
        "1. Добавить адаптивный размер позиции на основе волатильности (ATR)",
        "2. Внедрить систему ранжирования пар по исторической производительности",
        "3. Добавить фильтр по времени суток (избегать низколиквидных периодов)",
        "4. Реализовать динамическое управление риском на основе текущего drawdown",
        "5. Добавить анализ корреляции между парами для избежания переэкспозиции",
        "6. Внедрить machine learning для улучшения предсказания вероятности",
        "7. Добавить backtesting на исторических данных перед внедрением изменений",
        "8. Реализовать систему A/B тестирования разных стратегий",
        "9. Добавить мониторинг рыночных условий (тренд/флэт) и адаптацию стратегии",
        "10. Внедрить автоматическую оптимизацию параметров SL/TP на основе результатов"
    ]
    
    for improvement in improvements:
        print(f"  {improvement}")
    
    print(f"\n" + "=" * 80)

if __name__ == "__main__":
    analyze_trades()
