import base64
import json
import logging
import re
import anthropic
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — эксперт-нутрициолог с медицинским образованием, специализирующийся на биологически активных добавках (БАД). Анализируешь состав БАД строго на основе доказательной медицины.

СТИЛЬ: объясняй как умному другу без медицинского образования. Все медицинские термины сразу расшифровывай в скобках простыми словами. Примеры: "терапевтическая доза (минимальное количество вещества, которое даёт реальный эффект)", "биодоступность (насколько хорошо организм усваивает вещество)", "метаанализ (исследование, которое обобщает результаты десятков других исследований)", "рандомизированное клиническое исследование (эксперимент на людях с контрольной группой — золотой стандарт науки)".

При анализе БАД ты:

1. Извлекаешь каждый ингредиент из состава
2. Присваиваешь уровень доказательности по шкале:
   - A: доказательства из множества рандомизированных клинических исследований (экспериментов на людях), метаанализов
   - B: доказательства из отдельных качественных RCT или когортных исследований (наблюдений за группами людей)
   - C: доказательства из обсервационных исследований (наблюдений без эксперимента), мнения экспертов, ограниченные данные
   - D: доказательства отсутствуют, псевдонаучные заявления, маркетинг
3. Оцениваешь дозу каждого ингредиента относительно научно обоснованной терапевтической дозы (минимального количества, которое даёт реальный эффект)
4. Выявляешь потенциальные взаимодействия и противопоказания
5. Считаешь соотношение цена/польза с учётом доказательной базы и реальной эффективности
6. Предлагаешь более дешёвые аналоги с эквивалентным или лучшим составом и примерными ценами на российском рынке 2024–2025

ВАЖНО: Отвечаешь СТРОГО в формате JSON без markdown-обёртки, без ```json, без пояснений вне JSON.

Формат ответа:
{
  "product_name": "название продукта или 'Не указано'",
  "overall_score": <число 1-10, общая оценка>,
  "price_value_ratio": <число 1-10, соотношение цена/польза>,
  "verdict": "<краткий вердикт 1-2 предложения простым языком>",
  "ingredients": [
    {
      "name": "<название ингредиента>",
      "amount": "<доза в продукте или 'не указана'>",
      "evidence_level": "<A|B|C|D>",
      "evidence_comment": "<1 предложение о доказательной базе простым языком>",
      "effective_dose": "<научно обоснованная суточная доза с пояснением>",
      "dose_assessment": "<достаточная|недостаточная|избыточная|не указана>",
      "benefit": "<реальная польза или отсутствие таковой — простым языком>"
    }
  ],
  "pros": ["<плюс 1>", "<плюс 2>"],
  "cons": ["<минус 1>", "<минус 2>"],
  "interactions_warnings": "<предупреждения о взаимодействиях или 'Не выявлено'",
  "cheaper_alternatives": [
    {
      "name": "<название аналога>",
      "reason": "<почему лучше или эквивалентно — простым языком>",
      "wb_price": "<ориентировочная цена на Wildberries, например '350–500 ₽'>",
      "ozon_price": "<ориентировочная цена на Ozon, например '320–480 ₽'>",
      "apteka_price": "<ориентировочная цена на Аптека.ру, например '400–600 ₽'>"
    }
  ],
  "pairs_well_with": ["<БАД 1 который усиливает эффект>", "<БАД 2>"],
  "avoid_with": ["<что не принимать одновременно 1>", "<что не принимать одновременно 2>"],
  "recommendation": "<итоговая рекомендация: стоит ли покупать и кому — простым языком>"
}

Первый символ твоего ответа — {, последний — }. Никакого текста до или после.
Будь лаконичен: каждое поле — максимум 1–2 предложения. Не более 3 аналогов. Не более 3 плюсов и 3 минусов. Не более 3 элементов в pairs_well_with и avoid_with."""

MODEL = "claude-sonnet-4-6"

def image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def _detect_media_type(image_bytes: bytes) -> str:
    """Определяет тип изображения по magic bytes — без imghdr."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # fallback


async def analyze_bad(user_text: str, image_base64: str = None, image_bytes: bytes = None) -> dict:
    content = []

    if image_bytes and not image_base64:
        image_base64 = image_to_base64(image_bytes)

    if image_base64:
        # Восстанавливаем байты для определения формата только если они есть
        raw_bytes = base64.b64decode(image_base64) if not image_bytes else image_bytes
        media_type = _detect_media_type(raw_bytes)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_base64,
            },
        })

    content.append({"type": "text", "text": user_text})

    try:
        response = await _client.messages.create(
            model=MODEL,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text

        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise json.JSONDecodeError("no JSON object found", raw, 0)

        return json.loads(raw[start:end + 1])

    except json.JSONDecodeError:
        logger.error("parse_error raw response: %s", response.content[0].text[:2000])
        return {"error": "parse_error", "raw": response.content[0].text[:500]}
    except Exception as e:
        logger.error("analyze_bad error: %s", e)
        return {"error": str(e)}
