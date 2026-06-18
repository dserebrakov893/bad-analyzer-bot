import os
from dotenv import load_dotenv

load_dotenv(override=True)

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DATABASE_URL      = os.getenv("DATABASE_URL")
PROXY_URL         = os.getenv("PROXY_URL", "")
ADMIN_ID          = int(os.getenv("ADMIN_ID", "0"))
YUKASSA_TOKEN     = os.getenv("YUKASSA_TOKEN", "")

_admin_ids_raw = os.getenv("ADMIN_IDS", str(ADMIN_ID))
ADMIN_IDS: set[int] = {
    int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()
}

_required = {
    "TELEGRAM_TOKEN":    TELEGRAM_TOKEN,
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "DATABASE_URL":      DATABASE_URL,
}

missing = [k for k, v in _required.items() if not v]
if missing:
    raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")
