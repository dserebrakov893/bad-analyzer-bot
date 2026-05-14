import fcntl
import logging
import os
import sys
from config import TELEGRAM_TOKEN
from bot import build_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

LOCK_FILE = "/tmp/bad-analyzer-bot.lock"
_lock_fh = None


def acquire_lock():
    global _lock_fh
    _lock_fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fh.write(str(os.getpid()))
        _lock_fh.flush()
    except OSError:
        logger.error("Бот уже запущен. Завершение.")
        sys.exit(1)


def release_lock():
    global _lock_fh
    if _lock_fh:
        fcntl.flock(_lock_fh, fcntl.LOCK_UN)
        _lock_fh.close()
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def main() -> None:
    acquire_lock()
    try:
        logger.info("Запуск бота (PID %s)...", os.getpid())
        app = build_app(TELEGRAM_TOKEN)
        logger.info("Polling started. Нажмите Ctrl+C для остановки.")
        app.run_polling(drop_pending_updates=True)
        logger.info("Бот остановлен.")
    finally:
        release_lock()


if __name__ == "__main__":
    main()
