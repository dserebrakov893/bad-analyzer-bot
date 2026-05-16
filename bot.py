from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
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
    "конкретный аналог с ценой\\."
)

# ─── Тексты экранов ───────────────────────────────────────────────────────────

SCREEN_CHECK = (
    "🔬 *Проверить БАД*\n\n"
    "Просто напиши название и состав, например:\n"
    "_Омега\\-3 Доппельгерц 1000мг, EPA 180мг DHA 120мг, 30 капсул, 890 руб_\n\n"
    "Или отправь *фото этикетки* — прочитаю состав сам\\.\n\n"
    "Чем больше информации \\(цена, количество капсул\\) — тем точнее анализ\\."
)

SCREEN_EXAMPLES = (
    "📋 *Примеры разборов*\n\n"
    "🔴 *Омега\\-3 Доппельгерц* — цена/польза 2/10\n"
    "_EPA 180мг \\+ DHA 120мг — в 3–5 раз ниже терапевтической дозы\\. "
    "Переплата за бренд, аналог в 2 раза дешевле\\._\n\n"
    "🔴 *Коллаген Эвалар 900мг* — цена/польза 2/10\n"
    "_Доза в 10 раз ниже нормы \\(нужно 10г/сут\\)\\. "
    "Маркетинговый продукт без реальной эффективности\\._\n\n"
    "🟢 *Витамин D3 NOW Foods 5000 IU* — цена/польза 9/10\n"
    "_Доказанная эффективность, надёжный производитель, "
    "минимальная цена за дозу\\._"
)

SCREEN_HOW = (
    "❓ *Как это работает*\n\n"
    "1\\. Ты присылаешь название БАД или фото этикетки\n"
    "2\\. Я анализирую каждый ингредиент по доказательной базе:\n"
    "   ✅ Доказано — метаанализы, RCT\n"
    "   🟡 Вероятно работает — отдельные исследования\n"
    "   🟠 Мало данных — ограниченные данные\n"
    "   ❌ Не доказано — нет исследований\n\n"
    "3\\. Оцениваю дозу каждого компонента\n"
    "4\\. Считаю цена/польза от 1 до 10\n"
    "5\\. Нахожу аналог дешевле с тем же эффектом\n\n"
    "_Анализирую как нутрициолог, не как маркетолог\\._"
)

SCREEN_SUB = (
    "💳 *Подписка*\n\n"
    "Бесплатно: *3 разбора*\n"
    "Подписка: *149 ₽/мес*\n\n"
    "Это дешевле одной ненужной банки витаминов\\.\n\n"
    "👉 [Оплатить подписку](https://t.me/tribute/app?startapp=dKdT)\n\n"
    "_После оплаты напиши /activate_"
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
            wb = alt.get("wb_price", "")
            ozon = alt.get("ozon_price", "")
            apteka = alt.get("apteka_price", "")
            price_parts = []
            if wb:
                price_parts.append(f"WB: {_esc(wb)}")
            if ozon:
                price_parts.append(f"Ozon: {_esc(ozon)}")
            if apteka:
                price_parts.append(f"Аптека\\.ру: {_esc(apteka)}")
            if price_parts:
                lines.append(f"   _{'  |  '.join(price_parts)}_")
        lines.append(
            "\n⚠️ _Цены ориентировочные — реальные могут отличаться\\. "
            "Проверяй перед покупкой на WB/Ozon/Аптека\\.ру_"
        )
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


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔬 Проверить БАД", callback_data="check")],
        [InlineKeyboardButton("📋 Примеры разборов", callback_data="examples"),
         InlineKeyboardButton("❓ Как это работает", callback_data="how")],
        [InlineKeyboardButton("💳 Подписка", callback_data="sub"),
         InlineKeyboardButton("📊 Мой счёт", callback_data="score")],
    ])


def _back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Главное меню", callback_data="main")]
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        WELCOME,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_main_menu(),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main":
        await query.edit_message_text(WELCOME, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=_main_menu())

    elif data == "check":
        await query.edit_message_text(SCREEN_CHECK, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=_back_menu())

    elif data == "examples":
        await query.edit_message_text(SCREEN_EXAMPLES, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=_back_menu())

    elif data == "how":
        await query.edit_message_text(SCREEN_HOW, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=_back_menu())

    elif data == "sub":
        await query.edit_message_text(SCREEN_SUB, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=_back_menu())

    elif data == "score":
        user_id = query.from_user.id
        user = __import__("db").get_or_create_user(user_id)
        count = user.get("requests_count", 0)
        subscribed = user.get("is_subscribed", False)
        until = user.get("subscribed_until", "")

        if subscribed and until:
            from datetime import datetime, timezone
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            until_str = _esc(until_dt.strftime("%d.%m.%Y"))
            status = f"💳 Подписка активна до {until_str}"
        elif subscribed:
            status = "💳 Подписка активна"
        else:
            remaining = max(0, 3 - count)
            status = f"🆓 Бесплатных разборов осталось: *{remaining}/3*"

        text = (
            "📊 *Мой счёт*\n\n"
            f"Всего запросов: *{_esc(str(count))}*\n"
            f"{status}"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=_back_menu())


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
    user_id = update.effective_user.id
    user_text = update.message.text.strip()

    # Есть сохранённое фото — значит пользователь отвечает ценой
    image_bytes: bytes = context.user_data.pop("pending_photo", None)
    if image_bytes:
        user_text_full = f"Проанализируй состав БАД на этикетке.\nЦена упаковки: {user_text} руб."
        if not await _check_allowed(update):
            return
        await update.message.chat.send_action("typing")
        data = await analyze_bad(
            user_text=user_text_full,
            image_base64=image_to_base64(image_bytes),
            image_bytes=image_bytes,
        )
        await _send_result(update, data)
        if "error" not in data:
            increment_requests(user_id, data.get("product_name", user_text_full[:100]))
        return

    # Обычный текстовый запрос
    if not await _check_allowed(update):
        return
    await update.message.chat.send_action("typing")
    data = await analyze_bad(user_text=user_text)
    await _send_result(update, data)
    if "error" not in data:
        increment_requests(user_id, data.get("product_name", user_text[:100]))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_allowed(update):
        return

    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())

    context.user_data["pending_photo"] = image_bytes

    await update.message.reply_text(
        "Фото получил\\! Укажи цену с упаковки в рублях — подберу аналог дешевле 👇",
        parse_mode="MarkdownV2",
    )


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
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
