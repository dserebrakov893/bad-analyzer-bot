from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from analyzer import analyze_bad, image_to_base64
from config import PROXY_URL, ADMIN_ID
from db import is_allowed, increment_requests, set_subscribed, remaining_free, get_stats

# ─── Константы ───────────────────────────────────────────────────────────────

TG_LIMIT = 4096

WELCOME = (
    "Средний россиянин тратит *4 200 ₽/мес* на витамины и БАДы\\. "
    "Половина из этого — переплата за бренд и маркетинг\\.\n\n"
    "Я анализирую состав по доказательной базе и нахожу аналог дешевле, "
    "обычно в 2–3 раза\\.\n\n"
    "В отличие от ChatGPT и других LLM, я заточен только под это, "
    "отвечаю структурированно, работаю с фото этикетки и сразу даю "
    "конкретный аналог с ценой\\.\n\n"
    "Пришли любой БАД — покажу где ты переплачиваешь\\.\n\n"
    "_3 разбора бесплатно, далее — подписка 149 ₽/мес\\. "
    "Это дешевле одной ненужной банки\\._"
)

DISCLAIMER = (
    "\n\n_⚕️ Не является медицинской рекомендацией\\. "
    "Проконсультируйтесь с врачом перед приёмом БАД\\._"
)

PAYWALL = (
    "Бесплатные разборы закончились \\(3/3\\) 🔒\n\n"
    "Подписка *149 ₽/мес* — меньше одной ненужной банки:\n"
    "👉 [Оплатить подписку](https://t.me/tribute/app?startapp=dKdT)\n\n"
    "_После оплаты напиши /activate_"
)

EVIDENCE = {
    "A": "✅ Доказано",
    "B": "🟡 Вероятно работает",
    "C": "🟠 Мало данных",
    "D": "❌ Не доказано",
}

DOSE_WARN = {
    "недостаточная": " ⚠️ доза низкая",
    "избыточная": " 🔺 доза высокая",
    "не указана": " ❓",
}


# ─── Форматирование ───────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Экранирует спецсимволы для MarkdownV2."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _score_bar(score) -> str:
    try:
        n = int(score)
    except (TypeError, ValueError):
        return _esc(str(score))
    filled = "▓" * n
    empty = "░" * (10 - n)
    return f"{filled}{empty} *{n}/10*"


def _build_parts(data: dict) -> list[str]:
    """Разбивает результат на логические блоки, каждый не разрывается при отправке."""
    parts = []

    # Шапка
    name = _esc(data.get("product_name", "Неизвестный продукт"))
    overall = data.get("overall_score", "—")
    pv = data.get("price_value_ratio", "—")
    parts.append(
        f"*{name}*\n"
        f"Оценка:        {_score_bar(overall)}\n"
        f"Цена/польза: {_score_bar(pv)}"
    )

    # Вердикт
    verdict = data.get("verdict", "")
    if verdict:
        parts.append(f"💬 _{_esc(verdict)}_")

    # Состав
    ingredients = data.get("ingredients", [])
    if ingredients:
        lines = ["*📋 Состав:*"]
        for ing in ingredients:
            ev_key = ing.get("evidence_level", "?")
            ev_label = _esc(EVIDENCE.get(ev_key, ev_key))
            ing_name = _esc(ing.get("name", "?"))
            amount = ing.get("amount", "")
            amount_str = f" — {_esc(amount)}" if amount and amount != "не указана" else ""
            dose_key = ing.get("dose_assessment", "")
            dose_str = _esc(DOSE_WARN.get(dose_key, ""))
            benefit = ing.get("benefit", "")
            benefit_str = f"\n   _{_esc(benefit)}_" if benefit else ""

            lines.append(
                f"{ev_label} *{ing_name}*{amount_str}{dose_str}{benefit_str}"
            )
        parts.append("\n".join(lines))

    # Плюсы / минусы
    pros = data.get("pros", [])
    cons = data.get("cons", [])
    if pros or cons:
        pc = []
        if pros:
            pc.append("*Плюсы:*")
            pc += [f"\\+ {_esc(p)}" for p in pros]
        if cons:
            pc.append("*Минусы:*")
            pc += [f"\\- {_esc(c)}" for c in cons]
        parts.append("\n".join(pc))

    # Предупреждения
    warnings = data.get("interactions_warnings", "")
    if warnings and warnings.lower() not in ("не выявлено", ""):
        parts.append(f"⚠️ *Взаимодействия:* {_esc(warnings)}")

    # Аналоги
    alternatives = data.get("cheaper_alternatives", [])
    if alternatives:
        lines = ["*💰 Дешевле и не хуже:*"]
        for alt in alternatives:
            alt_name = _esc(alt.get("name", "?"))
            alt_reason = _esc(alt.get("reason", ""))
            lines.append(f"• *{alt_name}* — {alt_reason}")
        parts.append("\n".join(lines))

    # Итог
    rec = data.get("recommendation", "")
    if rec:
        parts.append(f"*🏁 Итог:* {_esc(rec)}")

    return parts


def format_result(data: dict) -> list[str]:
    """Возвращает список сообщений ≤ TG_LIMIT символов каждое."""
    if "error" in data:
        err = _esc(str(data.get("error", "unknown")))
        return [f"❌ Ошибка анализа: `{err}`"]

    parts = _build_parts(data)
    messages: list[str] = []
    current = ""

    for part in parts:
        sep = "\n\n" if current else ""
        candidate = current + sep + part

        if len(candidate) + len(DISCLAIMER) <= TG_LIMIT:
            current = candidate
        else:
            if current:
                messages.append(current)
            # Блок сам по себе большой — режем по строкам
            if len(part) + len(DISCLAIMER) > TG_LIMIT:
                current = ""
                for line in part.split("\n"):
                    sep2 = "\n" if current else ""
                    if len(current + sep2 + line) + len(DISCLAIMER) <= TG_LIMIT:
                        current = current + sep2 + line
                    else:
                        if current:
                            messages.append(current)
                        current = line
            else:
                current = part

    if current:
        messages.append(current)

    if messages:
        messages[-1] += DISCLAIMER

    return messages or ["Нет данных для отображения\\."]


# ─── Хэндлеры ────────────────────────────────────────────────────────────────

async def _send_result(update: Update, data: dict) -> None:
    for msg in format_result(data):
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN_V2)


async def _check_allowed(update: Update) -> bool:
    """Проверяет лимит. Если исчерпан — отправляет paywall и возвращает False."""
    user_id = update.effective_user.id
    allowed = is_allowed(user_id)
    if not allowed:
        await update.message.reply_text(PAYWALL, parse_mode=ParseMode.MARKDOWN_V2)
        return False
    return True


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Нет доступа\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Запрос статистики от %s", update.effective_user.id)

        s = get_stats()
        logger.info("Статистика получена: %s", s)

        top_lines = ""
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, (name, count) in enumerate(s["top_products"]):
            short = name[:40] + "…" if len(name) > 40 else name
            top_lines += f"\n{medals[i]} {_esc(short)} — {count}"

        text = (
            "📊 *Статистика бота*\n"
            "\n"
            f"👥 Всего пользователей: *{s['total_users']}*\n"
            f"🆕 Новых за 7 дней: *{s['new_week']}*\n"
            f"💳 Платящих подписчиков: *{s['subscribers']}*\n"
            "\n"
            f"📨 Запросов сегодня: *{s['requests_today']}*\n"
            f"📈 Запросов за 7 дней: *{s['requests_week']}*\n"
        )

        if top_lines:
            text += f"\n🔥 *Топ продуктов:*{top_lines}"

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Ошибка /stats: %s", e, exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: `{_esc(str(e))}`", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(f"Твой Telegram ID: `{uid}`", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller_id = update.effective_user.id

    if caller_id != ADMIN_ID:
        await update.message.reply_text("⛔ Нет доступа\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Использование: `/activate 123456789`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    target_id = int(args[0])
    set_subscribed(target_id, days=30)
    await update.message.reply_text(
        f"✅ Подписка активирована для `{target_id}` на 30 дней\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_allowed(update):
        return

    user_id = update.effective_user.id
    user_text = update.message.text

    await update.message.chat.send_action("typing")
    data = await analyze_bad(user_text=user_text)
    await _send_result(update, data)

    if "error" not in data:
        product = data.get("product_name", user_text[:100])
        increment_requests(user_id, product)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_allowed(update):
        return

    user_id = update.effective_user.id

    await update.message.chat.send_action("typing")

    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())

    caption = update.message.caption or "Проанализируй состав БАД на этикетке"
    data = await analyze_bad(
        user_text=caption,
        image_base64=image_to_base64(image_bytes),
        image_bytes=image_bytes,
    )
    await _send_result(update, data)

    if "error" not in data:
        product = data.get("product_name", caption[:100])
        increment_requests(user_id, product)


# ─── Сборка приложения ────────────────────────────────────────────────────────

def build_app(token: str):
    builder = ApplicationBuilder().token(token)
    if PROXY_URL:
        builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
    app = builder.build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("activate", cmd_activate))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    return app
