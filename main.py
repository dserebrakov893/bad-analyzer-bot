import logging
import os
import time

from config import TELEGRAM_TOKEN
from bot import build_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

MAX_RETRY_WAIT = 60  # максимальная пауза между перезапусками (сек)


def run() -> None:
    retry = 0
    while True:
        try:
            logger.info("Запуск бота (попытка %d, PID %s)...", retry + 1, os.getpid())
            app = build_app(TELEGRAM_TOKEN)
            app.run_polling(
                drop_pending_updates=True,
                timeout=30,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30,
            )
            # run_polling вернул управление — нештатная ситуация, перезапускаем
            logger.warning("run_polling завершился — перезапуск через 5 сек...")
            time.sleep(5)

        except KeyboardInterrupt:
            logger.info("Получен KeyboardInterrupt — остановка.")
            break

        except Exception as e:
            retry += 1
            wait = min(MAX_RETRY_WAIT, 2 ** min(retry, 6))  # 2, 4, 8, 16, 32, 60, 60...
            logger.error(
                "Бот упал: %s. Перезапуск через %d сек (попытка %d)...",
                e, wait, retry,
                exc_info=True,
            )
            time.sleep(wait)


if __name__ == "__main__":
    run()
