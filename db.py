import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

from config import ADMIN_IDS

logger = logging.getLogger(__name__)

FREE_LIMIT = 3

_pool: SimpleConnectionPool = None


def _get_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(1, 5, os.getenv("DATABASE_URL"))
    return _pool


@contextmanager
def _db():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_db() -> None:
    """Создаёт таблицы если не существуют."""
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id          BIGINT PRIMARY KEY,
                    requests_count   INTEGER   DEFAULT 0,
                    is_subscribed    BOOLEAN   DEFAULT FALSE,
                    subscribed_until TIMESTAMP,
                    created_at       TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id            SERIAL PRIMARY KEY,
                    user_id       BIGINT,
                    product_name  TEXT,
                    overall_score INTEGER,
                    created_at    TIMESTAMP DEFAULT NOW()
                )
            """)
    logger.info("БД инициализирована")


def get_or_create_user(user_id: int) -> dict:
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO users (user_id, requests_count, is_subscribed)
                VALUES (%s, 0, FALSE)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return dict(cur.fetchone())


def is_allowed(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True

    user = get_or_create_user(user_id)
    count = user.get("requests_count", 0)

    if user.get("is_subscribed"):
        until = user.get("subscribed_until")
        if until:
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if until < datetime.now(timezone.utc):
                with _db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE users
                            SET is_subscribed = FALSE, subscribed_until = NULL
                            WHERE user_id = %s
                        """, (user_id,))
                logger.info("Подписка истекла у пользователя %s", user_id)
            else:
                return True

    return count < FREE_LIMIT


def increment_requests(user_id: int, product_name: str) -> int:
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET requests_count = requests_count + 1
                WHERE user_id = %s
                RETURNING requests_count
            """, (user_id,))
            new_count = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO requests (user_id, product_name) VALUES (%s, %s)",
                (user_id, product_name[:500]),
            )
    logger.info("Запрос #%s от пользователя %s: %s", new_count, user_id, product_name[:80])
    return new_count


def set_subscribed(user_id: int, days: int) -> None:
    get_or_create_user(user_id)
    until = datetime.now(timezone.utc) + timedelta(days=days)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET is_subscribed = TRUE, subscribed_until = %s
                WHERE user_id = %s
            """, (until, user_id))
    logger.info("Подписка активирована для %s до %s", user_id, until.strftime("%Y-%m-%d"))


def remaining_free(user_id: int) -> int:
    user = get_or_create_user(user_id)
    return max(0, FREE_LIMIT - user.get("requests_count", 0))


def get_stats() -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total_users = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= %s", (week_ago,))
            new_week = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM users WHERE is_subscribed = TRUE")
            subscribers = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM requests WHERE created_at >= %s", (today_start,))
            requests_today = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM requests WHERE created_at >= %s", (week_ago,))
            requests_week = cur.fetchone()[0]

            cur.execute("""
                SELECT product_name, COUNT(*) AS cnt
                FROM requests
                GROUP BY product_name
                ORDER BY cnt DESC
                LIMIT 5
            """)
            top5 = [(row[0], row[1]) for row in cur.fetchall()]

    return {
        "total_users": total_users,
        "new_week": new_week,
        "subscribers": subscribers,
        "requests_today": requests_today,
        "requests_week": requests_week,
        "top_products": top5,
    }
