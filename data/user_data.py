import json
import os
from typing import Dict, Optional, Any, List
from pathlib import Path
from cryptography.fernet import Fernet
import base64
from hashlib import sha256
from datetime import datetime
try:
    from data.database import get_database
except ImportError:
    # Для обратной совместимости
    get_database = None


class UserDataManager:
    """Менеджер данных пользователей с поддержкой БД и JSON (обратная совместимость)"""
    
    def __init__(self, data_dir: str = "data", use_database: bool = True):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.use_database = use_database and get_database is not None
        
        # Инициализируем БД если используется
        if self.use_database:
            try:
                self.db = get_database()
            except Exception as e:
                print(f"[UserDataManager] ⚠️ Не удалось инициализировать БД: {e}, используем JSON")
                self.use_database = False
                self.db = None
        else:
            self.db = None
        
        # Генерируем ключ шифрования на основе секрета (в продакшене использовать переменную окружения)
        secret = os.getenv("ENCRYPTION_KEY", "default_secret_key_change_in_production")
        key = sha256(secret.encode()).digest()
        self.cipher = Fernet(base64.urlsafe_b64encode(key))
    
    def _get_user_file(self, user_id: int) -> Path:
        """Получить путь к файлу пользователя"""
        return self.data_dir / f"user_{user_id}.json"
    
    def _encrypt(self, data: str) -> str:
        """Зашифровать данные"""
        return self.cipher.encrypt(data.encode()).decode()
    
    def _decrypt(self, encrypted_data: str) -> str:
        """Расшифровать данные"""
        return self.cipher.decrypt(encrypted_data.encode()).decode()
    
    def _migrate_if_needed(self):
        """Автоматическая миграция данных из JSON в БД при первом запуске"""
        try:
            # Проверяем, есть ли JSON файлы для миграции
            json_files = list(self.data_dir.glob("user_*.json"))
            if json_files:
                print(f"[UserDataManager] Найдено {len(json_files)} JSON файлов для миграции...")
                migrated = self.db.migrate_all_json_files(str(self.data_dir))
                if migrated > 0:
                    print(f"[UserDataManager] ✅ Мигрировано {migrated} пользователей в БД")
        except Exception as e:
            print(f"[UserDataManager] ⚠️ Ошибка миграции: {e}")
    
    def get_user_data(self, user_id: int) -> Dict[str, Any]:
        """Получить данные пользователя (из БД или JSON)"""
        if self.use_database:
            user_data = self.db.get_user(user_id)
            if user_data:
                return user_data
        
        # Fallback на JSON (для обратной совместимости)
        user_file = self._get_user_file(user_id)
        
        if not user_file.exists():
            default_data = self._get_default_data()
            # Сохраняем в БД если используется
            if self.use_database:
                self.db.create_or_update_user(user_id, default_data)
            return default_data
        
        try:
            with open(user_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Расшифровываем API ключи
            if 'api_key_encrypted' in data:
                data['api_key'] = self._decrypt(data['api_key_encrypted'])
            if 'secret_key_encrypted' in data:
                data['secret_key'] = self._decrypt(data['secret_key_encrypted'])
            
            # Мигрируем в БД если используется
            if self.use_database:
                self.db.migrate_from_json(user_id, user_file)
            
            return data
        except Exception as e:
            print(f"Ошибка чтения данных пользователя {user_id}: {e}")
            return self._get_default_data()
    
    def save_user_data(self, user_id: int, data: Dict[str, Any]):
        """Сохранить данные пользователя (в БД и JSON для совместимости)"""
        # Сохраняем в БД если используется
        if self.use_database:
            try:
                self.db.create_or_update_user(user_id, data)
            except Exception as e:
                print(f"Ошибка сохранения в БД для пользователя {user_id}: {e}")
        
        # Также сохраняем в JSON для обратной совместимости
        user_file = self._get_user_file(user_id)
        
        # Шифруем API ключи перед сохранением
        data_copy = data.copy()
        if 'api_key' in data_copy and data_copy['api_key']:
            data_copy['api_key_encrypted'] = self._encrypt(data_copy['api_key'])
            del data_copy['api_key']
        if 'secret_key' in data_copy and data_copy['secret_key']:
            data_copy['secret_key_encrypted'] = self._encrypt(data_copy['secret_key'])
            del data_copy['secret_key']
        
        try:
            with open(user_file, 'w', encoding='utf-8') as f:
                json.dump(data_copy, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения данных пользователя {user_id}: {e}")
    
    def update_user_setting(self, user_id: int, key: str, value: Any):
        """Обновить настройку пользователя"""
        data = self.get_user_data(user_id)
        data[key] = value
        self.save_user_data(user_id, data)
    
    def _get_default_data(self) -> Dict[str, Any]:
        """Получить данные по умолчанию"""
        from config.settings import (
            DEFAULT_RISK_PER_TRADE, DEFAULT_TAKE_PROFIT, 
            DEFAULT_STOP_LOSS, DEFAULT_LEVERAGE, MAX_OPEN_POSITIONS, DEFAULT_PAIRS
        )
        
        return {
            'api_key': None,
            'secret_key': None,
            'is_demo_mode': True,
            'risk_per_trade': DEFAULT_RISK_PER_TRADE,
            'take_profit_percent': DEFAULT_TAKE_PROFIT,
            'stop_loss_percent': DEFAULT_STOP_LOSS,
            'leverage': DEFAULT_LEVERAGE,
            'max_open_positions': MAX_OPEN_POSITIONS,
            'trading_pairs': DEFAULT_PAIRS,
            'auto_trading_enabled': False,
            'notifications_enabled': True,
            'demo_balance': 10000.0,
            'demo_positions': [],  # Открытые демо-позиции
            'max_drawdown_percent': 20.0,  # Авто-стоп при drawdown >20% (из tt.txt)
            'max_holding_minutes': 7,  # Максимальное время удержания для скальпинга (рекомендуемое закрытие)
            'force_close_minutes': 10,  # Принудительное закрытие через N минут (максимум для скальпинга)
            'strategy_profile': 'scalp_smc_v2'  # Профиль стратегии (как в pycryptobot: конфиг-профили)
        }
    
    def get_demo_positions(self, user_id: int) -> List[Dict[str, Any]]:
        """Получить открытые демо-позиции (из БД или JSON)"""
        if self.use_database:
            trades = self.db.get_open_trades(user_id)
            # Преобразуем формат для совместимости
            positions = []
            for trade in trades:
                if trade.get('is_demo', True):
                    positions.append({
                        'symbol': trade.get('symbol'),
                        'direction': trade.get('direction'),
                        'amount': trade.get('amount'),
                        'entry': trade.get('entry_price'),
                        'stop_loss': trade.get('stop_loss'),
                        'take_profit': trade.get('take_profit'),
                        'pnl': trade.get('pnl', 0),
                        'status': trade.get('status', 'open'),
                        'timestamp': trade.get('entry_time'),
                        'close_price': trade.get('close_price'),
                        'close_time': trade.get('close_time'),
                        'close_reason': trade.get('close_reason')
                    })
            return positions
        
        # Fallback на JSON
        data = self.get_user_data(user_id)
        return data.get('demo_positions', [])
    
    def save_demo_position(self, user_id: int, position: Dict[str, Any]):
        """Сохранить демо-позицию (в БД и JSON)"""
        if self.use_database:
            try:
                # Проверяем, нет ли уже открытой позиции по этому символу
                open_trades = self.db.get_open_trades(user_id, symbol=position.get('symbol'))
                if open_trades:
                    # Обновляем существующую
                    trade_id = open_trades[0].get('trade_id')
                    updates = {
                        'amount': position.get('amount'),
                        'entry_price': position.get('entry'),
                        'stop_loss': position.get('stop_loss'),
                        'take_profit': position.get('take_profit'),
                        'position_value': position.get('entry', 0) * position.get('amount', 0) if position.get('entry') and position.get('amount') else 0
                    }
                    self.db.update_trade(trade_id, updates)
                else:
                    # Создаём новую
                    trade_data = {
                        'symbol': position.get('symbol'),
                        'direction': position.get('direction', 'long'),
                        'amount': position.get('amount', 0),
                        'entry': position.get('entry', 0),
                        'stop_loss': position.get('stop_loss'),
                        'take_profit': position.get('take_profit'),
                        'leverage': position.get('leverage', 5),
                        'is_demo': True,
                        'position_value': position.get('entry', 0) * position.get('amount', 0) if position.get('entry') and position.get('amount') else 0,
                        'probability': position.get('probability'),
                        'quality_score': position.get('quality_score'),
                        'signal_strength': position.get('signal_strength'),
                        'scale_factor': position.get('scale_factor'),
                        'order_id': position.get('order_id')
                    }
                    self.db.create_trade(user_id, trade_data)
            except Exception as e:
                print(f"Ошибка сохранения позиции в БД: {e}")
        
        # Также сохраняем в JSON для совместимости
        data = self.get_user_data(user_id)
        if 'demo_positions' not in data:
            data['demo_positions'] = []
        
        symbol = position.get('symbol')
        existing_idx = None
        for i, pos in enumerate(data['demo_positions']):
            if pos.get('symbol') == symbol and pos.get('status') == 'open':
                existing_idx = i
                break
        
        if existing_idx is not None:
            data['demo_positions'][existing_idx].update(position)
        else:
            position['timestamp'] = position.get('timestamp', datetime.now().isoformat())
            position['status'] = 'open'
            data['demo_positions'].append(position)
        
        self.save_user_data(user_id, data)
    
    def update_demo_position(self, user_id: int, symbol: str, updates: Dict[str, Any]):
        """Обновить демо-позицию (например, при закрытии)"""
        if self.use_database:
            try:
                open_trades = self.db.get_open_trades(user_id, symbol=symbol)
                if open_trades:
                    trade_id = open_trades[0].get('trade_id')
                    
                    # Если позиция закрывается
                    if updates.get('status') == 'closed' and updates.get('close_price'):
                        self.db.close_trade(
                            trade_id,
                            updates.get('close_price'),
                            updates.get('close_reason', ''),
                            updates.get('pnl', 0)
                        )
                    else:
                        # Простое обновление
                        db_updates = {}
                        if 'close_price' in updates:
                            db_updates['close_price'] = updates['close_price']
                        if 'close_reason' in updates:
                            db_updates['close_reason'] = updates['close_reason']
                        if 'pnl' in updates:
                            db_updates['pnl'] = updates['pnl']
                        if 'status' in updates:
                            db_updates['status'] = updates['status']
                        
                        if db_updates:
                            self.db.update_trade(trade_id, db_updates)
            except Exception as e:
                print(f"Ошибка обновления позиции в БД: {e}")
        
        # Также обновляем в JSON
        data = self.get_user_data(user_id)
        demo_positions = data.get('demo_positions', [])
        
        for pos in demo_positions:
            if pos.get('symbol') == symbol and pos.get('status') == 'open':
                pos.update(updates)
                break
        
        data['demo_positions'] = demo_positions
        self.save_user_data(user_id, data)
    
    def update_demo_balance(self, user_id: int, new_balance: float):
        """Обновить демо-баланс"""
        data = self.get_user_data(user_id)
        data['demo_balance'] = new_balance
        self.save_user_data(user_id, data)
