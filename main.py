import logging
import os
import subprocess
import time

from telegram.error import Conflict

from config import TELEGRAM_TOKEN
from bot import build_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

MAX_RETRY_WAIT = 60
CONFLICT_WAIT  = 30


def run() -> None:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        commit = "unknown"
    logger.info("=== BAD-ANALYZER-BOT STARTED | commit=%s | PID=%s ===", commit, os.getpid())

    retry = 0
    while True:
        try:
            logger.info("Запуск polling (попытка %d)...", retry + 1)
            app = build_app(TELEGRAM_TOKEN)
            app.run_polling(drop_pending_updates=True)
            logger.warning("run_polling завершился — перезапуск через 5 сек...")
            time.sleep(5)
            retry = 0

        except KeyboardInterrupt:
            logger.info("Получен KeyboardInterrupt — остановка.")
            break

        except Conflict:
            retry += 1
            logger.warning("Conflict: другой экземпляр бота ещё работает. Ожидание %d сек (попытка %d)...", CONFLICT_WAIT, retry)
            time.sleep(CONFLICT_WAIT)

        except Exception as e:
            retry += 1
            wait = min(MAX_RETRY_WAIT, 2 ** min(retry, 6))
            logger.error("Бот упал: %s. Перезапуск через %d сек (попытка %d)...", e, wait, retry, exc_info=True)
            time.sleep(wait)


if __name__ == "__main__":
    run()
