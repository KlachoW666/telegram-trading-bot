import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class StrategyProfile:
    key: str
    title: str
    timeframe: str
    htf_timeframe: str
    min_confirmations: int
    atr_min_percent: float
    sl_cooldown_minutes: int
    max_drawdown_percent: float
    scan_pairs_limit: int
    scan_top_n: int


class StrategyProfiles:
    """
    Минимальный слой "как в pycryptobot": профили стратегии через конфиг,
    чтобы менять параметры без правки кода.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else Path("config/strategy_profiles.json")

    def load_raw(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_profiles(self) -> List[StrategyProfile]:
        raw = self.load_raw()
        out: List[StrategyProfile] = []
        for key, cfg in raw.items():
            try:
                out.append(
                    StrategyProfile(
                        key=str(key),
                        title=str(cfg.get("title", key)),
                        timeframe=str(cfg.get("timeframe", "5m")),
                        htf_timeframe=str(cfg.get("htf_timeframe", "1h")),
                        min_confirmations=int(cfg.get("min_confirmations", 3)),
                        atr_min_percent=float(cfg.get("atr_min_percent", 0.25)),
                        sl_cooldown_minutes=int(cfg.get("sl_cooldown_minutes", 15)),
                        max_drawdown_percent=float(cfg.get("max_drawdown_percent", 20.0)),
                        scan_pairs_limit=int(cfg.get("scan_pairs_limit", 30)),
                        scan_top_n=int(cfg.get("scan_top_n", 5)),
                    )
                )
            except Exception:
                continue
        return out

    def get(self, key: str) -> Optional[StrategyProfile]:
        for p in self.list_profiles():
            if p.key == key:
                return p
        return None

    def get_or_default(self, key: Optional[str]) -> StrategyProfile:
        chosen = self.get(key or "")
        if chosen:
            return chosen
        # default: first profile or hardcoded fallback
        profiles = self.list_profiles()
        if profiles:
            return profiles[0]
        return StrategyProfile(
            key="default",
            title="Default",
            timeframe="5m",
            htf_timeframe="1h",
            min_confirmations=3,
            atr_min_percent=0.25,
            sl_cooldown_minutes=15,
            max_drawdown_percent=20.0,
            scan_pairs_limit=30,
            scan_top_n=5,
        )

