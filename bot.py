import asyncio
import os
import time
import pymorphy2
import datetime
import google.generativeai as genai
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME

# === Gemini
API_KEY = "AIzaSyAqUKhMqcDQ5-eqzFoA5LG_95CaoWHet7w"  # ВСТАВЬ СВОЙ КЛЮЧ
genai.configure(api_key=API_KEY)

models = genai.list_models()
flash_models = [
    m.name for m in models
    if "gemini-2.5-flash" in m.name
    and "lite" not in m.name
    and "generateContent" in m.supported_generation_methods
]
if not flash_models:
    raise Exception("Нет доступных моделей gemini-2.5-flash (без lite)")

selected_model = sorted(flash_models)[-1]
print(f"[INFO] Используется модель: {selected_model}")
model = genai.GenerativeModel(selected_model)

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

# === Очередь сообщений
message_queue = asyncio.Queue()
gemini_blocked_until = None

async def check_with_gemini(text, client):
    global gemini_blocked_until
    now = datetime.datetime.utcnow()
    if gemini_blocked_until and now < gemini_blocked_until:
        print(f"[GEMINI] Блок до {gemini_blocked_until}")
        await asyncio.sleep(10)
        return "блок"

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
        "- новости по платформам, трекерам, банам, обновлениям, платёжкам и т.д.\n\n"
        "Если в тексте нет конкретной пользы — считай его бесполезным.\n"
        "Не будь мягким. Отсеивай всё, что не даст выгоды арбитражнику.\n\n"
        f"Анализируй текст поста:\n\"{clean_text}\"\n\n"
        "Ответь **одним словом**, выбрав только из: реклама, бесполезно, полезно."
    )

    for attempt in range(1, 21):
        try:
            await asyncio.sleep(10)
            response = model.generate_content(prompt)
            answer = response.text.strip().lower()
            print(f"[GEMINI] Попытка {attempt}, ответ: {answer}")
            if answer in ['реклама', 'бесполезно', 'полезно']:
                return answer
        except Exception as e:
            print(f"[ERROR] Gemini ошибка: {e}")
            if 'quota' in str(e).lower() or '429' in str(e):
                gemini_blocked_until = now + datetime.timedelta(hours=1)
                await client.send_message(CHANNEL_TRASH, f"❗️Превышен лимит Gemini API. Отключён до {gemini_blocked_until.strftime('%H:%M:%S')} UTC")
                return "блок"
            await asyncio.sleep(3)
    return "ошибка"

async def process_queue(client):
    while True:
        event = await message_queue.get()
        load_filter_words()

        if event.poll or event.voice or event.video_note:
            continue

        if getattr(event.message, 'grouped_id', None):
            continue

        message_text = event.raw_text or ""
        if not message_text.strip():
            continue

        normalized = normalize_text(message_text)
        if filter_words.intersection(normalized):
            continue

        result = await check_with_gemini(message_text, client)

        if result == "полезно":
            await event.forward_to(CHANNEL_GOOD)
            print("[OK] Репост в основной канал")
        elif result in ["реклама", "бесполезно"]:
            await event.forward_to(CHANNEL_TRASH)
            print("[OK] Репост в мусорный канал")
        else:
            print("[FAIL] Не удалось получить результат от Gemini")

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        await message_queue.put(event)

    await asyncio.gather(
        client.run_until_disconnected(),
        process_queue(client)
    )

if __name__ == "__main__":
    asyncio.run(main())
