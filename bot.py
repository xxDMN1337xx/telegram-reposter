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

# === Фильтрация
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

# === HTML-конвертация
def entities_to_html(text, entities):
    if not entities:
        return escape(text or "")

    entities = sorted(entities, key=lambda e: e.offset)
    result = []
    last = 0

    for e in entities:
        result.append(escape(text[last:e.offset]))
        content = escape(text[e.offset:e.offset + e.length])

        if isinstance(e, MessageEntityBold):
            result.append(f"<b>{content}</b>")
        elif isinstance(e, MessageEntityItalic):
            result.append(f"<i>{content}</i>")
        elif isinstance(e, MessageEntityUnderline):
            result.append(f"<u>{content}</u>")
        elif isinstance(e, MessageEntityStrike):
            result.append(f"<s>{content}</s>")
        elif isinstance(e, MessageEntityCode):
            result.append(f"<code>{content}</code>")
        elif isinstance(e, MessageEntityPre):
            result.append(f"<pre>{content}</pre>")
        elif isinstance(e, MessageEntityTextUrl):
            result.append(f'<a href="{escape(e.url)}">{content}</a>')
        elif isinstance(e, MessageEntityUrl):
            result.append(f'<a href="{content}">{content}</a>')
        elif isinstance(e, MessageEntityMentionName):
            result.append(f'<a href="tg://user?id={e.user_id}">{content}</a>')
        elif isinstance(e, MessageEntitySpoiler):
            result.append(f'<tg-spoiler>{content}</tg-spoiler>')
        elif isinstance(e, MessageEntityBlockquote):
            result.append(f'<blockquote>{content}</blockquote>')
        else:
            result.append(content)

        last = e.offset + e.length

    result.append(escape(text[last:]))
    return ''.join(result)

# === GPT-фильтрация
async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("\n", " "))
    prompt = (
        "Ты ассистент, помогающий отбирать посты для Telegram-канала по арбитражу трафика.\n\n"
        "Тебе НЕЛЬЗЯ допускать к публикации:\n"
        "- личные посты\n- общая реклама\n- бесполезные тексты\n- интервью\n"
        "- розыгрыши\n- вечеринки, конференции\n- лонгриды без конкретики\n\n"
        "Публиковать можно только:\n"
        "- кейсы, схемы, инсайты, цифры\n- связки, источники трафика\n"
        "- инструменты, API, скрипты\n- обзоры ИИ-инструментов\n- новости платформ\n\n"
        f"Анализируй текст поста:\n\"{clean_text}\"\n\n"
        "Ответь одним словом: реклама, бесполезно, полезно."
    )

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
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ⚠️ {provider.__name__}: '{result}'")
        except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ❌ {provider.__name__} ошибка: {str(e)[:100]}")
        return None

    raw_results = await asyncio.gather(*[call_provider(p, i) for i, p in enumerate(fallback_providers)])
    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    for r in raw_results:
        if r in summary:
            summary[r] += 1

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
    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    # Группировка
    messages_to_forward = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_forward.append(msg)
    messages_to_forward.sort(key=lambda m: m.id)

    # Источник
    source = ""
    try:
        fwd = event.message.fwd_from
        if fwd and isinstance(fwd.from_id, PeerChannel):
            entity = await client.get_entity(fwd.from_id)
        else:
            entity = await client.get_entity(event.chat_id)
        source = f"Источник: https://t.me/{entity.username}" if entity.username else f"Источник: {entity.title} {entity.id}"
    except:
        source = f"Источник: канал {event.chat_id}"

    # === Основной текст + media
    media = [msg.media for msg in messages_to_forward if msg.media]
    main_msg = messages_to_forward[0]
    main_text = entities_to_html(main_msg.message or "", main_msg.entities or [])
    full_text = main_text.strip() + f"\n\n{escape(source)}"
    max_len = 1000 if media else 4000
    chunks = [full_text[i:i+max_len] for i in range(0, len(full_text), max_len)]

    if media:
        try:
            await client.send_file(target_channel, file=media, caption=chunks[0], force_document=False, parse_mode='html')
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
