import asyncio
import os
import re
import pymorphy2
import g4f
from html import escape as escape_html
from telethon import TelegramClient, events
from telethon.tl.types import Message, PeerChannel, MessageEntityPre, MessageEntityCode, MessageEntityTextUrl, MessageEntityMentionName, MessageEntityBlockquote
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

# === HTML восстановление форматирования

def message_to_html(message: Message) -> str:
    if not message.text:
        return ""

    raw = message.text
    entities = message.entities or []
    text = list(escape_html(raw))

    def insert_tags(start, end, open_tag, close_tag):
        text[start:end] = list(open_tag + ''.join(text[start:end]) + close_tag)

    for entity in sorted(entities, key=lambda e: e.offset + e.length, reverse=True):
        start = entity.offset
        end = start + entity.length

        if isinstance(entity, MessageEntityPre):
            insert_tags(start, end, '<pre>', '</pre>')
        elif isinstance(entity, MessageEntityCode):
            insert_tags(start, end, '<code>', '</code>')
        elif entity.__class__.__name__ == "MessageEntityBold":
            insert_tags(start, end, '<b>', '</b>')
        elif entity.__class__.__name__ == "MessageEntityItalic":
            insert_tags(start, end, '<i>', '</i>')
        elif entity.__class__.__name__ == "MessageEntityUnderline":
            insert_tags(start, end, '<u>', '</u>')
        elif entity.__class__.__name__ == "MessageEntityStrike":
            insert_tags(start, end, '<s>', '</s>')
        elif entity.__class__.__name__ == "MessageEntitySpoiler":
            insert_tags(start, end, '<span class="tg-spoiler">', '</span>')
        elif entity.__class__.__name__ == "MessageEntityBlockquote":
            insert_tags(start, end, '<blockquote>', '</blockquote>')
        elif isinstance(entity, MessageEntityTextUrl):
            insert_tags(start, end, f'<a href="{escape_html(entity.url)}">', '</a>')
        elif isinstance(entity, MessageEntityMentionName):
            insert_tags(start, end, f'<a href="tg://user?id={entity.user_id}">', '</a>')

    return ''.join(text)

# === GPT фильтрация
async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("\n", " "))
    prompt = f"..."  # тот же как в оригинале, опущен для краткости
    ...  # остальной код фильтрации без изменений

# === Обработка сообщений
async def handle_message(event, client):
    load_filter_words()
    if not isinstance(event.message.to_id, PeerChannel): return
    if event.poll or event.voice or event.video_note: return
    message_text = event.message.text or ""
    if not message_text.strip(): return

    if len(message_text) > 2000:
        await client.send_message(CHANNEL_TRASH, f"⚠️ Сообщение обрезано до 2000 символов (было {len(message_text)})")

    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized): return

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
        text_buffer += message_to_html(msg).strip() + "\n"
        if msg.media:
            media.append(msg.media)

    text_buffer = text_buffer.strip()
    max_text_len = 1000 if media else 4000
    chunks = [text_buffer[i:i+max_text_len] for i in range(0, len(text_buffer), max_text_len)]
    if chunks:
        chunks[-1] += f"\n\n{source}"

    if media:
        try:
            await client.send_file(target_channel, file=media, caption=chunks[0], parse_mode='html', force_document=False)
            for part in chunks[1:]:
                await client.send_message(target_channel, part, parse_mode='html')
        except Exception as e:
            print(f"[!] Ошибка отправки медиа: {e}")
    else:
        for part in chunks:
            await client.send_message(target_channel, part, parse_mode='html')

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
