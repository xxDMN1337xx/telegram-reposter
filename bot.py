import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import Message, PeerChannel, PeerUser
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

# === HTML форматирование
def escape_html(text):
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

def format_message_to_html(message):
    if not message.entities:
        return escape_html(message.text)

    entities = sorted(message.entities, key=lambda e: e.offset)
    text = message.text
    result = ""
    last_offset = 0

    for entity in entities:
        result += escape_html(text[last_offset:entity.offset])
        segment = escape_html(text[entity.offset:entity.offset + entity.length])

        tag_open, tag_close = '', ''
        etype = type(entity).__name__
        if etype == 'MessageEntityBold': tag_open, tag_close = '<b>', '</b>'
        elif etype == 'MessageEntityItalic': tag_open, tag_close = '<i>', '</i>'
        elif etype == 'MessageEntityUnderline': tag_open, tag_close = '<u>', '</u>'
        elif etype == 'MessageEntityStrike': tag_open, tag_close = '<s>', '</s>'
        elif etype == 'MessageEntitySpoiler': tag_open, tag_close = '<span class="tg-spoiler">', '</span>'
        elif etype == 'MessageEntityUrl': tag_open, tag_close = f'<a href="{segment}">', '</a>'
        elif etype == 'MessageEntityTextUrl': tag_open, tag_close = f'<a href="{entity.url}">', '</a>'
        elif etype == 'MessageEntityMentionName': tag_open, tag_close = f'<a href="tg://user?id={entity.user_id}">', '</a>'
        elif etype == 'MessageEntityCode': tag_open, tag_close = '<code>', '</code>'
        elif etype == 'MessageEntityPre': tag_open, tag_close = '<pre>', '</pre>'
        elif etype == 'MessageEntityQuote': tag_open, tag_close = '<blockquote>', '</blockquote>'

        result += f'{tag_open}{segment}{tag_close}'
        last_offset = entity.offset + entity.length

    result += escape_html(text[last_offset:])
    return result

# === Умное разбиение HTML текста
def smart_split_html(html, max_len):
    blocks = re.split(r'(</?(?:b|i|u|s|code|pre|a|span|blockquote)[^>]*>)', html)
    result = []
    buffer = ''

    for block in blocks:
        if len(buffer) + len(block) <= max_len:
            buffer += block
        else:
            if buffer:
                result.append(buffer.strip())
            buffer = block

    if buffer:
        result.append(buffer.strip())
    return result

# === GPT фильтрация
async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("\n", " "))

    prompt = (
        "Ты ассистент, помогающий отбирать посты для Telegram-канала по арбитражу трафика.\n\n"
        "[...]\n\n"  # Сократил для читаемости (оставь оригинальный промпт у себя)
        f"Анализируй текст поста:\n\"{clean_text}\"\n\n"
        "Ответь **одним словом**, выбери только из: реклама, бесполезно, полезно."
    )

    tasks = []
    for i, provider in enumerate(fallback_providers):
        async def call(provider=provider, i=i):
            try:
                response = await asyncio.wait_for(asyncio.to_thread(g4f.ChatCompletion.create,
                    provider=provider, model=g4f.models.default,
                    messages=[{"role": "user", "content": prompt}]), timeout=30)
                result = (response or '').strip().lower()
                result = re.sub(r'[^а-яА-Я]', '', result)
                if result in ['реклама', 'бесполезно', 'полезно']:
                    await client.send_message(CHANNEL_TRASH, f"{i+1}/{len(fallback_providers)} ✅ {provider.__name__}: {result}")
                    return result
                await client.send_message(CHANNEL_TRASH, f"{i+1}/{len(fallback_providers)} ⚠️ {provider.__name__}: '{result}'")
            except Exception as e:
                await client.send_message(CHANNEL_TRASH, f"{i+1}/{len(fallback_providers)} ❌ {provider.__name__}: {str(e)[:100]}")
            return None
        tasks.append(call())

    raw_results = await asyncio.gather(*tasks)
    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    for r in raw_results:
        if r in summary:
            summary[r] += 1

    await client.send_message(CHANNEL_TRASH, f"📊 Сводка: {summary}")
    if summary['полезно'] > summary['реклама'] + summary['бесполезно']:
        return 'полезно'
    return 'мусор'

# === Обработка сообщений
async def handle_message(event, client):
    load_filter_words()
    if not isinstance(event.message.to_id, PeerChannel): return
    if event.poll or event.voice or event.video_note: return
    if not (event.message.text and event.message.text.strip()): return

    if len(event.message.text) > 2000:
        await client.send_message(CHANNEL_TRASH, f"⚠️ Сообщение обрезано до 2000 символов (было {len(event.message.text)})")

    if filter_words.intersection(normalize_text(event.message.text)):
        return

    result = await check_with_gpt(event.message.text, client)

    messages_to_forward = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_forward.append(msg)
    messages_to_forward.sort(key=lambda m: m.id)

    source = ""
    try:
        entity = await client.get_entity(event.chat_id)
        source = f"Источник: https://t.me/{entity.username}" if entity.username else f"Источник: {entity.title} {entity.id}"
    except:
        source = f"Источник: канал {event.chat_id}"

    target_channel = CHANNEL_GOOD if result == 'полезно' else CHANNEL_TRASH

    html_buffer = ""
    media = []
    for msg in messages_to_forward:
        if msg.text:
            html_buffer += format_message_to_html(msg).strip() + "\n"
        if msg.media:
            media.append(msg.media)

    html_buffer = html_buffer.strip()
    max_text_len = 1000 if media else 4000
    chunks = smart_split_html(html_buffer, max_text_len)
    if chunks:
        chunks[-1] += f"\n\n{escape_html(source)}"

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
