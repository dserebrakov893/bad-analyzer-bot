import logging
import os
import subprocess

from config import TELEGRAM_TOKEN
from bot import build_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

WEBHOOK_HOST = "https://worker-production-be17.up.railway.app"
LISTEN_PORT  = 8443


def run() -> None:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        commit = "unknown"
    logger.info("=== BAD-ANALYZER-BOT STARTED (webhook) | commit=%s | PID=%s ===", commit, os.getpid())

    app = build_app(TELEGRAM_TOKEN)

    webhook_url = f"{WEBHOOK_HOST}/{TELEGRAM_TOKEN}"
    logger.info("Webhook URL: %s", webhook_url)

    app.run_webhook(
        listen="0.0.0.0",
        port=LISTEN_PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    run()
