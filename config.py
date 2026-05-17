import os
from dotenv import load_dotenv

load_dotenv(override=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PROXY_URL = os.getenv("PROXY_URL")  # опционально, например socks5://127.0.0.1:1080
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Список admin user_id через запятую: "123,456,789"
# Для этих пользователей is_allowed всегда True
_admin_ids_raw = os.getenv("ADMIN_IDS", str(ADMIN_ID))
ADMIN_IDS: set[int] = {
    int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()
}

_required = {
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}

missing = [k for k, v in _required.items() if not v]
if missing:
    raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")
