from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from services.bingx_api import BingXAPI
from data.user_data import UserDataManager
from data.database import get_database
import math


class StatisticsManager:
    """Менеджер статистики торговли"""
    
    def __init__(self, api: Optional[BingXAPI], user_id: int):
        self.api = api
        self.user_id = user_id
        self.user_data = UserDataManager()
        # Используем БД для хранения сделок
        try:
            self.db = get_database()
            self.use_database = True
        except Exception as e:
            print(f"[StatisticsManager] ⚠️ БД недоступна: {e}, используем user_data")
            self.db = None
            self.use_database = False
        
        # Загружаем демо-позиции из user_data (для обратной совместимости)
        self.demo_trades = self.user_data.get_demo_positions(user_id)
    
    async def get_balance_info(self, is_demo: bool = False, demo_balance: float = 10000) -> Dict[str, Any]:
        """Получить информацию о балансе"""
        if is_demo:
            # В демо-режиме используем виртуальный баланс
            positions = await self._get_demo_positions()
            total_pnl = sum([p.get('unrealized_pnl', 0) for p in positions])
            
            return {
                'total': demo_balance + total_pnl,
                'free': demo_balance,
                'used': abs(total_pnl) if total_pnl < 0 else 0,
                'equity': demo_balance + total_pnl,
                'unrealized_pnl': total_pnl,
                'is_demo': True
            }
        
        try:
            balance = await self.api.get_balance()
            positions = await self.api.get_positions()
            
            # Рассчитываем unrealized P&L
            total_pnl = sum([pos.get('unrealizedPnl', 0) or 0 for pos in positions])
            
            return {
                'total': balance['total'],
                'free': balance['free'],
                'used': balance['used'],
                'equity': balance['total'] + total_pnl,
                'unrealized_pnl': total_pnl,
                'open_positions': len(positions),
                'is_demo': False
            }
        except Exception as e:
            return {
                'error': str(e),
                'is_demo': False
            }
    
    async def get_statistics(self, period: str = '24h', is_demo: bool = False) -> Dict[str, Any]:
        """
        Получить статистику за период
        
        Args:
            period: '1h', '24h', '7d', '30d', 'all'
        """
        trades = await self._get_trades_for_period(period, is_demo)
        
        if not trades:
            return {
                'period': period,
                'total_trades': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'total_profit': 0,
                'max_drawdown': 0
            }
        
        # Рассчитываем метрики
        winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in trades if t.get('pnl', 0) < 0]
        
        total_profit = sum([t.get('pnl', 0) for t in winning_trades])
        total_loss = abs(sum([t.get('pnl', 0) for t in losing_trades]))
        
        win_rate = (len(winning_trades) / len(trades) * 100) if trades else 0
        profit_factor = (total_profit / total_loss) if total_loss > 0 else 0
        
        # Максимальная просадка
        max_drawdown = self._calculate_max_drawdown(trades)

        # Sharpe (упрощённо по серии PnL на сделку; без привязки к risk-free)
        sharpe = self._calculate_sharpe(trades)
        
        return {
            'period': period,
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': round(win_rate, 2),
            'profit_factor': round(profit_factor, 2),
            'total_profit': round(total_profit, 2),
            'total_loss': round(total_loss, 2),
            'net_profit': round(total_profit - total_loss, 2),
            'max_drawdown': round(max_drawdown, 2),
            'avg_win': round(total_profit / len(winning_trades), 2) if winning_trades else 0,
            'avg_loss': round(total_loss / len(losing_trades), 2) if losing_trades else 0,
            'sharpe': sharpe,
        }
    
    async def get_trade_history(self, limit: int = 20, is_demo: bool = False) -> List[Dict[str, Any]]:
        """Получить историю сделок (из БД или user_data)"""
        if self.use_database and self.db:
            try:
                # Получаем закрытые сделки из БД
                closed_trades = self.db.get_closed_trades(self.user_id, limit=limit)
                
                # Преобразуем формат для совместимости
                trades = []
                for trade in closed_trades:
                    if is_demo and not trade.get('is_demo', True):
                        continue
                    if not is_demo and trade.get('is_demo', True):
                        continue
                    
                    trades.append({
                        'symbol': trade.get('symbol'),
                        'direction': trade.get('direction'),
                        'amount': trade.get('amount'),
                        'entry': trade.get('entry_price'),
                        'close_price': trade.get('close_price'),
                        'pnl': trade.get('pnl', 0),
                        'status': trade.get('status', 'closed'),
                        'timestamp': trade.get('entry_time'),
                        'close_time': trade.get('close_time'),
                        'close_reason': trade.get('close_reason')
                    })
                
                return trades
            except Exception as e:
                print(f"[StatisticsManager] ⚠️ Ошибка получения сделок из БД: {e}")
        
        # Fallback на user_data
        if is_demo:
            return self.demo_trades[-limit:] if len(self.demo_trades) > limit else self.demo_trades
        
        return []
    
    def add_demo_trade(self, trade: Dict[str, Any]):
        """Добавить демо-сделку в историю (в БД и user_data)"""
        trade['timestamp'] = datetime.now().isoformat()
        trade['status'] = 'open'
        trade['close_price'] = None
        
        # Сохраняем в user_data (который сам сохранит в БД если используется)
        self.user_data.save_demo_position(self.user_id, trade)
        
        # Обновляем локальный кэш
        self.demo_trades = self.user_data.get_demo_positions(self.user_id)
    
    def get_demo_trades(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить демо-сделки (опционально фильтр по статусу)"""
        if status:
            return [t for t in self.demo_trades if t.get('status') == status]
        return self.demo_trades
    
    def close_demo_trade(self, symbol: str, close_price: float, reason: str = ""):
        """Закрыть демо-сделку (в БД и user_data)"""
        # Ищем открытую сделку
        open_trades = self.user_data.get_demo_positions(self.user_id)
        trade_to_close = None
        
        for trade in reversed(open_trades):
            if trade.get('symbol') == symbol and trade.get('status') == 'open':
                trade_to_close = trade
                break
        
        if not trade_to_close:
            return False
        
        entry = trade_to_close.get('entry', 0)
        amount = trade_to_close.get('amount', 0)
        direction = trade_to_close.get('direction', 'long')
        
        # Критическая проверка: если entry = 0, PnL будет неправильным
        if entry == 0 or entry is None:
            print(f"[StatisticsManager] ⚠️ Ошибка: entry = 0 для {symbol}, используем close_price как entry")
            # Используем close_price как entry (это лучше, чем 0)
            entry = close_price
        
        # Рассчитываем PnL
        if direction == 'long':
            pnl = (close_price - entry) * amount
        else:  # short
            pnl = (entry - close_price) * amount
        
        # Обновляем через user_data (который сохранит в БД)
        self.user_data.update_demo_position(self.user_id, symbol, {
            'status': 'closed',
            'close_price': close_price,
            'close_time': datetime.now().isoformat(),
            'pnl': pnl,
            'close_reason': reason
        })
        
        # Обновляем демо-баланс
        current_balance = self.user_data.get_user_data(self.user_id).get('demo_balance', 10000.0)
        new_balance = current_balance + pnl
        self.user_data.update_demo_balance(self.user_id, new_balance)
        
        # Обновляем локальный кэш
        self.demo_trades = self.user_data.get_demo_positions(self.user_id)
        
        return True
    
    async def _get_trades_for_period(self, period: str, is_demo: bool) -> List[Dict[str, Any]]:
        """Получить сделки за период (из БД или user_data)"""
        now = datetime.now()
        
        if period == '1h':
            start_time = now - timedelta(hours=1)
        elif period == '24h':
            start_time = now - timedelta(days=1)
        elif period == '7d':
            start_time = now - timedelta(days=7)
        elif period == '30d':
            start_time = now - timedelta(days=30)
        else:
            start_time = datetime.min
        
        # Используем БД если доступна
        if self.use_database and self.db:
            try:
                closed_trades = self.db.get_closed_trades(
                    self.user_id,
                    limit=10000,
                    start_date=start_time,
                    end_date=now
                )
                
                # Преобразуем формат
                trades = []
                for trade in closed_trades:
                    if is_demo and not trade.get('is_demo', True):
                        continue
                    if not is_demo and trade.get('is_demo', True):
                        continue
                    
                    trades.append({
                        'symbol': trade.get('symbol'),
                        'direction': trade.get('direction'),
                        'amount': trade.get('amount'),
                        'entry': trade.get('entry_price'),
                        'close_price': trade.get('close_price'),
                        'pnl': trade.get('pnl', 0),
                        'status': trade.get('status', 'closed'),
                        'timestamp': trade.get('entry_time'),
                        'close_time': trade.get('close_time'),
                        'close_reason': trade.get('close_reason')
                    })
                
                return trades
            except Exception as e:
                print(f"[StatisticsManager] ⚠️ Ошибка получения сделок из БД: {e}")
        
        # Fallback на user_data
        if is_demo:
            return [t for t in self.demo_trades 
                   if t.get('timestamp') and datetime.fromisoformat(t['timestamp']) >= start_time]
        
        return []
    
    def _calculate_max_drawdown(self, trades: List[Dict[str, Any]]) -> float:
        """Рассчитывает максимальную просадку"""
        if not trades:
            return 0
        
        cumulative = 0
        peak = 0
        max_dd = 0
        
        for trade in trades:
            cumulative += trade.get('pnl', 0)
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > max_dd:
                max_dd = drawdown
        
        return max_dd

    def _calculate_sharpe(self, trades: List[Dict[str, Any]]) -> float:
        """
        Упрощённый Sharpe на сделку:
        Sharpe = mean(pnl) / std(pnl)
        """
        pnls = [float(t.get("pnl", 0) or 0) for t in trades if t.get("pnl") is not None]
        if len(pnls) < 2:
            return 0.0
        mean = sum(pnls) / len(pnls)
        var = sum([(x - mean) ** 2 for x in pnls]) / (len(pnls) - 1)
        std = var ** 0.5
        if std == 0:
            return 0.0
        return round(mean / std, 3)
    
    async def _get_demo_positions(self) -> List[Dict[str, Any]]:
        """Получить открытые демо-позиции с unrealized PnL"""
        open_positions = self.user_data.get_demo_positions(self.user_id)
        return [p for p in open_positions if p.get('status') == 'open']
    
    async def get_advanced_statistics(self, period: str = '24h', is_demo: bool = False) -> Dict[str, Any]:
        """
        Расширенный анализ ставок с глубокой статистикой
        
        Включает:
        - Анализ по парам
        - Анализ по направлениям (long/short)
        - Анализ по таймфреймам
        - Корреляция индикаторов с результатами
        - Анализ эффективности стратегий
        """
        trades = await self._get_trades_for_period(period, is_demo)
        
        if not trades:
            return {
                'period': period,
                'basic_stats': await self.get_statistics(period, is_demo),
                'pair_analysis': {},
                'direction_analysis': {},
                'timeframe_analysis': {},
                'strategy_performance': {},
                'risk_metrics': {}
            }
        
        # Базовая статистика
        basic_stats = await self.get_statistics(period, is_demo)
        
        # Анализ по парам
        pair_analysis = self._analyze_by_pairs(trades)
        
        # Анализ по направлениям
        direction_analysis = self._analyze_by_direction(trades)
        
        # Анализ по таймфреймам
        timeframe_analysis = self._analyze_by_timeframe(trades)
        
        # Анализ эффективности стратегий
        strategy_performance = self._analyze_strategy_performance(trades)
        
        # Расширенные метрики риска
        risk_metrics = self._calculate_advanced_risk_metrics(trades)
        
        # Анализ корреляции индикаторов
        indicator_correlation = self._analyze_indicator_correlation(trades)
        
        return {
            'period': period,
            'basic_stats': basic_stats,
            'pair_analysis': pair_analysis,
            'direction_analysis': direction_analysis,
            'timeframe_analysis': timeframe_analysis,
            'strategy_performance': strategy_performance,
            'risk_metrics': risk_metrics,
            'indicator_correlation': indicator_correlation,
            'recommendations': self._generate_recommendations_from_analysis(
                pair_analysis, direction_analysis, strategy_performance, risk_metrics
            )
        }
    
    def _analyze_by_pairs(self, trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Анализ эффективности по торговым парам"""
        pair_stats = {}
        
        for trade in trades:
            symbol = trade.get('symbol', 'UNKNOWN')
            if symbol not in pair_stats:
                pair_stats[symbol] = {
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'total_pnl': 0,
                    'total_profit': 0,
                    'total_loss': 0,
                    'avg_pnl': 0,
                    'win_rate': 0,
                    'profit_factor': 0,
                    'best_trade': 0,
                    'worst_trade': 0
                }
            
            pnl = trade.get('pnl', 0)
            pair_stats[symbol]['total_trades'] += 1
            pair_stats[symbol]['total_pnl'] += pnl
            
            if pnl > 0:
                pair_stats[symbol]['winning_trades'] += 1
                pair_stats[symbol]['total_profit'] += pnl
                if pnl > pair_stats[symbol]['best_trade']:
                    pair_stats[symbol]['best_trade'] = pnl
            else:
                pair_stats[symbol]['losing_trades'] += 1
                pair_stats[symbol]['total_loss'] += abs(pnl)
                if pnl < pair_stats[symbol]['worst_trade']:
                    pair_stats[symbol]['worst_trade'] = pnl
        
        # Рассчитываем финальные метрики
        for symbol in pair_stats:
            stats = pair_stats[symbol]
            stats['win_rate'] = (stats['winning_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
            stats['profit_factor'] = (stats['total_profit'] / stats['total_loss']) if stats['total_loss'] > 0 else 0
            stats['avg_pnl'] = stats['total_pnl'] / stats['total_trades'] if stats['total_trades'] > 0 else 0
            
            # Округляем значения
            for key in ['win_rate', 'profit_factor', 'avg_pnl', 'total_pnl', 'total_profit', 'total_loss', 'best_trade', 'worst_trade']:
                stats[key] = round(stats[key], 2)
        
        return pair_stats
    
    def _analyze_by_direction(self, trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Анализ эффективности по направлениям (long/short)"""
        direction_stats = {
            'long': {'total': 0, 'winning': 0, 'losing': 0, 'total_pnl': 0, 'win_rate': 0, 'avg_pnl': 0},
            'short': {'total': 0, 'winning': 0, 'losing': 0, 'total_pnl': 0, 'win_rate': 0, 'avg_pnl': 0}
        }
        
        for trade in trades:
            direction = trade.get('direction', 'long').lower()
            if direction not in direction_stats:
                continue
            
            pnl = trade.get('pnl', 0)
            direction_stats[direction]['total'] += 1
            direction_stats[direction]['total_pnl'] += pnl
            
            if pnl > 0:
                direction_stats[direction]['winning'] += 1
            else:
                direction_stats[direction]['losing'] += 1
        
        # Рассчитываем метрики
        for direction in direction_stats:
            stats = direction_stats[direction]
            stats['win_rate'] = (stats['winning'] / stats['total'] * 100) if stats['total'] > 0 else 0
            stats['avg_pnl'] = stats['total_pnl'] / stats['total'] if stats['total'] > 0 else 0
            stats['win_rate'] = round(stats['win_rate'], 2)
            stats['avg_pnl'] = round(stats['avg_pnl'], 2)
            stats['total_pnl'] = round(stats['total_pnl'], 2)
        
        return direction_stats
    
    def _analyze_by_timeframe(self, trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Анализ эффективности по таймфреймам"""
        timeframe_stats = {}
        
        for trade in trades:
            timeframe = trade.get('timeframe', '5m')
            if timeframe not in timeframe_stats:
                timeframe_stats[timeframe] = {
                    'total': 0, 'winning': 0, 'losing': 0,
                    'total_pnl': 0, 'win_rate': 0, 'avg_pnl': 0
                }
            
            pnl = trade.get('pnl', 0)
            stats = timeframe_stats[timeframe]
            stats['total'] += 1
            stats['total_pnl'] += pnl
            
            if pnl > 0:
                stats['winning'] += 1
            else:
                stats['losing'] += 1
        
        # Рассчитываем метрики
        for timeframe in timeframe_stats:
            stats = timeframe_stats[timeframe]
            stats['win_rate'] = (stats['winning'] / stats['total'] * 100) if stats['total'] > 0 else 0
            stats['avg_pnl'] = stats['total_pnl'] / stats['total'] if stats['total'] > 0 else 0
            stats['win_rate'] = round(stats['win_rate'], 2)
            stats['avg_pnl'] = round(stats['avg_pnl'], 2)
            stats['total_pnl'] = round(stats['total_pnl'], 2)
        
        return timeframe_stats
    
    def _analyze_strategy_performance(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Анализ эффективности различных стратегий"""
        # Анализируем по типам сигналов (если есть в данных)
        strategy_stats = {}
        
        for trade in trades:
            # Определяем стратегию по сигналу или другим параметрам
            signal_type = trade.get('signal_type', 'unknown')
            if signal_type not in strategy_stats:
                strategy_stats[signal_type] = {
                    'total': 0, 'winning': 0, 'total_pnl': 0,
                    'win_rate': 0, 'avg_pnl': 0
                }
            
            pnl = trade.get('pnl', 0)
            stats = strategy_stats[signal_type]
            stats['total'] += 1
            stats['total_pnl'] += pnl
            
            if pnl > 0:
                stats['winning'] += 1
        
        # Рассчитываем метрики
        for strategy in strategy_stats:
            stats = strategy_stats[strategy]
            stats['win_rate'] = (stats['winning'] / stats['total'] * 100) if stats['total'] > 0 else 0
            stats['avg_pnl'] = stats['total_pnl'] / stats['total'] if stats['total'] > 0 else 0
            stats['win_rate'] = round(stats['win_rate'], 2)
            stats['avg_pnl'] = round(stats['avg_pnl'], 2)
            stats['total_pnl'] = round(stats['total_pnl'], 2)
        
        return strategy_stats
    
    def _calculate_advanced_risk_metrics(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Расширенные метрики риска"""
        if not trades:
            return {}
        
        pnls = [t.get('pnl', 0) for t in trades]
        winning_pnls = [p for p in pnls if p > 0]
        losing_pnls = [p for p in pnls if p < 0]
        
        # Value at Risk (VaR) - 95% уровень
        sorted_pnls = sorted(pnls)
        var_95 = sorted_pnls[int(len(sorted_pnls) * 0.05)] if sorted_pnls else 0
        
        # Expected Shortfall (CVaR)
        cvar_95 = sum([p for p in sorted_pnls[:int(len(sorted_pnls) * 0.05)]]) / max(1, int(len(sorted_pnls) * 0.05)) if sorted_pnls else 0
        
        # Коэффициент Сортино (Sortino Ratio) - учитывает только негативную волатильность
        mean_return = sum(pnls) / len(pnls) if pnls else 0
        downside_deviation = math.sqrt(sum([min(0, p - mean_return) ** 2 for p in pnls]) / len(pnls)) if pnls else 0
        sortino = (mean_return / downside_deviation) if downside_deviation > 0 else 0
        
        # Максимальная серия убытков
        max_losing_streak = 0
        current_streak = 0
        for pnl in pnls:
            if pnl < 0:
                current_streak += 1
                max_losing_streak = max(max_losing_streak, current_streak)
            else:
                current_streak = 0
        
        # Максимальная серия прибыли
        max_winning_streak = 0
        current_streak = 0
        for pnl in pnls:
            if pnl > 0:
                current_streak += 1
                max_winning_streak = max(max_winning_streak, current_streak)
            else:
                current_streak = 0
        
        # Recovery Factor (чистая прибыль / максимальная просадка)
        max_dd = self._calculate_max_drawdown(trades)
        net_profit = sum(pnls)
        recovery_factor = (net_profit / max_dd) if max_dd > 0 else 0
        
        return {
            'var_95': round(var_95, 2),
            'cvar_95': round(cvar_95, 2),
            'sortino_ratio': round(sortino, 3),
            'max_losing_streak': max_losing_streak,
            'max_winning_streak': max_winning_streak,
            'recovery_factor': round(recovery_factor, 2),
            'downside_deviation': round(downside_deviation, 2),
            'risk_reward_ratio': round(abs(sum(winning_pnls) / sum(losing_pnls)) if losing_pnls else 0, 2)
        }
    
    def _analyze_indicator_correlation(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Анализ корреляции индикаторов с результатами сделок"""
        # Группируем сделки по значениям индикаторов (если есть в данных)
        # Это упрощенная версия - в реальности нужны данные индикаторов из анализа
        
        correlation_data = {
            'rsi_correlation': {'oversold_wins': 0, 'oversold_total': 0, 'overbought_wins': 0, 'overbought_total': 0},
            'macd_correlation': {'bullish_wins': 0, 'bullish_total': 0, 'bearish_wins': 0, 'bearish_total': 0},
            'signal_strength_correlation': {}
        }
        
        # Анализируем корреляцию силы сигнала с результатом
        signal_strengths = []
        for trade in trades:
            signal_strength = trade.get('signal_strength', 0)
            pnl = trade.get('pnl', 0)
            if signal_strength > 0:
                signal_strengths.append({
                    'strength': signal_strength,
                    'pnl': pnl,
                    'win': pnl > 0
                })
        
        # Группируем по уровням силы сигнала
        strength_groups = {
            'weak': {'wins': 0, 'total': 0, 'avg_pnl': 0},
            'medium': {'wins': 0, 'total': 0, 'avg_pnl': 0},
            'strong': {'wins': 0, 'total': 0, 'avg_pnl': 0}
        }
        
        for item in signal_strengths:
            if item['strength'] < 40:
                group = 'weak'
            elif item['strength'] < 70:
                group = 'medium'
            else:
                group = 'strong'
            
            strength_groups[group]['total'] += 1
            strength_groups[group]['avg_pnl'] += item['pnl']
            if item['win']:
                strength_groups[group]['wins'] += 1
        
        # Рассчитываем финальные метрики
        for group in strength_groups:
            stats = strength_groups[group]
            if stats['total'] > 0:
                stats['win_rate'] = round((stats['wins'] / stats['total']) * 100, 2)
                stats['avg_pnl'] = round(stats['avg_pnl'] / stats['total'], 2)
            else:
                stats['win_rate'] = 0
                stats['avg_pnl'] = 0
        
        correlation_data['signal_strength_correlation'] = strength_groups
        
        return correlation_data
    
    def _generate_recommendations_from_analysis(
        self, pair_analysis: Dict, direction_analysis: Dict,
        strategy_performance: Dict, risk_metrics: Dict
    ) -> List[str]:
        """Генерирует рекомендации на основе анализа"""
        recommendations = []
        
        # Анализ по парам
        if pair_analysis:
            best_pair = max(pair_analysis.items(), key=lambda x: x[1].get('win_rate', 0))
            worst_pair = min(pair_analysis.items(), key=lambda x: x[1].get('win_rate', 0))
            
            if best_pair[1].get('win_rate', 0) > 60:
                recommendations.append(f"✅ Лучшая пара: {best_pair[0]} (Win Rate: {best_pair[1]['win_rate']}%)")
            
            if worst_pair[1].get('win_rate', 0) < 40:
                recommendations.append(f"⚠️ Избегать: {worst_pair[0]} (Win Rate: {worst_pair[1]['win_rate']}%)")
        
        # Анализ по направлениям
        if direction_analysis:
            long_wr = direction_analysis.get('long', {}).get('win_rate', 0)
            short_wr = direction_analysis.get('short', {}).get('win_rate', 0)
            
            if long_wr > short_wr + 10:
                recommendations.append(f"📈 LONG показывает лучшие результаты (WR: {long_wr}% vs {short_wr}%)")
            elif short_wr > long_wr + 10:
                recommendations.append(f"📉 SHORT показывает лучшие результаты (WR: {short_wr}% vs {long_wr}%)")
        
        # Анализ риска
        if risk_metrics:
            if risk_metrics.get('max_losing_streak', 0) > 5:
                recommendations.append(f"⚠️ Обнаружена длинная серия убытков: {risk_metrics['max_losing_streak']} сделок подряд")
            
            if risk_metrics.get('recovery_factor', 0) < 1:
                recommendations.append("⚠️ Recovery Factor < 1: просадки превышают прибыль")
        
        return recommendations
    
    def format_statistics_message(self, stats: Dict[str, Any]) -> str:
        """Форматирует статистику в сообщение"""
        period_names = {
            '1h': 'последний час',
            '24h': '24 часа',
            '7d': 'неделю',
            '30d': 'месяц',
            'all': 'всё время'
        }
        
        period_name = period_names.get(stats.get('period', 'all'), 'период')
        
        message = f"📊 Статистика за {period_name}:\n\n"
        message += f"📈 Всего сделок: {stats.get('total_trades', 0)}\n"
        message += f"✅ Прибыльных: {stats.get('winning_trades', 0)}\n"
        message += f"❌ Убыточных: {stats.get('losing_trades', 0)}\n"
        message += f"🎯 Win Rate: {stats.get('win_rate', 0)}%\n"
        message += f"💰 Чистая прибыль: {stats.get('net_profit', 0)} USDT\n"
        message += f"📊 Profit Factor: {stats.get('profit_factor', 0)}\n"
        message += f"📉 Max Drawdown: {stats.get('max_drawdown', 0)} USDT\n"
        message += f"📐 Sharpe: {stats.get('sharpe', 0)}\n"
        
        if stats.get('avg_win', 0) > 0:
            message += f"📈 Средний выигрыш: {stats.get('avg_win', 0)} USDT\n"
        if stats.get('avg_loss', 0) > 0:
            message += f"📉 Средний проигрыш: {stats.get('avg_loss', 0)} USDT\n"
        
        return message
