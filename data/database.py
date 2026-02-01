"""
Профессиональная система базы данных для торгового бота
Использует SQLite с поддержкой миграций и оптимизацией
"""
import sqlite3
import json
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from cryptography.fernet import Fernet
import base64
from hashlib import sha256

# Допустимые колонки таблицы trades (для валидации в update_trade)
_TRADES_COLUMNS = frozenset({
    'symbol', 'direction', 'amount', 'entry_price', 'stop_loss', 'take_profit',
    'leverage', 'status', 'pnl', 'close_price', 'close_reason', 'close_time',
    'entry_time', 'position_value', 'risk_amount', 'potential_profit',
    'risk_reward_ratio', 'probability', 'quality_score', 'signal_strength',
    'scale_factor', 'order_id', 'is_demo',
})


class Database:
    """Профессиональный менеджер базы данных с поддержкой транзакций"""
    
    def __init__(self, db_path: str = "data/trading_bot.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        
        # Генерируем ключ шифрования
        secret = os.getenv("ENCRYPTION_KEY", "default_secret_key_change_in_production")
        key = sha256(secret.encode()).digest()
        self.cipher = Fernet(base64.urlsafe_b64encode(key))
        
        # Инициализируем БД (индексы создаются внутри _init_database)
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для работы с БД"""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    
    def _init_database(self):
        """Инициализация БД с созданием всех таблиц"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    api_key_encrypted TEXT,
                    secret_key_encrypted TEXT,
                    is_demo_mode BOOLEAN DEFAULT 1,
                    risk_per_trade REAL DEFAULT 1.5,
                    take_profit_percent REAL DEFAULT 3.0,
                    stop_loss_percent REAL DEFAULT 1.5,
                    leverage INTEGER DEFAULT 5,
                    max_open_positions INTEGER DEFAULT 5,
                    trading_pairs TEXT,  -- JSON массив
                    auto_trading_enabled BOOLEAN DEFAULT 0,
                    notifications_enabled BOOLEAN DEFAULT 1,
                    demo_balance REAL DEFAULT 10000.0,
                    max_drawdown_percent REAL DEFAULT 20.0,
                    strategy_profile TEXT DEFAULT 'scalp_smc_v2',
                    sl_cooldown_minutes INTEGER DEFAULT 15,
                    atr_min_percent REAL DEFAULT 0.25,
                    timeframe TEXT DEFAULT '5m',
                    htf_timeframe TEXT DEFAULT '1h',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица сделок (открытые и закрытые)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,  -- 'long' или 'short'
                    amount REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    leverage INTEGER DEFAULT 5,
                    status TEXT DEFAULT 'open',  -- 'open' или 'closed'
                    pnl REAL DEFAULT 0,
                    close_price REAL,
                    close_reason TEXT,
                    close_time TIMESTAMP,
                    entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    position_value REAL,  -- Номинальный размер позиции
                    risk_amount REAL,  -- Риск в USDT
                    potential_profit REAL,  -- Потенциальная прибыль
                    risk_reward_ratio REAL,
                    probability REAL,  -- Вероятность сигнала
                    quality_score INTEGER,  -- Оценка качества
                    signal_strength REAL,
                    scale_factor REAL,  -- Коэффициент масштабирования
                    order_id TEXT,  -- ID ордера на бирже
                    is_demo BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Создаем индексы для trades
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_user_status ON trades(user_id, status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_status ON trades(symbol, status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_close_time ON trades(close_time)")
            
            # Таблица статистики (агрегированная статистика по периодам)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_statistics (
                    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    period_start TIMESTAMP NOT NULL,
                    period_end TIMESTAMP NOT NULL,
                    period_type TEXT NOT NULL,  -- '1h', '24h', '7d', '30d', 'all'
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_profit REAL DEFAULT 0,
                    total_loss REAL DEFAULT 0,
                    net_profit REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    profit_factor REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    sharpe_ratio REAL DEFAULT 0,
                    sortino_ratio REAL DEFAULT 0,
                    avg_win REAL DEFAULT 0,
                    avg_loss REAL DEFAULT 0,
                    max_losing_streak INTEGER DEFAULT 0,
                    max_winning_streak INTEGER DEFAULT 0,
                    recovery_factor REAL DEFAULT 0,
                    var_95 REAL,
                    cvar_95 REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Индекс для trade_statistics
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stat_user_period ON trade_statistics(user_id, period_type, period_start)")
            
            # Таблица анализа по парам (для быстрого доступа)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pair_statistics (
                    pair_stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    period_start TIMESTAMP NOT NULL,
                    period_end TIMESTAMP NOT NULL,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    profit_factor REAL DEFAULT 0,
                    avg_pnl REAL DEFAULT 0,
                    best_trade REAL DEFAULT 0,
                    worst_trade REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    UNIQUE(user_id, symbol, period_start)
                )
            """)
            
            # Индекс для pair_statistics
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pair_user_symbol ON pair_statistics(user_id, symbol)")
            
            # Таблица уведомлений (для отслеживания отправленных уведомлений)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    trade_id INTEGER,
                    notification_type TEXT NOT NULL,  -- 'trade_open', 'trade_close', 'alert'
                    message_text TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_sent BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
                )
            """)
            
            # Индекс для notifications
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_user_sent ON notifications(user_id, is_sent, sent_at)")
    
    def _encrypt(self, data: str) -> str:
        """Зашифровать данные"""
        if not data:
            return ""
        return self.cipher.encrypt(data.encode()).decode()
    
    def _decrypt(self, encrypted_data: str) -> str:
        """Расшифровать данные"""
        if not encrypted_data:
            return ""
        return self.cipher.decrypt(encrypted_data.encode()).decode()
    
    # ========== МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========
    
    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить данные пользователя"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            data = dict(row)
            
            # Расшифровываем API ключи
            try:
                if data.get('api_key_encrypted'):
                    decrypted = self._decrypt(data['api_key_encrypted'])
                    if decrypted:
                        data['api_key'] = decrypted
                if data.get('secret_key_encrypted'):
                    decrypted = self._decrypt(data['secret_key_encrypted'])
                    if decrypted:
                        data['secret_key'] = decrypted
            except Exception as e:
                print(f"Ошибка расшифровки API ключей для пользователя {user_id}: {e}")
                # Оставляем ключи пустыми если не удалось расшифровать
            
            # Парсим JSON поля
            if data.get('trading_pairs'):
                try:
                    data['trading_pairs'] = json.loads(data['trading_pairs'])
                except:
                    data['trading_pairs'] = []
            else:
                data['trading_pairs'] = []
            
            return data
    
    def create_or_update_user(self, user_id: int, data: Dict[str, Any]) -> bool:
        """Создать или обновить пользователя"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем существование пользователя
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            exists = cursor.fetchone() is not None
            
            # Подготовка данных
            api_key_encrypted = None
            secret_key_encrypted = None
            if data.get('api_key'):
                api_key_encrypted = self._encrypt(data['api_key'])
            if data.get('secret_key'):
                secret_key_encrypted = self._encrypt(data['secret_key'])
            
            trading_pairs_json = json.dumps(data.get('trading_pairs', []))
            
            if exists:
                # Обновление - обновляем ключи только если они указаны
                # Строим SQL запрос динамически в зависимости от наличия ключей
                update_fields = []
                update_values = []
                
                if api_key_encrypted is not None:
                    update_fields.append("api_key_encrypted = ?")
                    update_values.append(api_key_encrypted)
                if secret_key_encrypted is not None:
                    update_fields.append("secret_key_encrypted = ?")
                    update_values.append(secret_key_encrypted)
                
                # Всегда обновляем остальные поля
                update_fields.extend([
                    "is_demo_mode = ?",
                    "risk_per_trade = ?",
                    "take_profit_percent = ?",
                    "stop_loss_percent = ?",
                    "leverage = ?",
                    "max_open_positions = ?",
                    "trading_pairs = ?",
                    "auto_trading_enabled = ?",
                    "notifications_enabled = ?",
                    "demo_balance = ?",
                    "max_drawdown_percent = ?",
                    "strategy_profile = ?",
                    "sl_cooldown_minutes = ?",
                    "atr_min_percent = ?",
                    "timeframe = ?",
                    "htf_timeframe = ?",
                    "updated_at = CURRENT_TIMESTAMP"
                ])
                
                update_values.extend([
                    data.get('is_demo_mode', True),
                    data.get('risk_per_trade', 1.5),
                    data.get('take_profit_percent', 3.0),
                    data.get('stop_loss_percent', 1.5),
                    data.get('leverage', 5),
                    data.get('max_open_positions', 5),
                    trading_pairs_json,
                    data.get('auto_trading_enabled', False),
                    data.get('notifications_enabled', True),
                    data.get('demo_balance', 10000.0),
                    data.get('max_drawdown_percent', 20.0),
                    data.get('strategy_profile', 'scalp_smc_v2'),
                    data.get('sl_cooldown_minutes', 15),
                    data.get('atr_min_percent', 0.25),
                    data.get('timeframe', '5m'),
                    data.get('htf_timeframe', '1h'),
                    user_id
                ])
                
                sql = f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = ?"
                cursor.execute(sql, update_values)
            else:
                # Создание
                cursor.execute("""
                    INSERT INTO users (
                        user_id, api_key_encrypted, secret_key_encrypted,
                        is_demo_mode, risk_per_trade, take_profit_percent,
                        stop_loss_percent, leverage, max_open_positions,
                        trading_pairs, auto_trading_enabled, notifications_enabled,
                        demo_balance, max_drawdown_percent, strategy_profile,
                        sl_cooldown_minutes, atr_min_percent, timeframe, htf_timeframe
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    api_key_encrypted,
                    secret_key_encrypted,
                    data.get('is_demo_mode', True),
                    data.get('risk_per_trade', 1.5),
                    data.get('take_profit_percent', 3.0),
                    data.get('stop_loss_percent', 1.5),
                    data.get('leverage', 5),
                    data.get('max_open_positions', 5),
                    trading_pairs_json,
                    data.get('auto_trading_enabled', False),
                    data.get('notifications_enabled', True),
                    data.get('demo_balance', 10000.0),
                    data.get('max_drawdown_percent', 20.0),
                    data.get('strategy_profile', 'scalp_smc_v2'),
                    data.get('sl_cooldown_minutes', 15),
                    data.get('atr_min_percent', 0.25),
                    data.get('timeframe', '5m'),
                    data.get('htf_timeframe', '1h')
                ))
            
            return True
    
    def update_user_setting(self, user_id: int, key: str, value: Any) -> bool:
        """Обновить настройку пользователя"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        user[key] = value
        return self.create_or_update_user(user_id, user)
    
    # ========== МЕТОДЫ ДЛЯ СДЕЛОК ==========
    
    def create_trade(self, user_id: int, trade_data: Dict[str, Any]) -> int:
        """Создать новую сделку и вернуть её ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (
                    user_id, symbol, direction, amount, entry_price,
                    stop_loss, take_profit, leverage, status, pnl,
                    position_value, risk_amount, potential_profit,
                    risk_reward_ratio, probability, quality_score,
                    signal_strength, scale_factor, order_id, is_demo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                trade_data.get('symbol'),
                trade_data.get('direction'),
                trade_data.get('amount'),
                trade_data.get('entry'),
                trade_data.get('stop_loss'),
                trade_data.get('take_profit'),
                trade_data.get('leverage', 5),
                'open',
                0,
                trade_data.get('position_value'),
                trade_data.get('risk_amount'),
                trade_data.get('potential_profit'),
                trade_data.get('risk_reward_ratio'),
                trade_data.get('probability'),
                trade_data.get('quality_score'),
                trade_data.get('signal_strength'),
                trade_data.get('scale_factor'),
                trade_data.get('order_id'),
                trade_data.get('is_demo', True)
            ))
            return cursor.lastrowid
    
    def close_trade(self, trade_id: int, close_price: float, close_reason: str, pnl: float) -> bool:
        """Закрыть сделку"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trades SET
                    status = 'closed',
                    close_price = ?,
                    close_reason = ?,
                    close_time = CURRENT_TIMESTAMP,
                    pnl = ?
                WHERE trade_id = ?
            """, (close_price, close_reason, pnl, trade_id))
            return cursor.rowcount > 0
    
    def get_open_trades(self, user_id: int, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить открытые сделки"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if symbol:
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE user_id = ? AND status = 'open' AND symbol = ?
                    ORDER BY entry_time DESC
                """, (user_id, symbol))
            else:
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE user_id = ? AND status = 'open'
                    ORDER BY entry_time DESC
                """, (user_id,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_closed_trades(
        self, 
        user_id: int, 
        limit: int = 100,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Получить закрытые сделки с фильтрацией"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM trades WHERE user_id = ? AND status = 'closed'"
            params = [user_id]
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            
            if start_date:
                query += " AND close_time >= ?"
                params.append(start_date.isoformat())
            
            if end_date:
                query += " AND close_time <= ?"
                params.append(end_date.isoformat())
            
            query += " ORDER BY close_time DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_all_trades(
        self,
        user_id: int,
        limit: int = 1000,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Получить все сделки (открытые и закрытые)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if status:
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE user_id = ? AND status = ?
                    ORDER BY entry_time DESC
                    LIMIT ?
                """, (user_id, status, limit))
            else:
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE user_id = ?
                    ORDER BY entry_time DESC
                    LIMIT ?
                """, (user_id, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_trade_by_id(self, trade_id: int) -> Optional[Dict[str, Any]]:
        """Получить сделку по ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_trade(self, trade_id: int, updates: Dict[str, Any]) -> bool:
        """Обновить данные сделки"""
        if not updates:
            return False

        invalid = set(updates.keys()) - _TRADES_COLUMNS
        if invalid:
            raise ValueError(f"Недопустимые поля trades: {invalid}")

        set_clauses = []
        params = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            params.append(value)
        
        params.append(trade_id)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE trades SET {', '.join(set_clauses)} WHERE trade_id = ?",
                params
            )
            return cursor.rowcount > 0
    
    # ========== МЕТОДЫ ДЛЯ СТАТИСТИКИ ==========
    
    def save_trade_statistics(self, user_id: int, stats: Dict[str, Any]) -> int:
        """Сохранить агрегированную статистику"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_statistics (
                    user_id, period_start, period_end, period_type,
                    total_trades, winning_trades, losing_trades,
                    total_profit, total_loss, net_profit, win_rate,
                    profit_factor, max_drawdown, sharpe_ratio, sortino_ratio,
                    avg_win, avg_loss, max_losing_streak, max_winning_streak,
                    recovery_factor, var_95, cvar_95
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                stats.get('period_start'),
                stats.get('period_end'),
                stats.get('period_type'),
                stats.get('total_trades', 0),
                stats.get('winning_trades', 0),
                stats.get('losing_trades', 0),
                stats.get('total_profit', 0),
                stats.get('total_loss', 0),
                stats.get('net_profit', 0),
                stats.get('win_rate', 0),
                stats.get('profit_factor', 0),
                stats.get('max_drawdown', 0),
                stats.get('sharpe', 0),
                stats.get('sortino_ratio', 0),
                stats.get('avg_win', 0),
                stats.get('avg_loss', 0),
                stats.get('max_losing_streak', 0),
                stats.get('max_winning_streak', 0),
                stats.get('recovery_factor', 0),
                stats.get('var_95'),
                stats.get('cvar_95')
            ))
            return cursor.lastrowid
    
    def save_pair_statistics(self, user_id: int, symbol: str, stats: Dict[str, Any], 
                            period_start: datetime, period_end: datetime) -> bool:
        """Сохранить статистику по паре"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO pair_statistics (
                    user_id, symbol, period_start, period_end,
                    total_trades, winning_trades, losing_trades,
                    total_pnl, win_rate, profit_factor, avg_pnl,
                    best_trade, worst_trade
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, symbol, period_start.isoformat(), period_end.isoformat(),
                stats.get('total_trades', 0),
                stats.get('winning_trades', 0),
                stats.get('losing_trades', 0),
                stats.get('total_pnl', 0),
                stats.get('win_rate', 0),
                stats.get('profit_factor', 0),
                stats.get('avg_pnl', 0),
                stats.get('best_trade', 0),
                stats.get('worst_trade', 0)
            ))
            return True
    
    # ========== МЕТОДЫ ДЛЯ УВЕДОМЛЕНИЙ ==========
    
    def log_notification(self, user_id: int, notification_type: str, 
                        message_text: str, trade_id: Optional[int] = None) -> int:
        """Записать уведомление в БД"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notifications (
                    user_id, trade_id, notification_type, message_text
                ) VALUES (?, ?, ?, ?)
            """, (user_id, trade_id, notification_type, message_text))
            return cursor.lastrowid
    
    def get_notifications(self, user_id: int, limit: int = 50, 
                         notification_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить историю уведомлений"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if notification_type:
                cursor.execute("""
                    SELECT * FROM notifications 
                    WHERE user_id = ? AND notification_type = ?
                    ORDER BY sent_at DESC
                    LIMIT ?
                """, (user_id, notification_type, limit))
            else:
                cursor.execute("""
                    SELECT * FROM notifications 
                    WHERE user_id = ?
                    ORDER BY sent_at DESC
                    LIMIT ?
                """, (user_id, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    # ========== МИГРАЦИЯ ДАННЫХ ==========
    
    def migrate_from_json(self, user_id: int, json_file_path: Path) -> bool:
        """Мигрировать данные из JSON файла в БД"""
        try:
            if not json_file_path.exists():
                return False
            
            with open(json_file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # Мигрируем данные пользователя
            user_data = {
                'is_demo_mode': json_data.get('is_demo_mode', True),
                'risk_per_trade': json_data.get('risk_per_trade', 1.5),
                'take_profit_percent': json_data.get('take_profit_percent', 3.0),
                'stop_loss_percent': json_data.get('stop_loss_percent', 1.5),
                'leverage': json_data.get('leverage', 5),
                'max_open_positions': json_data.get('max_open_positions', 5),
                'trading_pairs': json_data.get('trading_pairs', []),
                'auto_trading_enabled': json_data.get('auto_trading_enabled', False),
                'notifications_enabled': json_data.get('notifications_enabled', True),
                'demo_balance': json_data.get('demo_balance', 10000.0),
                'max_drawdown_percent': json_data.get('max_drawdown_percent', 20.0),
                'strategy_profile': json_data.get('strategy_profile', 'scalp_smc_v2'),
                'sl_cooldown_minutes': json_data.get('sl_cooldown_minutes', 15),
                'atr_min_percent': json_data.get('atr_min_percent', 0.25),
                'timeframe': json_data.get('timeframe', '5m'),
                'htf_timeframe': json_data.get('htf_timeframe', '1h'),
            }
            
            # Расшифровываем API ключи если они есть
            if 'api_key_encrypted' in json_data:
                # Ключи уже зашифрованы в JSON, сохраняем как есть
                user_data['api_key'] = None  # Будет расшифровано при чтении
                user_data['secret_key'] = None
            
            self.create_or_update_user(user_id, user_data)
            
            # Мигрируем сделки
            demo_positions = json_data.get('demo_positions', [])
            for pos in demo_positions:
                trade_data = {
                    'symbol': pos.get('symbol'),
                    'direction': pos.get('direction', 'long'),
                    'amount': pos.get('amount', 0),
                    'entry': pos.get('entry', 0),
                    'stop_loss': pos.get('stop_loss'),
                    'take_profit': pos.get('take_profit'),
                    'leverage': json_data.get('leverage', 5),
                    'is_demo': True,
                    'position_value': pos.get('entry', 0) * pos.get('amount', 0) if pos.get('entry') and pos.get('amount') else 0
                }
                
                trade_id = self.create_trade(user_id, trade_data)
                
                # Если сделка закрыта - обновляем
                if pos.get('status') == 'closed' and pos.get('close_price'):
                    self.close_trade(
                        trade_id,
                        pos.get('close_price'),
                        pos.get('close_reason', ''),
                        pos.get('pnl', 0)
                    )
            
            return True
        except Exception as e:
            print(f"Ошибка миграции данных для пользователя {user_id}: {e}")
            return False
    
    def migrate_all_json_files(self, data_dir: str = "data") -> int:
        """Мигрировать все JSON файлы в БД"""
        data_path = Path(data_dir)
        migrated = 0
        
        for json_file in data_path.glob("user_*.json"):
            try:
                # Извлекаем user_id из имени файла
                user_id_str = json_file.stem.replace("user_", "")
                user_id = int(user_id_str)
                
                if self.migrate_from_json(user_id, json_file):
                    migrated += 1
                    print(f"✅ Мигрированы данные пользователя {user_id}")
            except Exception as e:
                print(f"❌ Ошибка миграции {json_file}: {e}")
        
        return migrated


# Глобальный экземпляр БД
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Получить глобальный экземпляр БД (singleton)"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
