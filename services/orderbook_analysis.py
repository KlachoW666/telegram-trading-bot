from typing import Dict, List, Any, Optional


class OrderBookAnalyzer:
    """Класс для глубокого анализа стакана (Order Book)"""
    
    def analyze_orderbook(self, orderbook: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Глубокий анализ стакана
        
        Args:
            orderbook: Стакан с bids и asks
            current_price: Текущая цена
        
        Returns:
            Результаты анализа
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return {'error': 'Недостаточно данных в стакане'}
        
        # Базовый анализ объёмов
        bid_volume_analysis = self._analyze_volume_levels(bids, current_price, 'bid')
        ask_volume_analysis = self._analyze_volume_levels(asks, current_price, 'ask')
        
        # Имбаланс
        imbalance = self._calculate_imbalance(bids, asks)
        
        # Стены (крупные ордера)
        walls = self._find_walls(bids, asks, current_price)
        
        # Потенциальные спуф-ордера
        spoof_orders = self._detect_spoofing(bids, asks, current_price)
        
        # Absorption (поглощение)
        absorption = self._detect_absorption(bids, asks, current_price)
        
        # Общий сигнал
        signal = self._generate_signal(imbalance, walls, absorption)
        
        return {
            'current_price': current_price,
            'bid_analysis': bid_volume_analysis,
            'ask_analysis': ask_volume_analysis,
            'imbalance': imbalance,
            'walls': walls,
            'spoof_orders': spoof_orders,
            'absorption': absorption,
            'signal': signal,
            'summary': self._generate_summary(imbalance, walls, absorption, signal)
        }
    
    def _analyze_volume_levels(self, levels: List[List], current_price: float, side: str) -> Dict[str, Any]:
        """Анализирует уровни объёмов"""
        if not levels:
            return {}
        
        total_volume = sum([level[1] for level in levels])
        avg_volume = total_volume / len(levels) if levels else 0
        
        # Ближайшие уровни к цене
        nearby_levels = []
        for level in levels[:10]:
            price = level[0]
            volume = level[1]
            distance = abs(price - current_price) / current_price * 100
            
            if distance < 1.0:  # В пределах 1% от цены
                nearby_levels.append({
                    'price': price,
                    'volume': volume,
                    'distance_percent': distance,
                    'is_large': volume > avg_volume * 2
                })
        
        return {
            'total_volume': total_volume,
            'average_volume': avg_volume,
            'nearby_levels': nearby_levels,
            'largest_level': {
                'price': max(levels, key=lambda x: x[1])[0],
                'volume': max(levels, key=lambda x: x[1])[1]
            } if levels else None
        }
    
    def _calculate_imbalance(self, bids: List[List], asks: List[List]) -> Dict[str, Any]:
        """
        Рассчитывает имбаланс между бидами и асками
        
        Согласно proverka.txt: (sum bids / sum asks) >1.2 — buy signal
        Используем более глубокий анализ для точности
        """
        # Используем больше уровней для более точного анализа (рекомендация: до 100 уровней)
        bid_volume = sum([bid[1] for bid in bids[:50]])  # Увеличено с 20 до 50
        ask_volume = sum([ask[1] for ask in asks[:50]])  # Увеличено с 20 до 50
        
        total_volume = bid_volume + ask_volume
        imbalance_percent = ((bid_volume - ask_volume) / total_volume * 100) if total_volume > 0 else 0
        
        # Согласно proverka.txt: bids/asks ratio >1.2 — buy signal
        bids_asks_ratio = bid_volume / ask_volume if ask_volume > 0 else 1.0
        
        # Определяем сигнал на основе ratio (как в proverka.txt)
        if bids_asks_ratio > 1.5:
            ratio_signal = 'strong_bullish'
        elif bids_asks_ratio > 1.2:  # Порог из proverka.txt
            ratio_signal = 'bullish'
        elif bids_asks_ratio < 0.67:  # 1/1.5 = обратный порог
            ratio_signal = 'strong_bearish'
        elif bids_asks_ratio < 0.83:  # 1/1.2 = обратный порог
            ratio_signal = 'bearish'
        else:
            ratio_signal = 'neutral'
        
        # Комбинируем сигналы от процента и ratio для более точного результата
        if imbalance_percent > 30 or bids_asks_ratio > 1.5:
            final_signal = 'strong_bullish'
        elif imbalance_percent > 10 or bids_asks_ratio > 1.2:
            final_signal = 'bullish'
        elif imbalance_percent < -30 or bids_asks_ratio < 0.67:
            final_signal = 'strong_bearish'
        elif imbalance_percent < -10 or bids_asks_ratio < 0.83:
            final_signal = 'bearish'
        else:
            final_signal = 'neutral'
        
        return {
            'bid_volume': bid_volume,
            'ask_volume': ask_volume,
            'imbalance_percent': imbalance_percent,
            'bids_asks_ratio': bids_asks_ratio,  # Новое поле согласно proverka.txt
            'ratio_signal': ratio_signal,  # Сигнал на основе ratio
            'signal': final_signal
        }
    
    def _find_walls(self, bids: List[List], asks: List[List], current_price: float) -> List[Dict[str, Any]]:
        """Находит крупные стены в стакане"""
        walls = []
        
        # Стены на бидах
        # Используем больше уровней для более точного анализа (согласно proverka.txt)
        avg_bid_volume = sum([bid[1] for bid in bids[:50]]) / 50 if len(bids) >= 50 else (sum([bid[1] for bid in bids]) / len(bids) if bids else 0)
        for bid in bids[:20]:  # Проверяем больше уровней
            if bid[1] > avg_bid_volume * 3:  # В 3 раза больше среднего
                walls.append({
                    'side': 'bid',
                    'price': bid[0],
                    'volume': bid[1],
                    'distance_percent': (current_price - bid[0]) / current_price * 100,
                    'strength': 'strong' if bid[1] > avg_bid_volume * 5 else 'medium'
                })
        
        # Стены на асках
        avg_ask_volume = sum([ask[1] for ask in asks[:50]]) / 50 if len(asks) >= 50 else (sum([ask[1] for ask in asks]) / len(asks) if asks else 0)
        for ask in asks[:20]:  # Проверяем больше уровней
            if ask[1] > avg_ask_volume * 3:
                walls.append({
                    'side': 'ask',
                    'price': ask[0],
                    'volume': ask[1],
                    'distance_percent': (ask[0] - current_price) / current_price * 100,
                    'strength': 'strong' if ask[1] > avg_ask_volume * 5 else 'medium'
                })
        
        return sorted(walls, key=lambda x: x['volume'], reverse=True)[:5]
    
    def _detect_spoofing(self, bids: List[List], asks: List[List], current_price: float) -> List[Dict[str, Any]]:
        """Обнаруживает потенциальные спуф-ордера"""
        spoofs = []
        
        # Анализ быстрого появления/исчезновения крупных ордеров
        # (в реальной системе это требует исторических данных)
        # Используем больше уровней для более точного анализа (согласно proverka.txt)
        avg_bid = sum([bid[1] for bid in bids[:50]]) / 50 if len(bids) >= 50 else (sum([bid[1] for bid in bids]) / len(bids) if bids else 0)
        avg_ask = sum([ask[1] for ask in asks[:50]]) / 50 if len(asks) >= 50 else (sum([ask[1] for ask in asks]) / len(asks) if asks else 0)
        
        for bid in bids[:5]:
            if bid[1] > avg_bid * 5 and abs(bid[0] - current_price) / current_price < 0.005:
                spoofs.append({
                    'side': 'bid',
                    'price': bid[0],
                    'volume': bid[1],
                    'reason': 'Очень крупный ордер очень близко к цене'
                })
        
        for ask in asks[:5]:
            if ask[1] > avg_ask * 5 and abs(ask[0] - current_price) / current_price < 0.005:
                spoofs.append({
                    'side': 'ask',
                    'price': ask[0],
                    'volume': ask[1],
                    'reason': 'Очень крупный ордер очень близко к цене'
                })
        
        return spoofs
    
    def _detect_absorption(self, bids: List[List], asks: List[List], current_price: float) -> Optional[Dict[str, Any]]:
        """Обнаруживает поглощение (absorption)"""
        # Absorption - когда большой объём стоит на уровне, но цена не двигается
        # Это требует анализа движения цены, но мы можем оценить по статике
        
        if not bids or not asks:
            return None
        
        # Ищем уровни с очень большим объёмом близко к цене
        for bid in bids[:3]:
            # Используем больше уровней для анализа (согласно proverka.txt)
            if bid[1] > sum([b[1] for b in bids[:50]]) * 0.3:  # 30% от общего объёма (более точный порог)
                return {
                    'side': 'bid',
                    'price': bid[0],
                    'volume': bid[1],
                    'interpretation': 'Возможное поглощение продаж на уровне бида'
                }
        
        for ask in asks[:3]:
            if ask[1] > sum([a[1] for a in asks[:50]]) * 0.3:  # 30% от общего объёма
                return {
                    'side': 'ask',
                    'price': ask[0],
                    'volume': ask[1],
                    'interpretation': 'Возможное поглощение покупок на уровне аска'
                }
        
        return None
    
    def _generate_signal(self, imbalance: Dict[str, Any], walls: List[Dict], absorption: Optional[Dict]) -> Dict[str, Any]:
        """
        Генерирует торговый сигнал на основе стакана
        
        Согласно proverka.txt: (sum bids / sum asks) >1.2 — buy signal
        """
        signals = []
        strength = 0
        
        # Сигнал от имбаланса (используем ratio согласно proverka.txt)
        bids_asks_ratio = imbalance.get('bids_asks_ratio', 1.0)
        ratio_signal = imbalance.get('ratio_signal', 'neutral')
        
        # Приоритет сигналу от ratio (согласно proverka.txt)
        if bids_asks_ratio > 1.2:  # Порог из proverka.txt
            signals.append('imbalance_bullish_ratio')
            if bids_asks_ratio > 1.5:
                strength += 25  # Сильный сигнал
            else:
                strength += 15  # Умеренный сигнал
        elif bids_asks_ratio < 0.83:  # Обратный порог
            signals.append('imbalance_bearish_ratio')
            if bids_asks_ratio < 0.67:
                strength -= 25
            else:
                strength -= 15
        
        # Дополнительный сигнал от процента имбаланса (для совместимости)
        imbalance_signal = imbalance.get('signal', 'neutral')
        if 'bullish' in imbalance_signal and 'bullish' not in ratio_signal:
            signals.append('imbalance_bullish')
            strength += 10 if 'strong' in imbalance_signal else 5
        elif 'bearish' in imbalance_signal and 'bearish' not in ratio_signal:
            signals.append('imbalance_bearish')
            strength -= 10 if 'strong' in imbalance_signal else 5
        
        # Сигнал от стен
        bid_walls = [w for w in walls if w['side'] == 'bid' and w['strength'] == 'strong']
        ask_walls = [w for w in walls if w['side'] == 'ask' and w['strength'] == 'strong']
        
        if len(bid_walls) > len(ask_walls):
            signals.append('strong_bid_walls')
            strength += 15
        elif len(ask_walls) > len(bid_walls):
            signals.append('strong_ask_walls')
            strength -= 15
        
        # Сигнал от поглощения
        if absorption:
            if absorption['side'] == 'bid':
                signals.append('absorption_bid')
                strength += 10
            else:
                signals.append('absorption_ask')
                strength -= 10
        
        # Финальный сигнал
        if strength > 25:
            final = 'strong_bullish'
        elif strength > 10:
            final = 'bullish'
        elif strength < -25:
            final = 'strong_bearish'
        elif strength < -10:
            final = 'bearish'
        else:
            final = 'neutral'
        
        return {
            'signals': signals,
            'strength': strength,
            'final_signal': final,
            'confidence': min(abs(strength) * 2, 100)
        }
    
    def _generate_summary(self, imbalance: Dict, walls: List, absorption: Optional[Dict], signal: Dict) -> str:
        """Генерирует текстовое резюме анализа"""
        summary_parts = []
        
        # Имбаланс
        imb_percent = imbalance.get('imbalance_percent', 0)
        if abs(imb_percent) > 10:
            summary_parts.append(f"Имбаланс: {imb_percent:.1f}% ({'покупки' if imb_percent > 0 else 'продажи'})")
        
        # Стены
        if walls:
            strong_walls = [w for w in walls if w['strength'] == 'strong']
            if strong_walls:
                summary_parts.append(f"Обнаружено {len(strong_walls)} сильных стен")
        
        # Поглощение
        if absorption:
            summary_parts.append(f"Поглощение на {absorption['side']} уровне {absorption['price']}")
        
        # Сигнал
        final_signal = signal.get('final_signal', 'neutral')
        if final_signal != 'neutral':
            summary_parts.append(f"Сигнал стакана: {final_signal.upper()}")
        
        return ". ".join(summary_parts) if summary_parts else "Стакан нейтрален"
