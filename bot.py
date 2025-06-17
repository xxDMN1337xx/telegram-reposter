import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityBold, MessageEntityTextUrl
from config import API_ID, API_HASH, SESSION_NAME
from telethon.utils import get_peer_id

# === Каналы для публикации
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'

# === Провайдеры GPT (Обновленный список)
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
    words = re.findall(r'\b\w+\b', text.lower())
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

    results = []
    total = len(fallback_providers)

    async def call_provider(provider, index):
        try:
            # Используем g4f.models.default
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
                print(f"{index+1}/{total} ✅ {provider.__name__}: {result}")
                # await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ✅ {provider.__name__}: {result}")
                return result
            else:
                print(f"{index+1}/{total} ⚠️ {provider.__name__} странный ответ: '{result}'")
                # await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ⚠️ {provider.__name__} странный ответ: '{result}'")
        except Exception as e:
            print(f"{index+1}/{total} ❌ {provider.__name__} ошибка: {str(e)[:100]}")
            # await client.send_message(CHANNEL_TRASH, f"{index+1}/{total} ❌ {provider.__name__} ошибка: {str(e)[:100]}")
        return None

    tasks = [call_provider(p, i) for i, p in enumerate(fallback_providers)]
    raw_results = await asyncio.gather(*tasks)

    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    for result in raw_results:
        if result in summary:
            summary[result] += 1
    
    total_valid = sum(summary.values())

    # Логирование в консоль и в канал для мусора
    log_message = f"📊 Сводка GPT: {summary}"
    print(log_message)
    await client.send_message(CHANNEL_TRASH, log_message)

    if total_valid == 0:
        await client.send_message(CHANNEL_TRASH, "❌ Ни один GPT-провайдер не дал ответ. Повтор через 30 минут.")
        await asyncio.sleep(1800)
        return await check_with_gpt(text, client)

    if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]):
        return "полезно"
    else:
        return "мусор"

# === Новая функция для определения источника
async def get_source_info(event, client):
    """Определяет источник сообщения (оригинал, если репост) и формирует ссылку."""
    source_peer = None
    try:
        # 3) Источник сообщения если это репост должен быть канал с которого репостнули
        if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
            source_peer = await client.get_entity(event.message.fwd_from.from_id)
        else:
            source_peer = await event.get_chat()
        
        if hasattr(source_peer, 'username') and source_peer.username:
            return f"https://t.me/{source_peer.username}"
        else:
            return f"{getattr(source_peer, 'title', 'Unknown Channel')} (ID: {get_peer_id(source_peer)})"
    except Exception as e:
        print(f"[!] Не удалось получить информацию об источнике: {e}")
        # Запасной вариант
        chat = await event.get_chat()
        return f"{getattr(chat, 'title', 'Unknown Channel')} (ID: {event.chat_id})"


# === Новая функция для объединения текста и форматирования
def combine_grouped_messages(messages):
    """Объединяет текст и форматирование из нескольких сообщений."""
    full_text = ""
    full_entities = []
    media_files = []
    
    # Сортируем на всякий случай
    messages.sort(key=lambda m: m.id)

    for msg in messages:
        if msg.media and not hasattr(msg.media, 'webpage'):
            media_files.append(msg.media)
        
        if msg.text:
            text_part = msg.text
            # Добавляем перенос строки между сообщениями, если уже есть текст
            if full_text:
                full_text += "\n\n"

            current_offset = len(full_text)
            full_text += text_part

            if msg.entities:
                for entity in msg.entities:
                    entity.offset += current_offset
                    full_entities.append(entity)
                    
    return full_text.strip(), full_entities, media_files

# === Новая функция для отправки с разделением
async def send_split_message(client, target_channel, text, entities, media, source_link):
    """Отправляет сообщение, разделяя его при необходимости и добавляя источник."""
    
    # Добавляем источник в конец
    final_text = text + f"\n\nИсточник: {source_link}"
    
    # 4) Деление сообщений
    # 5) Сохранение форматирования
    MAX_CAPTION_LEN = 1024
    MAX_TEXT_LEN = 4096
    
    try:
        if media:
            # Отправка с медиа
            caption_text = final_text[:MAX_CAPTION_LEN]
            remaining_text = final_text[MAX_CAPTION_LEN:]

            # Фильтруем entities только для подписи
            caption_entities = [e for e in entities if e.offset + e.length <= MAX_CAPTION_LEN]

            await client.send_file(
                target_channel,
                file=media,
                caption=caption_text,
                caption_entities=caption_entities
            )
            print("[OK] Отправлено сообщение с медиа и подписью.")

            if remaining_text:
                # Фильтруем и сдвигаем entities для оставшегося текста
                remaining_entities = []
                for e in entities:
                    if e.offset >= MAX_CAPTION_LEN:
                        e.offset -= MAX_CAPTION_LEN
                        remaining_entities.append(e)
                
                # Telethon сам разделит оставшийся текст, если он больше 4096
                await client.send_message(
                    target_channel,
                    message=remaining_text,
                    entities=remaining_entities
                )
                print("[OK] Отправлен оставшийся текст.")

        else:
            # Отправка только текста
            # Telethon сам разделит сообщение, если оно длиннее 4096 символов
            await client.send_message(
                target_channel,
                message=final_text,
                entities=entities
            )
            print("[OK] Отправлено текстовое сообщение.")
            
    except Exception as e:
        print(f"[!!!] Критическая ошибка при отправке сообщения: {e}")
        # Запасной вариант: отправить как есть, без форматирования
        try:
            await client.send_message(target_channel, final_text)
        except Exception as e2:
            print(f"[!!!] Запасной вариант отправки тоже провалился: {e2}")

# === Основной обработчик сообщений
async def handle_message(event, client):
    # 2) Проверять только сообщения из каналов
    if not event.is_channel or event.is_group:
        return

    # Игнорировать опросы и голосовые/видео сообщения
    if event.poll or event.voice or event.video_note:
        return

    # Загружаем стоп-слова
    load_filter_words()
    
    # Собираем все сообщения из группы (если есть)
    messages_to_process = [event.message]
    if event.message.grouped_id:
        # Ждем немного, чтобы все сообщения группы успели прийти
        await asyncio.sleep(2) 
        async for msg in client.iter_messages(event.chat_id, limit=20, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_process.append(msg)
    
    # Объединяем текст, форматирование и медиа
    full_text, full_entities, media_files = combine_grouped_messages(messages_to_process)

    if not full_text.strip() and not media_files:
        return # Пустое сообщение, не обрабатываем
    
    if len(full_text) > 4000: # Ограничение для анализа GPT
        print(f"⚠️ Сообщение для анализа GPT обрезано до 4000 символов (было {len(full_text)})")
    
    # Проверка по стоп-словам
    normalized = normalize_text(full_text)
    if filter_words.intersection(normalized):
        print(f"[!] Сообщение пропущено из-за стоп-слов: {filter_words.intersection(normalized)}")
        return
    
    # Получаем результат от GPT
    result = await check_with_gpt(full_text, client)
    
    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH
    source_link = await get_source_info(event, client)
    
    # 1) Копируем со всех каналов с указанием источника
    print(f"-> Результат: '{result}'. Канал: {target_channel}. Источник: {source_link}")
    
    # Используем новую функцию для отправки
    await send_split_message(
        client=client,
        target_channel=target_channel,
        text=full_text,
        entities=full_entities,
        media=media_files[0] if media_files else None,
        source_link=source_link
    )


# === Запуск клиента
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    print("Клиент запускается...")
    await client.start()
    print("Клиент запущен и готов к работе.")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            await handle_message(event, client)
        except Exception as e:
            print(f"[!!!] Глобальная ошибка в обработчике: {e}")
            import traceback
            traceback.print_exc()


    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
