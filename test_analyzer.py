import asyncio
from analyzer import analyze_bad

PRODUCTS = [
    "Омега-3 Доппельгерц 1000мг, 30 капсул, 890 руб. EPA 180мг DHA 120мг",
    "Коллаген Эвалар 900мг + витамин C 60мг, 90 таблеток, 1890 руб.",
    "Витамин D3 NOW Foods 5000 IU, 240 капсул, 2200 руб.",
]


async def main():
    for product in PRODUCTS:
        print(f"\n{'='*60}")
        print(f"Продукт: {product}")
        print("Анализирую...")

        result = analyze_bad(user_text=product)
        if asyncio.iscoroutine(result):
            result = await result

        if "error" in result:
            print(f"Ошибка: {result}")
            continue

        price_value = result.get("price_value_ratio", "—")
        verdict = result.get("verdict", "—")
        alternatives = result.get("cheaper_alternatives", [])
        alt_names = ", ".join(a.get("name", "") for a in alternatives) or "не предложено"

        print(f"Цена/польза: {price_value}/10")
        print(f"Вердикт:     {verdict}")
        print(f"Аналоги:     {alt_names}")


asyncio.run(main())
