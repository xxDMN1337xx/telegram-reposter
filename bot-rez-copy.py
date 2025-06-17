import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import Message, PeerChannel
# PeerUser не используется, его можно убрать
# from telethon.tl.types import PeerUser 
from config import API_ID, API_HASH, SESSION_NAME

# === Каналы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === Провайдеры
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

# === Очистка текста для GPT
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

# === GPT фильтрация
async def check_with_gpt(text: str, client) -> str:
    # Для анализа GPT используем чистый текст, без разметки
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
    return "полезно" if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]) else "мусор"

# === Обработка сообщений (ВЕРСИЯ С ИСПРАВЛЕНИЯМИ)
async def handle_message(event, client):
    load_filter_words()

    if not isinstance(event.message.to_id, PeerChannel):
        return

    if event.poll or event.voice or event.video_note:
        return

    # Для анализа GPT по-прежнему используем чистый текст .text
    message_text = event.message.text or ""
    # Продолжаем, даже если текста нет, но есть медиа
    if not message_text.strip() and not event.message.media:
        return

    if len(message_text) > 2000:
        await client.send_message(CHANNEL_TRASH, f"⚠️ Сообщение обрезано до 2000 символов (было {len(message_text)})")

    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(message_text, client)

    messages_to_forward = []
    if event.message.grouped_id:
        # Улучшенный сбор сгруппированных сообщений
        group = await client.get_messages(event.chat_id, ids=event.message.grouped_id)
        if group:
            messages_to_forward = sorted([msg for msg in group if msg], key=lambda m: m.id)
    else:
        messages_to_forward.append(event.message)

    source = ""
    if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
        try:
            entity = await client.get_entity(PeerChannel(event.message.fwd_from.from_id.channel_id))
            source = f"Источник: [{entity.title}](https://t.me/{entity.username})" if entity.username else f"Источник: {entity.title}"
        except:
            source = f"Источник: канал {event.message.fwd_from.from_id.channel_id}"
    else:
        try:
            entity = await client.get_entity(event.chat_id)
            source = f"Источник: [{entity.title}](https://t.me/{entity.username})" if entity.username else f"Источник: {entity.title}"
        except:
            source = f"Источник: канал {event.chat_id}"

    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    # --- КЛЮЧЕВЫЕ ИЗМЕНЕНИЯ ЗДЕСЬ ---

    text_buffer = ""
    media_messages = []

    for msg in messages_to_forward:
        # 1. Используем .md_text для получения текста с Markdown разметкой
        if msg.md_text:
            text_buffer += msg.md_text.strip() + "\n\n"
        if msg.media:
            media_messages.append(msg) # Собираем сообщения с медиа целиком

    # Добавляем источник в конец общего текста. Источник оформлен как Markdown-ссылка.
    full_text_with_source = text_buffer.strip() + f"\n\n{source}"

    # Лимиты Telegram
    MAX_CAPTION_LEN = 1024
    MAX_MESSAGE_LEN = 4096

    if media_messages:
        # Текст для подписи к медиа (не более 1024 символов)
        caption = full_text_with_source[:MAX_CAPTION_LEN]
        # Оставшийся текст, который не влез в подпись
        remaining_text = full_text_with_source[MAX_CAPTION_LEN:]

        try:
            # 2. Отправляем медиа с подписью, указывая parse_mode='md'
            await client.send_file(
                target_channel,
                file=media_messages,
                caption=caption,
                parse_mode='md'
            )
            # Если остался текст, отправляем его отдельными сообщениями
            if remaining_text:
                for i in range(0, len(remaining_text), MAX_MESSAGE_LEN):
                    part = remaining_text[i:i+MAX_MESSAGE_LEN]
                    await client.send_message(target_channel, part, parse_mode='md')
        except Exception as e:
            print(f"[!] Ошибка отправки медиа с форматированием: {e}")
            # Запасной вариант: отправить без форматирования
            await client.send_file(target_channel, file=media_messages, caption=(event.message.text or "")[:MAX_CAPTION_LEN])

    elif full_text_with_source.strip():
        # Если медиа нет, просто отправляем текст по частям
        for i in range(0, len(full_text_with_source), MAX_MESSAGE_LEN):
            part = full_text_with_source[i:i+MAX_MESSAGE_LEN]
            # 3. Отправляем текст, указывая parse_mode='md'
            await client.send_message(target_channel, part, parse_mode='md')

    print(f"[OK] Копия с источника: {source.split('](')[0][10:]} -> {target_channel}")


# === Запуск клиента
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    print("Клиент запускается...")
    await client.start()
    print("Клиент запущен и слушает новые сообщения.")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            await handle_message(event, client)
        except Exception as e:
            # Логируем ошибки, чтобы скрипт не падал молча
            print(f"[!!!] Критическая ошибка в обработчике: {e}")
            # Можно отправлять уведомление об ошибке в личные сообщения или специальный канал
            # await client.send_message('me', f'Ошибка в боте: {e}')


    await client.run_until_disconnected()
    print("Клиент остановлен.")

if __name__ == "__main__":
    # Загружаем стоп-слова один раз при старте
    load_filter_words()
    # Запускаем основной цикл
    asyncio.run(main())
