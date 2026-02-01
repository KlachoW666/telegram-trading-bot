from aiogram.fsm.state import State, StatesGroup


class TradingStates(StatesGroup):
    """Состояния для торговли"""
    waiting_for_pair = State()
    waiting_for_direction = State()
    waiting_for_volume = State()
    waiting_for_tp = State()
    waiting_for_sl = State()


class SettingsStates(StatesGroup):
    """Состояния для настроек"""
    waiting_for_api_key = State()
    waiting_for_secret_key = State()
    waiting_for_risk_percent = State()
    waiting_for_tp_percent = State()
    waiting_for_sl_percent = State()
    waiting_for_max_positions = State()
    waiting_for_pair_selection = State()


class AnalysisStates(StatesGroup):
    """Состояния для анализа"""
    waiting_for_pair_analysis = State()
