import logging
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, ADMIN_IDS

logger = logging.getLogger(__name__)

_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FREE_LIMIT = 3


def get_or_create_user(user_id: int) -> dict:
    """Возвращает запись пользователя, создаёт если не существует."""
    res = (
        _client.table("users")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]

    new_user = {"user_id": user_id, "requests_count": 0, "is_subscribed": False}
    insert = _client.table("users").insert(new_user).execute()
    logger.info("Новый пользователь создан: %s", user_id)
    return insert.data[0]


def is_allowed(user_id: int) -> bool:
    """True если пользователь подписан или не исчерпал лимит бесплатных запросов."""
    # Администраторы всегда имеют доступ
    if user_id in ADMIN_IDS:
        return True

    user = get_or_create_user(user_id)
    count = user.get("requests_count", 0)

    if user.get("is_subscribed"):
        until = user.get("subscribed_until")
        if until:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if until_dt < datetime.now(timezone.utc):
                _client.table("users").update({
                    "is_subscribed": False,
                    "subscribed_until": None,
                }).eq("user_id", user_id).execute()
                logger.info("Подписка истекла у пользователя %s", user_id)
            else:
                return True

    return count < FREE_LIMIT


def increment_requests(user_id: int, product_name: str) -> int:
    """Увеличивает счётчик запросов и логирует в таблицу requests. Возвращает новый счётчик."""
    user = get_or_create_user(user_id)
    new_count = user.get("requests_count", 0) + 1

    _client.table("users").update({"requests_count": new_count}).eq("user_id", user_id).execute()

    _client.table("requests").insert({
        "user_id": user_id,
        "product_name": product_name[:500],  # обрезаем на случай длинного текста
    }).execute()

    logger.info("Запрос #%s от пользователя %s: %s", new_count, user_id, product_name[:80])
    return new_count


def set_subscribed(user_id: int, days: int) -> None:
    """Активирует подписку на указанное количество дней."""
    get_or_create_user(user_id)  # гарантируем существование записи

    until = datetime.now(timezone.utc) + timedelta(days=days)
    _client.table("users").update({
        "is_subscribed": True,
        "subscribed_until": until.isoformat(),
    }).eq("user_id", user_id).execute()

    logger.info("Подписка активирована для %s до %s", user_id, until.strftime("%Y-%m-%d"))


def remaining_free(user_id: int) -> int:
    """Возвращает количество оставшихся бесплатных запросов."""
    user = get_or_create_user(user_id)
    used = user.get("requests_count", 0)
    return max(0, FREE_LIMIT - used)


def get_stats() -> dict:
    """Возвращает статистику для админа."""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    total_users = len(
        _client.table("users").select("user_id").execute().data
    )
    new_week = len(
        _client.table("users").select("user_id")
        .gte("created_at", week_ago).execute().data
    )
    subscribers = len(
        _client.table("users").select("user_id")
        .eq("is_subscribed", True).execute().data
    )
    requests_today = len(
        _client.table("requests").select("id")
        .gte("created_at", today_start).execute().data
    )
    requests_week = len(
        _client.table("requests").select("id")
        .gte("created_at", week_ago).execute().data
    )

    # Топ-5 продуктов
    all_requests = _client.table("requests").select("product_name").execute().data
    counter: dict[str, int] = {}
    for row in all_requests:
        name = (row.get("product_name") or "—").strip()
        if name:
            counter[name] = counter.get(name, 0) + 1
    top5 = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_users": total_users,
        "new_week": new_week,
        "subscribers": subscribers,
        "requests_today": requests_today,
        "requests_week": requests_week,
        "top_products": top5,
    }
