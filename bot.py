import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import (
    PeerChannel, MessageEntityBold, MessageEntityItalic,
    MessageEntityUnderline, MessageEntityStrike, MessageEntitySpoiler,
    MessageEntityCode, MessageEntityPre, MessageEntityTextUrl,
    MessageEntityMentionName, MessageEntityUrl
)
from config import API_ID, API_HASH, SESSION_NAME

CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

fallback_providers = [
    g4f.Provider.AnyProvider,
    g4f.Provider.Blackbox,
    g4f.Provider.Chatai,
    g4f.Provider.CohereForAI_C4AI_Command,
    g4f.Provider.Copilot,
    g4f.Provider.CopilotAccount,
    g4f.Provider.Free2GPT,
    g4f.Provider.Qwen_Qwen_2_5,
    g4f.Provider.Qwen_Qwen_2_5_Max,
    g4f.Provider.Qwen_Qwen_2_72B,
    g4f.Provider.TeachAnything,
    g4f.Provider.WeWordle,
    g4f.Provider.Yqcloud,
]

morph = pymorphy2.MorphAnalyzer(lang='ru')
filter_words = set()

def escape_md(text):
    return re.sub(r'([_*\[\]()~`>#+=|{}.!-])', r'\\\1', text)

def format_entities(text, entities):
    if not entities:
        return escape_md(text)
    result = list(escape_md(text))
    added = 0
    for e in sorted(entities, key=lambda x: x.offset):
        start = e.offset + added
        end = start + e.length

        wrap = ''
        if isinstance(e, MessageEntityBold):
            wrap = ('*', '*')
        elif isinstance(e, MessageEntityItalic):
            wrap = ('_', '_')
        elif isinstance(e, MessageEntityUnderline):
            wrap = ('__', '__')
        elif isinstance(e, MessageEntityStrike):
            wrap = ('~', '~')
        elif isinstance(e, MessageEntitySpoiler):
            wrap = ('||', '||')
        elif isinstance(e, MessageEntityCode):
            wrap = ('`', '`')
        elif isinstance(e, MessageEntityPre):
            wrap = ('```', '```')
        elif isinstance(e, MessageEntityTextUrl):
            wrap = (f"[", f"]({escape_md(e.url)})")
        elif isinstance(e, MessageEntityMentionName):
            wrap = (f"[", f"](tg://user?id={e.user_id})")
        elif isinstance(e, MessageEntityUrl):
            continue  # уже встроено
        else:
            continue

        result.insert(start, wrap[0])
        result.insert(end + 1, wrap[1])
        added += len(wrap[0]) + len(wrap[1])
    return ''.join(result)

def sanitize_input(text):
    text = re.sub(r'https?://\S+', '[ссылка]', text)
    text = re.sub(r'[^\wа-яА-ЯёЁ.,:;!?%()\-–—\n ]+', '', text)
    return text.strip()[:2000]

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
        "- обзоры или новости об ИИ-инструментах (SkyReels, Scira, Sora, ChatGPT, MidJourney, Runway и т.д.)\n"
        "- новости по платформам, трекерам, банам, обновлениям, платёжкам и т.д.\n\n"
        "Если в тексте нет конкретной пользы — считай его бесполезным.\n"
        "Не будь мягким. Отсеивай всё, что не даст выгоды арбитражнику.\n\n"
        f"Анализируй текст поста:\n\"{clean_text}\"\n\n"
        "Ответь **одним словом**, выбери только из: реклама, бесполезно, полезно."
    )

    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
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
            if result in summary:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ✅ {provider.__name__}: {result}")
                return result
            await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ⚠️ {provider.__name__} странный ответ: {result}")
        except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ❌ {provider.__name__} ошибка: {str(e)[:100]}")
        return None

    results = await asyncio.gather(*[call_provider(p, i) for i, p in enumerate(fallback_providers)])
    for r in results:
        if r in summary:
            summary[r] += 1

    total_valid = sum(summary.values())
    if total_valid == 0:
        await client.send_message(CHANNEL_TRASH, "❌ Ни один GPT-провайдер не дал ответ. Повтор через 30 минут.")
        await asyncio.sleep(1800)
        return await check_with_gpt(text, client)

    await client.send_message(CHANNEL_TRASH, f"📊 Сводка: {summary}")
    return "полезно" if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]) else "мусор"

async def handle_message(event, client):
    load_filter_words()

    if not isinstance(event.message.to_id, PeerChannel):
        return
    if event.poll or event.voice or event.video_note:
        return

    message_text = event.message.text or ""
    if not message_text.strip():
        return

    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(message_text, client)

    messages = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages.append(msg)
    messages.sort(key=lambda m: m.id)

    # === Источник
    if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
        try:
            entity = await client.get_entity(PeerChannel(event.message.fwd_from.from_id.channel_id))
            source = f"Источник: https://t.me/{entity.username}" if entity.username else f"Источник: {entity.title} {entity.id}"
        except:
            source = f"Источник: канал {event.message.fwd_from.from_id.channel_id}"
    else:
        try:
            entity = await client.get_entity(event.chat_id)
            source = f"Источник: https://t.me/{entity.username}" if entity.username else f"Источник: {entity.title} {entity.id}"
        except:
            source = f"Источник: канал {event.chat_id}"

    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    text = ""
    media = []

    for msg in messages:
        if msg.message:
            text += format_entities(msg.message, msg.entities).strip() + "\n"
        if msg.media:
            media.append(msg.media)

    text = text.strip()
    max_len = 1000 if media else 4000
    chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)]
    if chunks:
        chunks[-1] += f"\n\n{escape_md(source)}"

    try:
        if media:
            await client.send_file(target_channel, file=media, caption=chunks[0], force_document=False, parse_mode='MarkdownV2')
            for part in chunks[1:]:
                await client.send_message(target_channel, part, parse_mode='MarkdownV2')
        else:
            for part in chunks:
                await client.send_message(target_channel, part, parse_mode='MarkdownV2')
    except Exception as e:
        print(f"[!] Ошибка при отправке: {e}")

    print(f"[OK] Копия с источника: {source}")

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        await handle_message(event, client)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
