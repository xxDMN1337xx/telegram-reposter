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

# === HTML форматирование
def entities_to_html(text, entities):
    if not text:
        return ""
    if not entities:
        return escape(text)

    result = []
    current_pos = 0
    tag_map = {
        MessageEntityBold: "b",
        MessageEntityItalic: "i",
        MessageEntityUnderline: "u",
        MessageEntityStrike: "s",
        MessageEntityCode: "code",
        MessageEntityPre: "pre",
        MessageEntitySpoiler: "tg-spoiler",
        MessageEntityBlockquote: "blockquote",
    }

    entities = sorted(entities, key=lambda e: e.offset)

    for entity in entities:
        start = entity.offset
        end = start + entity.length

        # текст до entity
        if current_pos < start:
            result.append(escape(text[current_pos:start]))

        segment = escape(text[start:end])

        if isinstance(entity, MessageEntityTextUrl):
            result.append(f'<a href="{escape(entity.url)}">{segment}</a>')
        elif isinstance(entity, MessageEntityUrl):
            result.append(f'<a href="{segment}">{segment}</a>')
        elif isinstance(entity, MessageEntityMentionName):
            result.append(f'<a href="tg://user?id={entity.user_id}">{segment}</a>')
        else:
            tag = tag_map.get(type(entity))
            if tag:
                result.append(f"<{tag}>{segment}</{tag}>")
            else:
                result.append(segment)

        current_pos = end

    # остаток текста
    if current_pos < len(text):
        result.append(escape(text[current_pos:]))

    return ''.join(result)

# === Текстовая фильтрация
def sanitize_input(text):
    text = re.sub(r'https?://\S+', '[ссылка]', text)
    text = re.sub(r'[^\wа-яА-ЯёЁ.,:;!?%()\-–—\n ]+', '', text)
    return text.strip()[:2000]

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

# === GPT-фильтрация
async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("\n", " "))
    prompt = (
        "Ты ассистент, помогающий отбирать посты для Telegram-канала по арбитражу трафика.\n\n"
        "Запрещено публиковать:\n- личные посты\n- бесполезные тексты\n- общие рассуждения\n"
        "- конкурсы, тусовки, философия, лонгриды\n\n"
        "Разрешено публиковать:\n- кейсы, связки, инструменты\n"
        "- скрипты, цифры, API, инсайты\n\n"
        f"Анализируй текст:\n\"{clean_text}\"\n\n"
        "Ответь одним словом: реклама, бесполезно, полезно."
    )

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
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{len(fallback_providers)} ✅ {provider.__name__}: {result}")
                return result
            else:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{len(fallback_providers)} ⚠️ {provider.__name__}: '{result}'")
        except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"{index+1}/{len(fallback_providers)} ❌ {provider.__name__} ошибка: {str(e)[:100]}")
        return None

    results = await asyncio.gather(*[call_provider(p, i) for i, p in enumerate(fallback_providers)])
    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    for r in results:
        if r in summary:
            summary[r] += 1

    if sum(summary.values()) == 0:
        await client.send_message(CHANNEL_TRASH, "❌ Ни один GPT-провайдер не дал ответ. Повтор через 30 мин.")
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

    if not (event.message.message or "").strip():
        return

    normalized = normalize_text(event.message.message)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(event.message.message, client)
    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    # === Группировка
    messages = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages.append(msg)
    messages.sort(key=lambda m: m.id)

    # === Источник
    try:
        fwd = event.message.fwd_from
        if fwd and isinstance(fwd.from_id, PeerChannel):
            entity = await client.get_entity(fwd.from_id)
        else:
            entity = await client.get_entity(event.chat_id)
        source = f"Источник: https://t.me/{entity.username}" if entity.username else f"Источник: {entity.title} {entity.id}"
    except:
        source = f"Источник: канал {event.chat_id}"

    media = [msg.media for msg in messages if msg.media]
    main = messages[0]
    html = entities_to_html(main.message or "", main.entities or [])
    html += f"\n\n{escape(source)}"

    max_len = 1000 if media else 4000
    chunks = [html[i:i+max_len] for i in range(0, len(html), max_len)]

    if media:
        try:
            await client.send_file(target_channel, file=media, caption=chunks[0], parse_mode='html', force_document=False)
            for chunk in chunks[1:]:
                await client.send_message(target_channel, chunk, parse_mode='html')
        except Exception as e:
            print(f"[!] Ошибка отправки медиа: {e}")
    else:
        for chunk in chunks:
            await client.send_message(target_channel, chunk, parse_mode='html')

    print(f"[OK] Копия с источника: {source}")

# === Запуск
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        await handle_message(event, client)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
