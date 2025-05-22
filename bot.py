import asyncio
import os
import datetime
import pymorphy2
import g4f
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME

# опционально подавить предупреждение:
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)


# === Каналы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === Лемматизация + фильтр слов
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

# === Провайдеры без авторизации
fallback_providers = [
    g4f.Provider.Yqcloud,
    g4f.Provider.Ails,
    g4f.Provider.Bing,
    g4f.Provider.Theb,
    g4f.Provider.FreeGpt,
    g4f.Provider.ChatBase,
    g4f.Provider.Vercel
]

async def check_with_gpt(text: str, client) -> str:
    clean_text = text.replace('"', "'").replace("\n", " ").strip()

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
        "- AI-инструменты, нейросети, ChatGPT, MidJourney, Sora, автоматизация с помощью ИИ\n"
        "- новости по платформам, трекерам, банам, обновлениям, платёжкам и т.д.\n\n"
        "Если в тексте нет конкретной пользы — считай его бесполезным.\n"
        "Не будь мягким. Отсеивай всё, что не даст выгоды арбитражнику.\n\n"
        f"Анализируй текст поста:\n\"{clean_text}\"\n\n"
        "Ответь **одним словом**, выбери только из: реклама, бесполезно, полезно."
    )

    for provider in fallback_providers:
        try:
            models = getattr(provider, "models", ["gpt-4", "gpt-3.5"])  # допустимые модели
            for model_name in models:
                try:
                    response = g4f.ChatCompletion.create(
                        model=model_name,
                        provider=provider,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    result = response.strip().lower()
                    print(f"[GPT] {provider.__name__} / {model_name} → {result}")
                    await client.send_message(CHANNEL_TRASH, f"✅ GPT ответ ({provider.__name__}, {model_name}): {result}")
                    return result
                except Exception as inner:
                    continue  # пробуем следующий model
        except Exception as e:
            continue  # пробуем следующий provider

    await client.send_message(CHANNEL_TRASH, "❌ Ошибка: не удалось получить ответ от ни одного GPT-провайдера.")
    return "ошибка"

async def handle_message(event, client):
    load_filter_words()

    if event.poll or event.voice or event.video_note:
        return
    if getattr(event.message, 'grouped_id', None):
        return

    message_text = event.raw_text or ""
    if not message_text.strip():
        return

    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(message_text, client)

    if result == "полезно":
        await event.forward_to(CHANNEL_GOOD)
        print("[OK] Репост в основной канал")
    elif result in ["реклама", "бесполезно"]:
        await event.forward_to(CHANNEL_TRASH)
        print("[OK] Репост в мусорный канал")
    else:
        print("[FAIL] GPT не смог классифицировать сообщение")

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        await handle_message(event, client)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
