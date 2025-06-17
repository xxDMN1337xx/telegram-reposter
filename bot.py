import asyncio
import os
import re
import pymorphy2
import g4f
from html import escape
from telethon import TelegramClient, events
from telethon.tl.types import *
from config import API_ID, API_HASH, SESSION_NAME

# === Каналы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === Провайдеры
fallback_providers = [
    g4f.Provider.Blackbox,
    g4f.Provider.CohereForAI_C4AI_Command,
    g4f.Provider.Free2GPT,
    g4f.Provider.Qwen_Qwen_2_5,
    g4f.Provider.Qwen_Qwen_2_5_Max,
    g4f.Provider.Qwen_Qwen_2_72B,
    g4f.Provider.WeWordle,
    g4f.Provider.Yqcloud,
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

# === HTML форматирование из entities

def entities_to_html(text, entities):
    if not entities:
        return escape(text)

    offsets = []
    for ent in entities:
        start, end = ent.offset, ent.offset + ent.length
        tag_open, tag_close = '', ''

        if isinstance(ent, MessageEntityBold):
            tag_open, tag_close = '<b>', '</b>'
        elif isinstance(ent, MessageEntityItalic):
            tag_open, tag_close = '<i>', '</i>'
        elif isinstance(ent, MessageEntityUnderline):
            tag_open, tag_close = '<u>', '</u>'
        elif isinstance(ent, MessageEntityStrike):
            tag_open, tag_close = '<s>', '</s>'
        elif isinstance(ent, MessageEntityCode):
            tag_open, tag_close = '<code>', '</code>'
        elif isinstance(ent, MessageEntityPre):
            tag_open, tag_close = '<pre>', '</pre>'
        elif isinstance(ent, MessageEntityTextUrl):
            tag_open, tag_close = f'<a href="{escape(ent.url)}">', '</a>'
        elif isinstance(ent, MessageEntityUrl):
            url = escape(text[start:end])
            tag_open, tag_close = f'<a href="{url}">', '</a>'
        elif isinstance(ent, MessageEntityMentionName):
            tag_open, tag_close = f'<a href="tg://user?id={ent.user_id}">', '</a>'
        elif isinstance(ent, MessageEntitySpoiler):
            tag_open, tag_close = '<tg-spoiler>', '</tg-spoiler>'
        elif isinstance(ent, MessageEntityBlockquote):
            tag_open, tag_close = '<blockquote>', '</blockquote>'

        offsets.append((start, tag_open))
        offsets.append((end, tag_close))

    offsets.sort(key=lambda x: x[0], reverse=True)
    text = escape(text)
    for pos, tag in offsets:
        text = text[:pos] + tag + text[pos:]

    return text

# === GPT фильтрация
async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("\n", " "))

    prompt = (
        "Ты ассистент, помогающий отбирать посты для Telegram-канала по арбитражу трафика.\n\n"
        "Тебе НЕЛЬЗЯ допускать к публикации следующие типы постов:\n"
        "- личные посты...\n\n"
        f"Анализируй текст поста:\n\"{clean_text}\"\n\n"
        "Ответь **одним словом**, выбери только из: реклама, бесполезно, полезно."
    )

    results = []
    total = len(fallback_providers)

    async def call_provider(provider, index):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    g4f.ChatCompletion.create,
                    provider=provider,
                    model=g4f.models.default,
                    messages=[{"role": "user", "content": prompt}]
                ),
                timeout=30
            )
            result = (response or "").strip().lower()
            result = re.sub(r'[^а-яА-Я]', '', result)
            if result in ['реклама', 'бесполезно', 'полезно']:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ✅ {provider.__name__}: {result}")
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
    return "полезно" if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]) else "мусор"

# === Обработка сообщений
async def handle_message(event, client):
    load_filter_words()

    if not isinstance(event.message.to_id, PeerChannel):
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

    try:
        entity = await client.get_entity(event.chat_id)
        source = f"Источник: https://t.me/{entity.username}" if entity.username else f"Источник: {entity.title} {entity.id}"
    except:
        source = f"Источник: канал {event.chat_id}"

    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    text_buffer = ""
    media = []

    for msg in messages_to_forward:
        if msg.text:
            text_buffer += entities_to_html(msg.text, msg.entities) + "\n"
        if msg.media:
            media.append(msg.media)

    text_buffer = text_buffer.strip()
    max_text_len = 1000 if media else 3000

    chunks = [text_buffer[i:i+max_text_len] for i in range(0, len(text_buffer), max_text_len)]
    if chunks:
        chunks[-1] += f"\n\n{escape(source)}"

    if media:
        try:
            await client.send_file(target_channel, file=media, caption=chunks[0], force_document=False, parse_mode='html')
            for part in chunks[1:]:
                await client.send_message(target_channel, part, parse_mode='html')
        except Exception as e:
            print(f"[!] Ошибка отправки медиа: {e}")
    else:
        for part in chunks:
            await client.send_message(target_channel, part, parse_mode='html')

    print(f"[OK] Копия с источника: {source}")

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
