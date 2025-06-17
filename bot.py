import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import Message, PeerChannel
from config import API_ID, API_HASH, SESSION_NAME

# === Каналы
CHANNEL_GOOD = 'https.t.me/fbeed1337'
CHANNEL_TRASH = 'https.t.me/musoradsxx'
# Максимальная длина сообщений в Telegram
TEXT_MAX_LEN = 4096
CAPTION_MAX_LEN = 1024

# === Провайдеры (обновленный список)
fallback_providers = [
    g4f.Provider.AnyProvider,
    g4f.Provider.Blackbox,
    g4f.Provider.Chatai,
    g4f.Provider.CohereForAI_C4AI_Command,
    g4f.Provider.Copilot,
    # g4f.Provider.CopilotAccount, # Часто требует аутентификации, может вызывать ошибки
    g4f.Provider.Free2GPT,
    g4f.Provider.Qwen_Qwen_2_5,
    g4f.Provider.Qwen_Qwen_2_5_Max,
    g4f.Provider.Qwen_Qwen_2_72B,
    g4f.Provider.TeachAnything,
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

    total = len(fallback_providers)

    async def call_provider(provider, index):
        try:
            # Пытаемся получить список моделей, если его нет - используем дефолтное значение
            model_name = getattr(provider, "model", "gpt-3.5-turbo")
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    g4f.ChatCompletion.create,
                    provider=provider,
                    model=model_name,
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


# === Новая функция для получения информации об источнике
async def get_source_info(event) -> str:
    """Определяет источник сообщения (оригинал или канал, где оно появилось)."""
    source_entity = None
    # Приоритет - оригинальный канал, если это форвард
    if event.message.fwd_from and isinstance(event.message.fwd_from.from_id, PeerChannel):
        try:
            # Получаем полную информацию о канале-источнике
            source_entity = await event.client.get_entity(event.message.fwd_from.from_id)
        except Exception:
            source_entity = None # Не удалось получить, используем инфо из fwd_from
            if hasattr(event.message.fwd_from, 'title'):
                 return f"Источник: {event.message.fwd_from.title}"


    # Если не форвард, или не удалось получить инфо, берем текущий чат
    if not source_entity:
        source_entity = await event.get_chat()

    if hasattr(source_entity, 'username') and source_entity.username:
        return f"Источник: https://t.me/{source_entity.username}"
    elif hasattr(source_entity, 'title'):
        return f"Источник: {source_entity.title} (ID: {source_entity.id})"
    else:
        return "Источник: Не определен"


# === Новая функция для отправки и разделения сообщений
async def send_split_message(client, target_channel, text, media, source_link):
    """Отправляет сообщение, при необходимости разделяя его на части."""
    text_parts = []
    
    # Если есть и текст, и медиа
    if text.strip() and media:
        caption = text[:CAPTION_MAX_LEN]
        remaining_text = text[CAPTION_MAX_LEN:].strip()
        
        # Отправляем первое сообщение с медиа и подписью
        try:
            await client.send_file(target_channel, file=media, caption=caption, parse_mode='md')
            print(f"[OK] Отправлено медиа с подписью в {target_channel}")
        except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"❗️ Ошибка отправки медиа с подписью: {e}")
            # Если ошибка, пробуем отправить без форматирования
            try:
                await client.send_file(target_channel, file=media, caption=caption)
            except Exception as e2:
                 await client.send_message(CHANNEL_TRASH, f"❗️ Повторная ошибка отправки медиа: {e2}")

        # Если остался текст, делим его на части
        if remaining_text:
            for i in range(0, len(remaining_text), TEXT_MAX_LEN):
                text_parts.append(remaining_text[i:i + TEXT_MAX_LEN])

    # Если только текст
    elif text.strip():
        for i in range(0, len(text), TEXT_MAX_LEN):
            text_parts.append(text[i:i + TEXT_MAX_LEN])
            
    # Если только медиа (без текста)
    elif media:
         try:
            # Отправляем медиа без подписи, источник будет в отдельном сообщении
            await client.send_file(target_channel, file=media, parse_mode='md')
            print(f"[OK] Отправлено медиа без подписи в {target_channel}")
         except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"❗️ Ошибка отправки медиа: {e}")
    
    # Добавляем источник в последнее сообщение
    if text_parts:
        text_parts[-1] = f"{text_parts[-1].strip()}\n\n{source_link}"
    # Если текста не было вообще (только медиа), отправляем источник отдельно
    elif media:
        text_parts.append(source_link)

    # Отправляем текстовые части
    for i, part in enumerate(text_parts):
        try:
            await client.send_message(target_channel, part, parse_mode='md')
            print(f"[OK] Отправлена текстовая часть {i+1}/{len(text_parts)} в {target_channel}")
        except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"❗️ Ошибка отправки текста (часть {i+1}): {e}")
            # Попытка отправить без форматирования
            try:
                await client.send_message(target_channel, part)
            except Exception as e2:
                await client.send_message(CHANNEL_TRASH, f"❗️ Повторная ошибка отправки текста: {e2}")


# === Обработка сообщений
async def handle_message(event, client):
    # 2) Реагируем только на сообщения в каналах
    if not event.is_channel:
        return

    load_filter_words()

    if event.poll or event.voice or event.video_note:
        return

    message_text = event.message.text or ""
    # Игнорируем сообщения без текста, если к ним не прикреплены медиа
    if not message_text.strip() and not event.message.media:
        return
    
    # Проверяем GPT только если есть текст
    if message_text.strip():
        if len(message_text) > 4000: # Обрезаем только для анализа GPT, не для отправки
            await client.send_message(CHANNEL_TRASH, f"⚠️ Текст для анализа GPT обрезан (было {len(message_text)})")

        normalized = normalize_text(message_text)
        if filter_words.intersection(normalized):
            print(f"[FILTER] Сообщение отфильтровано по словам.")
            return

        result = await check_with_gpt(message_text, client)
    else:
        # Если текста нет, но есть медиа - считаем полезным по умолчанию
        result = "полезно"
    
    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    # Собираем все сообщения из группы (если они сгруппированы)
    messages_to_process = [event.message]
    if event.message.grouped_id:
        # Увеличиваем диапазон поиска для надежности
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 15, max_id=event.message.id + 15):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_process.append(msg)
    
    messages_to_process.sort(key=lambda m: m.id)

    # 1, 3) Получаем информацию об источнике
    source_info_text = await get_source_info(event)

    # Собираем весь текст и все медиа из группы сообщений
    full_text = ""
    media_files = []
    for msg in messages_to_process:
        if msg.text:
            full_text += msg.text.strip() + "\n\n"
        if msg.media:
            media_files.append(msg.media)
            
    full_text = full_text.strip()

    # 4, 5) Отправляем сообщение с помощью новой функции
    print(f"[{result.upper()}] Начинаю копирование из '{source_info_text}' в '{target_channel}'...")
    await send_split_message(
        client=client,
        target_channel=target_channel,
        text=full_text,
        media=media_files,
        source_link=source_info_text
    )

# === Запуск клиента
async def main():
    print("Запуск клиента...")
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    print("Клиент успешно запущен.")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event: events.NewMessage.Event):
        try:
            await handle_message(event, client)
        except Exception as e:
            # Логируем серьезные ошибки, чтобы бот не падал молча
            print(f"[!!!] КРИТИЧЕСКАЯ ОШИБКА в обработчике: {e}")
            import traceback
            traceback.print_exc()


    print("Бот в режиме ожидания новых сообщений...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
