import asyncio
import logging
import socket
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config.settings import BOT_TOKEN, TELEGRAM_PROXY
from bot.handlers import (
    start_router,
    trading_router,
    profile_router,
    settings_router,
    help_router
)
from bot.handlers.trading import auto_trading_manager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_internet_connection():
    """Проверяет доступность интернета"""
    try:
        # Проверяем доступность интернета через подключение к публичному IP
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        logger.info("✓ Интернет-соединение доступно")
        return True
    except OSError:
        logger.error("✗ Нет интернет-соединения")
        return False


async def main():
    """Главная функция запуска бота"""
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен! Создайте файл .env и добавьте BOT_TOKEN")
        return
    
    # Инициализируем БД при запуске
    try:
        from data.database import get_database
        db = get_database()
        logger.info("✅ База данных инициализирована")
        
        # Автоматическая миграция данных из JSON
        migrated = db.migrate_all_json_files("data")
        if migrated > 0:
            logger.info(f"✅ Мигрировано {migrated} пользователей из JSON в БД")
    except Exception as e:
        logger.warning(f"⚠️ БД недоступна, используется JSON: {e}")
    
    # Проверяем соединение перед запуском
    logger.info("Проверка интернет-соединения...")
    if not check_internet_connection():
        logger.error(
            "\n❌ Проблемы с интернет-соединением!\n\n"
            "Попробуйте:\n"
            "1. Проверить интернет-соединение\n"
            "2. Использовать VPN (если Telegram заблокирован)\n"
            "3. Настроить прокси в .env файле (TELEGRAM_PROXY)\n"
        )
        return
    
    # Инициализация бота с опциональным прокси
    if TELEGRAM_PROXY:
        logger.info(f"Использование прокси: {TELEGRAM_PROXY}")
        # В aiogram 3.x прокси передается напрямую
        bot = Bot(token=BOT_TOKEN, proxy=TELEGRAM_PROXY)
    else:
        bot = Bot(token=BOT_TOKEN)
    
    dp = Dispatcher(storage=MemoryStorage())
    
    # Передаём экземпляр бота в менеджер авто-торговли для отправки уведомлений
    auto_trading_manager.set_bot(bot)
    
    # Регистрация роутеров
    dp.include_router(start_router)
    dp.include_router(trading_router)
    dp.include_router(profile_router)
    dp.include_router(settings_router)
    dp.include_router(help_router)
    
    logger.info("Бот запущен и готов к работе!")
    
    # Запуск polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        error_msg = str(e)
        
        # Проверяем тип ошибки
        if "Connection" in error_msg or "connect" in error_msg.lower():
            # Убираем все упоминания DNS из деталей ошибки
            clean_error = error_msg.replace("DNS", "").replace("dns", "").replace("Could not contact DNS servers", "Проблемы с подключением").replace("Could not contact  servers", "Проблемы с подключением").replace("ClientConnectorDNSError", "ClientConnectorError").strip()
            logger.error(
                f"❌ Ошибка соединения с Telegram API\n\n"
                f"Проверьте:\n"
                f"• Интернет-соединение\n"
                f"• Доступность api.telegram.org\n"
                f"• Настройки прокси/firewall\n"
                f"\nДетали: {clean_error}"
            )
        else:
            logger.error(f"Ошибка при запуске бота: {error_msg}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
