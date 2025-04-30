import asyncio
import os
import pymorphy2
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME, TARGET_CHANNEL

LAST_ID_FILE = 'last_id.txt'
filter_words = set()
last_processed_id = 0

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

def load_last_processed_id():
    global last_processed_id
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'r') as f:
            try:
                last_processed_id = int(f.read().strip())
            except:
                last_processed_id = 0

def save_last_processed_id(message_id):
    with open(LAST_ID_FILE, 'w') as f:
        f.write(str(message_id))

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    load_filter_words()
    load_last_processed_id()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        load_filter_words()

        if event.id <= last_processed_id:
            print(f"[SKIP] Уже обработано ID {event.id}")
            return

        if event.poll:
            print("[SKIP] Это опрос")
            return

        message_text = event.raw_text or ""
        print(f"[LOG] Получено сообщение ID {event.id} из {event.chat_id}: {message_text}")

        normalized_words = normalize_text(message_text)
        print(f"[DEBUG] Леммы сообщения: {normalized_words}")
        print(f"[DEBUG] Фильтр: {filter_words}")

        # ❌ Временно отключаем фильтр (для отладки)
        # if filter_words.intersection(normalized_words):
        #     print("[FILTERED] Совпадение по фильтру — сообщение пропущено")
        #     return

        # Проверка на то, что это канал и не исходящее
        if event.chat and getattr(event.chat, 'broadcast', False) and not event.out:
            print("[PASS] Репостим сообщение...")
            try:
                await event.forward_to(TARGET_CHANNEL)
                save_last_processed_id(event.id)
                print("[OK] Репост успешно")
            except Exception as e:
                print(f"[ERROR] Не удалось репостить: {e}")
        else:
            print(f"[DEBUG] НЕ репостим: broadcast={getattr(event.chat, 'broadcast', None)}, out={event.out}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
