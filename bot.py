import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME

# === Каналы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === Слова-фильтр
filter_words = set()
morph = pymorphy2.MorphAnalyzer(lang='ru')

def load_filter_words():
    global filter_words
    if os.path.exists('filter_words.txt'):
        with open('filter_words.txt', 'r', encoding='utf-8') as f:
            filter_words.clear()
            for line in f:
                word = line.strip().lower()
                if word:
                    lemma = morph.parse(word)[0].normal_form
                    filter_words.add(lemma)

def normalize_text(text):
    words = text.lower().split()
    return {morph.parse(word)[0].normal_form for word in words}

def sanitize_input(text):
    text = re.sub(r'https?://\S+', '[ссылка]', text)
    text = re.sub(r'[^\wа-яА-ЯёЁ.,:;!?%()\-–—\n ]+', '', text)
    return text.strip()[:2000]

# === Провайдеры
fallback_providers = [
    g4f.Provider.Blackbox,
    g4f.Provider.ChatGLM,
    g4f.Provider.CohereForAI_C4AI_Command,
    g4f.Provider.DocsBot,
    g4f.Provider.Dynaspark,
    g4f.Provider.GizAI,
    g4f.Provider.LambdaChat,
    g4f.Provider.OIVSCodeSer0501,
    g4f.Provider.OIVSCodeSer2,
    g4f.Provider.OIVSCodeSer5,
    g4f.Provider.PollinationsAI,
    g4f.Provider.Qwen_Qwen_2_5,
    g4f.Provider.Qwen_Qwen_2_5M,
    g4f.Provider.Qwen_Qwen_2_5_Max,
    g4f.Provider.Qwen_Qwen_2_72B,
    g4f.Provider.Qwen_Qwen_3,
    g4f.Provider.TeachAnything,
    g4f.Provider.WeWordle,
    g4f.Provider.Websim,
    g4f.Provider.Yqcloud,
]

# === Основная проверка GPT
async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("\n", " "))

    prompt = (
        "Ты ассистент, помогающий отбирать посты для Telegram-канала по арбитражу трафика.\n\n"
        "Тебе НЕЛЬЗЯ допускать к публикации следующие типы постов:\n"
        "- личные посты (о жизни, мотивации, погоде, мнения, размышления, философия)\n"
        "- общая реклама и нецелевые офферы\n"
        "- любые бесполезные и ни о чём тексты, без конкретных действий, результатов или данных\n"
        "- интервью, подкасты, беседы, видеоинтервью\n"
        "- розыгрыши, конкурсы, призы, подарки\n"
        "- посты про вечеринки, конференции, собрания, митапы, тусовки и сходки\n"
        "- лонгриды или колонки без конкретики: без связок, инструментов, цифр или кейсов\n"
        "- жалобы, наблюдения, история развития рынка, «эволюция контента» и т.д.\n\n"
        "Публиковать можно ТОЛЬКО если пост содержит:\n"
        "- конкретную пользу для арбитражников: кейсы, схемы, инсайты, цифры, советы, таблицы\n"
        "- конкретные связки, источники трафика, подходы, платформы, сравнение офферов\n"
        "- полезные инструменты, спай, автоматизацию, API, скрипты, парсеры, настройки\n"
        "- Обзоры или новости об ИИ-инструментах (например, SkyReels, Scira, Sora, ChatGPT, MidJourney, Runway, Leonardo и др.) считаются полезными\n"
        "- новости по платформам, трекерам, банам, обновлениям, платёжкам и т.д.\n\n"
        "Если в тексте нет конкретной пользы — считай его бесполезным.\n"
        "Ответь **одним словом**, выбери только из: реклама, бесполезно, полезно.\n\n"
        f"Анализ:\n\"{clean_text}\""
    )

    async def call_provider(provider):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    g4f.ChatCompletion.create,
                    provider=provider,
                    messages=[{"role": "user", "content": prompt}]
                ),
                timeout=30
            )
            result = (response or "").strip().lower()
            if result in ['реклама', 'бесполезно', 'полезно']:
                return result
        except Exception as e:
            print(f"[GPT ERROR] {provider.__name__}: {str(e)[:100]}")
        return None

    tasks = [call_provider(p) for p in fallback_providers]
    results = await asyncio.gather(*tasks)

    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    valid = 0

    for result in results:
        if result in summary:
            summary[result] += 1
            valid += 1

    if valid == 0:
        await client.send_message(CHANNEL_TRASH, "❌ Ни один GPT-провайдер не дал ответа. Повтор через 30 минут.")
        await asyncio.sleep(1800)
        return await check_with_gpt(text, client)

    await client.send_message(CHANNEL_TRASH, f"📊 GPT результаты:\n{summary}")
    if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]):
        return "полезно"
    else:
        return "мусор"

# === Обработка входящего сообщения
async def handle_message(event, client):
    load_filter_words()

    message_text = event.message.text or ""
    if not message_text.strip():
        return

    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(message_text, client)

    if result == "полезно":
        await event.message.forward_to(CHANNEL_GOOD)
        print("[OK] Репост в основной канал")
    elif result == "мусор":
        await event.message.forward_to(CHANNEL_TRASH)
        print("[OK] Репост в мусорный канал")
    else:
        print("[FAIL] Не удалось классифицировать сообщение")

# === Запуск клиента
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        await handle_message(event, client)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
