import asyncio
import os
import json
import pymorphy2
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME, TARGET_CHANNEL

LAST_ID_FILE = 'last_ids.json'
last_processed_ids = {}
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

def load_last_processed_ids():
    global last_processed_ids
    if os.path.exists(LAST_ID_FILE):
        try:
            with open(LAST_ID_FILE, 'r') as f:
                last_processed_ids = json.load(f)
        except Exception as e:
            print(f"[ERROR] Не удалось загрузить {LAST_ID_FILE}: {e}")
            last_processed_ids = {}

def save_last_processed_id(chat_id, message_id):
    last_processed_ids[str(chat_id)] = message_id
    try:
        with open(LAST_ID_FILE, 'w') as f:
            json.dump(last_processed_ids, f)
    except Exception as e:
        print(f"[ERROR] Не удалось сохранить {LAST_ID_FILE}: {e}")

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    load_filter_words()
    load_last_processed_ids()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        load_filter_words()

        chat_id = str(event.chat_id)
        message_id = event.id

        if event.poll:
            print("[SKIP] Это опрос")
            return

        if chat_id in last_processed_ids and message_id <= last_processed_ids[chat_id]:
            print(f"[SKIP] Уже обработано: ID {message_id} в чате {chat_id}")
            return

        message_text = event.raw_text or ""
        print(f"[LOG] Получено сообщение ID {message_id} из {chat_id}: {message_text}")

        normalized_words = normalize_text(message_text)
        print(f"[DEBUG] Леммы сообщения: {normalized_words}")
        print(f"[DEBUG] Фильтр: {filter_words}")

        # ❌ Отключи фильтр если хочешь всё репостить
        if filter_words.intersection(normalized_words):
            print("[FILTERED] Совпадение с фильтром — не репостим")
            return

        if event.chat and getattr(event.chat, 'broadcast', False) and not event.out:
            print("[PASS] Репостим сообщение...")
            try:
                await event.forward_to(TARGET_CHANNEL)
                save_last_processed_id(chat_id, message_id)
                print("[OK] Репост успешно")
            except Exception as e:
                print(f"[ERROR] Не удалось репостить: {e}")
        else:
            print(f"[DEBUG] НЕ репостим: broadcast={getattr(event.chat, 'broadcast', None)}, out={event.out}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
