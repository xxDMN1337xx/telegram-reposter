import asyncio
import os
import re
import pymorphy2
import g4f
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntity
from config import API_ID, API_HASH, SESSION_NAME

# === Константы
CHANNEL_GOOD = 'https://t.me/fbeed1337'
CHANNEL_TRASH = 'https://t.me/musoradsxx'
MAX_CAPTION_LENGTH = 1000
MAX_MESSAGE_LENGTH = 4000

# === Провайдеры GPT (согласно вашему новому списку)
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

# === Лемматизация (без изменений)
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

# === Проверка GPT (обновленная логика провайдеров)
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

    # 7. Новая логика вызова провайдеров
    async def call_provider(provider, index):
        # Попытка 1: без указания модели
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    g4f.ChatCompletion.create,
                    provider=provider,
                    messages=[{"role": "user", "content": prompt}]
                ), timeout=30
            )
            result = (response or "").strip().lower()
            result = re.sub(r'[^а-яА-Я]', '', result)
            if result in ['реклама', 'бесполезно', 'полезно']:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{len(fallback_providers)} ✅ {provider.__name__} (auto): {result}")
                return result
        except Exception:
            pass # Ошибка - это нормально, пробуем следующий вариант

        # Попытка 2: с моделью 'gpt-3.5'
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    g4f.ChatCompletion.create,
                    provider=provider,
                    model="gpt-3.5",
                    messages=[{"role": "user", "content": prompt}]
                ), timeout=30
            )
            result = (response or "").strip().lower()
            result = re.sub(r'[^а-яА-Я]', '', result)
            if result in ['реклама', 'бесполезно', 'полезно']:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{len(fallback_providers)} ✅ {provider.__name__} (gpt-3.5): {result}")
                return result
            else:
                await client.send_message(CHANNEL_TRASH, f"{index+1}/{len(fallback_providers)} ⚠️ {provider.__name__} странный ответ: '{result}'")

        except Exception as e:
            await client.send_message(CHANNEL_TRASH, f"{index+1}/{len(fallback_providers)} ❌ {provider.__name__} не сработал: {str(e)[:100]}")
        
        return None # Провайдер не смог дать ответ

    tasks = [call_provider(p, i) for i, p in enumerate(fallback_providers)]
    raw_results = await asyncio.gather(*tasks)

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

    if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]):
        return "полезно"
    else:
        return "мусор"

# === Вспомогательные функции для отправки
async def get_source_info(event, client):
    """ 3. Определяет истинный источник сообщения (канал, откуда был репост) """
    source_entity = None
    # Если это репост, берем информацию из него
    if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
        try:
            source_entity = await client.get_entity(event.message.fwd_from.from_id.channel_id)
        except Exception:
            source_entity = None # Не удалось получить entity
    # Если не репост, берем инфо из текущего чата
    elif event.is_channel:
        source_entity = event.chat

    if source_entity:
        if getattr(source_entity, 'username', None):
            return f"https://t.me/{source_entity.username}"
        else:
            title = getattr(source_entity, 'title', 'Unknown Channel')
            channel_id = getattr(source_entity, 'id', 'N/A')
            return f"{title} (ID: {channel_id})"
    return "Источник не определен"


async def send_copied_message(client, target_channel, messages_to_forward, source_string):
    """ 1, 4, 5. Собирает, форматирует и отправляет скопированное сообщение, делит при необходимости """
    full_text = ""
    all_entities = []
    media_files = []

    # Собираем текст, медиа и сущности форматирования из группы сообщений
    for msg in sorted(messages_to_forward, key=lambda m: m.id):
        current_len = len(full_text)
        if msg.text:
            text_to_add = msg.text.strip()
            full_text += text_to_add + "\n"
            if msg.entities:
                for entity in msg.entities:
                    entity.offset += current_len
                    all_entities.append(entity)
        if msg.media and not getattr(msg.media, 'poll', None):
            media_files.append(msg.media)
    
    full_text = full_text.strip()
    
    if not full_text and not media_files:
        return # Пустое сообщение, не отправляем

    # 4. Логика разделения сообщений
    if media_files:
        caption = full_text[:MAX_CAPTION_LENGTH]
        # 5. Сохраняем форматирование для подписи
        caption_entities = [e for e in all_entities if e.offset < len(caption)]
        
        remaining_text = full_text[MAX_CAPTION_LENGTH:].strip()
        
        await client.send_file(
            target_channel,
            file=media_files,
            caption=caption,
            formatting_entities=caption_entities,
            link_preview=False
        )
        
        text_to_send_later = remaining_text
    else:
        text_to_send_later = full_text

    # Добавляем источник в конец оставшегося или полного текста
    if text_to_send_later:
        final_text = f"{text_to_send_later}\n\n{source_string}"
    else:
        # Если весь текст ушел в подпись к медиа, источник отправляется отдельно
        final_text = source_string

    # Отправляем оставшийся текст, разбивая на части, если нужно
    while final_text:
        part_to_send = final_text[:MAX_MESSAGE_LENGTH]
        final_text = final_text[MAX_MESSAGE_LENGTH:]
        await client.send_message(target_channel, part_to_send, link_preview=False)


# === Основной обработчик сообщений
async def handle_message(event, client):
    # 2. Проверяем, что сообщение из канала, а не из чата или от пользователя
    if not event.is_channel:
        return

    load_filter_words()

    if event.poll or event.voice or event.video_note:
        return

    message_text = event.message.text or ""
    if not message_text.strip() and not event.message.media:
        return
        
    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(message_text, client)

    # Собираем сгруппированные сообщения
    messages_to_forward = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_forward.append(msg)

    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH
    
    # 1, 3. Получаем информацию об источнике
    source_info = await get_source_info(event, client)
    source_string = f"Источник: {source_info}"

    # 1, 4, 5. Используем новую функцию для копирования и отправки
    await send_copied_message(client, target_channel, messages_to_forward, source_string)
    print(f"[OK] Скопировано из источника: {source_info}. Результат: {result}")


# === Запуск клиента
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    print("Клиент запускается...")
    await client.start()
    print("Клиент запущен и слушает сообщения.")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            await handle_message(event, client)
        except Exception as e:
            print(f"[!!!] Произошла критическая ошибка в обработчике: {e}")
            # Можно добавить отправку сообщения об ошибке себе в ЛС или в лог-канал
            await client.send_message(CHANNEL_TRASH, f"КРИТИЧЕСКАЯ ОШИБКА: {e}")


    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
