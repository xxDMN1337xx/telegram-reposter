import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import Message, PeerChannel
from config import API_ID, API_HASH, SESSION_NAME

# === Каналы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === Провайдеры
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

filter_words = set()
morph = pymorphy2.MorphAnalyzer(lang='ru')

def load_filter_words():
    global filter_words
    if os.path.exists('filter_words.txt'):
        with open('filter_words.txt', 'r', encoding='utf-8') as f:
            filter_words = {morph.parse(line.strip().lower())[0].normal_form for line in f if line.strip()}

def normalize_text(text):
    return {morph.parse(word)[0].normal_form for word in text.lower().split()}

def sanitize_input(text):
    text = re.sub(r'https?://\S+', '[ссылка]', text)
    text = re.sub(r'[^\wа-яА-ЯёЁ.,:;!?%()\-–—\n ]+', '', text)
    return text.strip()[:2000]

def fix_markdown_links(text):
    return re.sub(r'\*\*(.+?)\*\s*\((https?://[^\s)]+)\)', r'[\1](\2)', text)

async def check_with_gpt(text, client):
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
    results = []
    total = len(fallback_providers)

    async def call(provider, index):
        for model in [None, "gpt-3.5"]:
            try:
                args = {"provider": provider, "messages": [{"role": "user", "content": prompt}]}
                if model:
                    args["model"] = model
                result = await asyncio.wait_for(
                    asyncio.to_thread(g4f.ChatCompletion.create, **args),
                    timeout=25
                )
                result = re.sub(r'[^а-яА-Я]', '', (result or "").strip().lower())
                if result in ['реклама', 'бесполезно', 'полезно']:
                    await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ✅ {provider.__name__}: {result}")
                    return result
                else:
                    await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ⚠️ {provider.__name__}: странный ответ: '{result}'")
                    return None
            except Exception as e:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ❌ {provider.__name__} ({'без model' if model is None else model}): ошибка: {str(e)[:100]}")
        return None

    raw_results = await asyncio.gather(*(call(p, i) for i, p in enumerate(fallback_providers)))
    stats = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    for r in raw_results:
        if r in stats: stats[r] += 1

    if sum(stats.values()) == 0:
        await client.send_message(CHANNEL_TRASH, "❌ Ни один провайдер не ответил. Повтор через 30 мин.")
        await asyncio.sleep(1800)
        return await check_with_gpt(text, client)

    await client.send_message(CHANNEL_TRASH, f"📊 Сводка: {stats}")
    return "полезно" if stats["полезно"] > stats["реклама"] + stats["бесполезно"] else "мусор"

async def handle_message(event, client):
    if not isinstance(event.message.to_id, PeerChannel):
        return

    load_filter_words()
    text = (event.message.text or "").strip()
    if not text: return
    normalized = normalize_text(text)
    if filter_words.intersection(normalized): return

    result = await check_with_gpt(text, client)
    messages = [event.message]

    if event.message.grouped_id:
        async for m in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if m.grouped_id == event.message.grouped_id and m.id != event.message.id:
                messages.append(m)
    messages.sort(key=lambda m: m.id)

    source_channel_id = None
    if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
        source_channel_id = event.message.fwd_from.from_id.channel_id
    else:
        source_channel_id = getattr(event.chat, "id", None)

    try:
        ent = await client.get_entity(source_channel_id)
        if getattr(ent, 'username', None):
            source_link = f"https://t.me/{ent.username}"
        else:
            source_link = f"{getattr(ent, 'title', 'Unknown')} {source_channel_id}"
    except:
        source_link = f"Unknown {source_channel_id}"

    full_text = ""
    media_files = []

    for msg in messages:
        if msg.text: full_text += msg.text.strip() + "\n"
        if msg.media: media_files.append(msg.media)

    full_text = fix_markdown_links(full_text.strip())
    full_text += f"\n\nИсточник: {source_link}"

    target = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH
    max_len = 1000 if media_files else 4000

    if len(full_text) <= max_len:
        if media_files:
            await client.send_file(target, media_files, caption=full_text, force_document=False, parse_mode="markdown")
        else:
            await client.send_message(target, full_text, parse_mode="markdown")
    else:
        if media_files:
            await client.send_file(target, media_files, caption=full_text[:1000], force_document=False, parse_mode="markdown")
            chunks = [full_text[i:i + 4000] for i in range(1000, len(full_text), 4000)]
            for c in chunks:
                await client.send_message(target, c, parse_mode="markdown")
        else:
            chunks = [full_text[i:i + 4000] for i in range(0, len(full_text), 4000)]
            for c in chunks:
                await client.send_message(target, c, parse_mode="markdown")

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        await handle_message(event, client)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
