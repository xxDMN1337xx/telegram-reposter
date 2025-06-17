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

# === GPT фильтрация
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
    return "полезно" if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]) else "мусор"


# === Обработка сообщений (ИСПРАВЛЕННАЯ ВЕРСИЯ) ===
async def handle_message(event, client):
    load_filter_words()

    if not isinstance(event.message.to_id, PeerChannel):
        return

    if event.poll or event.voice or event.video_note:
        return

    message_text_for_gpt = event.message.text or ""
    
    if not message_text_for_gpt.strip() and not event.message.media:
        return

    if len(message_text_for_gpt) > 2000:
        await client.send_message(CHANNEL_TRASH, f"⚠️ Сообщение обрезано до 2000 символов (было {len(message_text_for_gpt)})")

    normalized = normalize_text(message_text_for_gpt)
    if filter_words.intersection(normalized):
        return

    if message_text_for_gpt.strip():
        result = await check_with_gpt(message_text_for_gpt, client)
    else:
        result = "мусор"

    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    # Собираем все сообщения из группы (если это альбом)
    messages_to_copy = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_copy.append(msg)
    messages_to_copy.sort(key=lambda m: m.id)

    # Отправляем копии сообщений с полным сохранением форматирования
    try:
        # Telethon сам отправит их как альбом, если это возможно, скопировав все
        sent_messages = await client.send_message(
            target_channel,
            file=messages_to_copy  # Передаем список сообщений
        )

        # Формируем текст с источником
        source_text = ""
        source_peer = None
        
        # Определяем источник: пересланное сообщение или канал, где оно было
        if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
            source_peer = PeerChannel(event.message.fwd_from.from_id.channel_id)
        else:
            source_peer = event.message.peer_id
            
        try:
            entity = await client.get_entity(source_peer)
            # Создаем красивую Markdown-ссылку
            source_text = f"Источник: [{entity.title}](https://t.me/{entity.username})" if entity.username else f"Источник: {entity.title}"
        except Exception as e:
            if hasattr(source_peer, 'channel_id'):
                source_text = f"Источник: ID {source_peer.channel_id}"
            else:
                 source_text = "Источник: не определен"
            print(f"Не удалось получить entity для источника: {e}")

        # Отправляем сообщение с источником в ответ на последнее из скопированных
        if sent_messages:
            # Если было отправлено несколько сообщений (альбом), берем последнее
            last_sent_message = sent_messages[-1] if isinstance(sent_messages, list) else sent_messages
            
            await client.send_message(
                target_channel,
                message=source_text,
                reply_to=last_sent_message.id,
                parse_mode='md' # Включаем обработку Markdown для ссылки
            )
        
        print(f"[OK] Копия с источника: {source_text.replace('Источник: ', '')} -> Канал: {result}")

    except Exception as e:
        print(f"[!!!] Критическая ошибка при копировании сообщения: {e}")


# === Запуск клиента
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    # Кэш для отсеивания дублей из одной группы
    processed_groups = set()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        # Если сообщение является частью группы (альбома)
        if event.message.grouped_id:
            # Если мы уже обработали эту группу, выходим
            if event.message.grouped_id in processed_groups:
                return
            # Иначе добавляем ID группы в кэш и обрабатываем
            processed_groups.add(event.message.grouped_id)
            # Запускаем таймер для очистки кэша через 10 секунд
            asyncio.create_task(clear_group_id(event.message.grouped_id))
        
        try:
            await handle_message(event, client)
        except Exception as e:
            print(f"[!!!] Критическая ошибка в обработчике: {e}")

    async def clear_group_id(group_id):
        await asyncio.sleep(10) # Даем время всем сообщениям из группы прийти
        processed_groups.discard(group_id)

    print("Бот запущен и слушает новые сообщения...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
