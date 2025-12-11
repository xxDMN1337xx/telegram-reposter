import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import Message
from config import API_ID, API_HASH, SESSION_NAME

# === Каналы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === Источники с копированием (channel_id: ссылка)
COPY_CHANNELS = {
    1672980976: "https://t.me/piratecpa",      # piratecpa, piratcpa, arbitrazh_traffika, web3traff
    2530485449: "https://t.me/huihuihui111111111111",
    2101853050: "https://t.me/sapogcpa"
}

# === Провайдеры
fallback_providers = [
    g4f.Provider.CohereForAI_C4AI_Command,
    g4f.Provider.Yqcloud,
    g4f.Provider.WeWordle,
    g4f.Provider.OperaAria,
    g4f.Provider.AnyProvider,
    g4f.Provider.BAAI_Ling
]

# === Очистка текста
def sanitize_input(text):
    text = re.sub(r'https?://\S+', '[ссылка]', text)
    text = re.sub(r'[^\wа-яА-ЯёЁ.,:;!?%()\-–—\n ]+', '', text)
    return text.strip()[:2000]

# === Лемматизация
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

# === Проверка GPT
async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("\n", " "))

    prompt = (
        "Твоя роль: Строгий главный редактор приватного канала для профессионалов в арбитраже трафика (CPA, Affiliate Marketing).\n"
        "Твоя задача: Жестко фильтровать входящий поток постов. Аудитория — опытные вебмастера, им не нужна вода.\n\n"

        "🔴 КАТЕГОРИЯ 'БЕСПОЛЕЗНО' (Мусор):"
        "- Приветствия, пожелания доброго утра/ночи, вопросы 'как дела?'."
        "- Философия, размышления о жизни, мотивация, 'успешный успех', психология."
        "- Новости, не влияющие на заработок (политика, погода, сплетни)."
        "- Анонсы стримов, войсчатов, митапов, вечеринок (без текстовой выжимки пользы)."
        "- Розыгрыши денег, айфонов, билетов, призы за подписку."
        "- Любые вопросы к аудитории ('А как вы льете?', 'Посоветуйте сервисы').\n\n"

        "🔴 КАТЕГОРИЯ 'РЕКЛАМА' (Спам):"
        "- Прямая продажа курсов, наставничества, приваток."
        "- Реклама партнерок (CPA сетей) без приложенного кейса или схемы."
        "- Реклама сервисов без детального обзора их функционала."
        "- Вакансии, поиск сотрудников."
        "- Нативная реклама Telegram-каналов ('подпишись на друга').\n\n"

        "🟢 КАТЕГОРИЯ 'ПОЛЕЗНО' (Публикуем):"
        "- Технические мануалы: как настроить клоаку, трекер, антидетект, прокси."
        "- Кейсы и связки: ОБЯЗАТЕЛЬНО наличие цифр (ROI, Spend, Profit), источника и оффера."
        "- Реальные методы обхода банов Facebook, Google, TikTok (полиси, риски, зрд)."
        "- Скрипты, код, автоматизация, работа с API, парсеры."
        "- Обзоры НОВЫХ ИИ-инструментов, если они помогают делать креативы или тексты (Sora, MidJourney и т.д.)."
        "- Важные обновления рекламных кабинетов, влияющие на работу прямо сейчас.\n\n"

        "❗️ ИНСТРУКЦИЯ ПО ПРИНЯТИЮ РЕШЕНИЯ:"
        "1. Если пост содержит полезную информацию, но в конце есть ссылка на канал источника — это всё равно 'полезно'."
        "2. Если пост — это просто ссылка или 'читайте продолжение в источнике' — это 'реклама'."
        "3. Если сомневаешься — выбирай 'бесполезно'. Нам нужен только топ-контент.\n\n"

        f"Текст для анализа:\n\"\"\"{clean_text}\"\"\"\n\n"
        "Выведи ТОЛЬКО ОДНО слово-вердикт из трех вариантов: реклама, бесполезно, полезно."
    )

    results = []
    total = len(fallback_providers)

    async def call_provider(provider, index):
        try:
            models = getattr(provider, "models", [])
            model = models[0] if models else "gpt-3.5-turbo"

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    g4f.ChatCompletion.create,
                    provider=provider,
                    model=model,
                    messages=[{"role": "user", "content": prompt}]
                ),
                timeout=30
            )
            result = (response or "").strip().lower()
            result = re.sub(r'[^а-яА-Я]', '', result)

            if not result:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ⚠️ {provider.__name__} пустой ответ")
                return None

            if result in ['реклама', 'бесполезно', 'полезно']:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ✅ {provider.__name__} ({model}): {result}")
                return result
            else:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ⚠️ {provider.__name__} странный ответ: '{result}'")
        except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ❌ {provider.__name__} ошибка: {str(e)[:100]}")
        return None

    tasks = [call_provider(p, i) for i, p in enumerate(fallback_providers)]
    raw_results = await asyncio.gather(*tasks)

    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    for result in raw_results:
        if result in summary:
            summary[result] += 1

    total_valid = sum(summary.values())

    if total_valid == 0:
        await client.send_message(CHANNEL_TRASH, "❌ Ни один GPT-провайдер не дал ответ. Повтор через 30 минут.")
        await asyncio.sleep(1800)
        return await check_with_gpt(text, client)

    await client.send_message(CHANNEL_TRASH, f"📊 Сводка: {summary}")

    if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]):
        return "полезно"
    else:
        return "мусор"

# === Обработка сообщений
async def handle_message(event, client):
    load_filter_words()

    # === Только каналы (не обрабатываем чаты и группы)
    if not event.is_channel or event.chat is None or not getattr(event.chat, 'broadcast', False):
        return

    if event.poll or event.voice or event.video_note:
        return

    message_text = event.message.text or ""
    if not message_text.strip():
        return

    if len(message_text) > 2000:
        await client.send_message(CHANNEL_TRASH, f"⚠️ Сообщение обрезано до 2000 символов (было {len(message_text)})")

    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(message_text, client)

    messages_to_forward = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_forward.append(msg)
    messages_to_forward.sort(key=lambda m: m.id)

    # === Определение источника
    original_channel_id = None
    source_url = None

    if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
        original_channel_id = event.message.fwd_from.from_id.channel_id
    elif getattr(event.chat, "id", None) in COPY_CHANNELS:
        original_channel_id = event.chat.id

    if original_channel_id in COPY_CHANNELS:
        source_url = COPY_CHANNELS[original_channel_id]

    is_copy = source_url is not None
    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    if is_copy:
        media_files = []
        full_text = ""

        for msg in messages_to_forward:
            if msg.media:
                media_files.append(msg.media)
            if msg.text:
                full_text += msg.text.strip() + "\n"

        if full_text.strip():
            full_text = full_text.strip() + f"\n\nИсточник: {source_url}"
        else:
            full_text = f"Источник: {source_url}"

        if media_files:
            try:
                await client.send_file(
                    target_channel,
                    file=media_files,
                    caption=full_text,
                    force_document=False
                )
            except Exception as e:
                print(f"[!] Ошибка отправки медиа: {e}")
        else:
            await client.send_message(target_channel, full_text)

        print(f"[OK] Копия с источника: {source_url}")
    else:
        await client.forward_messages(target_channel, messages=messages_to_forward, from_peer=event.chat_id)
        print("[OK] Репост обычным способом")

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
