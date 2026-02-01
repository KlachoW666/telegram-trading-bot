from .start import router as start_router
from .trading import router as trading_router
from .profile import router as profile_router
from .settings import router as settings_router
from .help import router as help_router

__all__ = [
    "start_router",
    "trading_router",
    "profile_router",
    "settings_router",
    "help_router",
]
