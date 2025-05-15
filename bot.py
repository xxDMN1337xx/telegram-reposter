import asyncio
import os
import json
import time
import pymorphy2
import google.generativeai as genai
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME

# === Gemini
API_KEY = "AIzaSyAqUKhMqcDQ5-eqzFoA5LG_95CaoWHet7w"
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

# === Проверка Gemini
def check_with_gemini(text: str) -> str:
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
            response = model.generate_content(prompt)
            answer = response.text.strip().lower()
            print(f"[GEMINI] Попытка {attempt}, ответ: {answer}")
            if answer in ['реклама', 'бесполезно', 'полезно']:
                return answer
        except Exception as e:
            print(f"[ERROR] Gemini ошибка: {e}")
            time.sleep(2)

    return "ошибка"

# === Главный async блок
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    load_filter_words()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        load_filter_words()

        if event.poll:
            print("[SKIP] Опрос")
            return

        if event.voice or event.video_note:
            print("[SKIP] Голосовое / кружок")
            return

        if getattr(event.message, 'grouped_id', None):
            print("[SKIP] Альбом-элемент (будет обработан отдельно)")
            return

        message_text = event.raw_text or ""
        if not message_text.strip():
            print("[SKIP] Нет текста (пустое сообщение)")
            return

        normalized = normalize_text(message_text)
        if filter_words.intersection(normalized):
            print("[FILTER] Сработал фильтр по словам")
            return

        result = check_with_gemini(message_text)
        if result == "полезно":
            await event.forward_to(CHANNEL_GOOD)
            print("[OK] Репост в основной канал")
        elif result in ["реклама", "бесполезно"]:
            await event.forward_to(CHANNEL_TRASH)
            print("[OK] Репост в мусорный канал")
        else:
            print("[FAIL] Не удалось получить ответ от Gemini")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
