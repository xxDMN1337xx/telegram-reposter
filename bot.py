import asyncio
import os
import re
import html
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import Message, PeerChannel
from config import API_ID, API_HASH, SESSION_NAME

# === Каналы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === GPT Провайдеры
fallback_providers = [
    # === g4f.Provider.AnyProvider,
    g4f.Provider.Blackbox,
    g4f.Provider.CohereForAI_C4AI_Command,
    g4f.Provider.Free2GPT,
    g4f.Provider.Qwen_Qwen_2_5,
    g4f.Provider.Qwen_Qwen_2_5_Max,
    g4f.Provider.Qwen_Qwen_2_72B,
    g4f.Provider.WeWordle,
    g4f.Provider.Yqcloud,
]
# === Экранирование HTML
def escape_html(text: str) -> str:
    return html.escape(text)

# === Очистка текста
def sanitize_input(text):
    text = re.sub(r'https?://\S+', '[ссылка]', text)
    text = re.sub(r'[^\wа-яА-ЯёЁ.,:;!?%()\-–—\n ]+', '', text)
    return text.strip()[:2000]

# === Проверка GPT
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

    if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]):
        return "полезно"
    else:
        return "мусор"

# === Обработка сообщений
async def handle_message(event, client):
    if not isinstance(event.message.to_id, PeerChannel):  # Пропуск чатов/диалогов
        return

    if event.poll or event.voice or event.video_note:
        return

    message_text = event.message.message or ""
    if not message_text.strip():
        return

    result = await check_with_gpt(message_text, client)
    messages_to_forward = [event.message]

    # === Обработка альбомов (группировка)
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_forward.append(msg)
    messages_to_forward.sort(key=lambda m: m.id)

    # === Определяем источник
    source_channel = None
    if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
        channel_id = event.message.fwd_from.from_id.channel_id
        try:
            src_entity = await client.get_entity(PeerChannel(channel_id))
            if hasattr(src_entity, 'username') and src_entity.username:
                source_channel = f"https://t.me/{src_entity.username}"
            else:
                source_channel = f"Источник: {escape_html(src_entity.title)} ({channel_id})"
        except:
            source_channel = f"Источник: Channel {channel_id}"
    else:
        try:
            src_entity = await event.get_chat()
            if hasattr(src_entity, 'username') and src_entity.username:
                source_channel = f"https://t.me/{src_entity.username}"
            else:
                source_channel = f"Источник: {escape_html(src_entity.title)} ({src_entity.id})"
        except:
            source_channel = "Источник: неизвестен"

    full_text = ""
    media_files = []
    for msg in messages_to_forward:
        if msg.media:
            media_files.append(msg.media)
        if msg.message:
            full_text += msg.message + "\n"

    full_text = full_text.strip()
    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    # === Отправка
    if media_files:
        caption = escape_html(full_text[:1000])
        try:
            await client.send_file(
                target_channel,
                file=media_files,
                caption=caption,
                force_document=False,
                parse_mode="html"
            )
        except Exception as e:
            print(f"[!] Ошибка отправки медиа: {e}")
        remaining_text = full_text[1000:]
        if remaining_text:
            chunks = [escape_html(remaining_text[i:i + 4000]) for i in range(0, len(remaining_text), 4000)]
            for chunk in chunks[:-1]:
                await client.send_message(target_channel, chunk, parse_mode="html")
            await client.send_message(target_channel, chunks[-1] + f"\n\n<i>{source_channel}</i>", parse_mode="html")
        else:
            await client.send_message(target_channel, f"<i>{source_channel}</i>", parse_mode="html")
    else:
        chunks = [escape_html(full_text[i:i + 4000]) for i in range(0, len(full_text), 4000)]
        for chunk in chunks[:-1]:
            await client.send_message(target_channel, chunk, parse_mode="html")
        await client.send_message(target_channel, chunks[-1] + f"\n\n<i>{source_channel}</i>", parse_mode="html")

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
