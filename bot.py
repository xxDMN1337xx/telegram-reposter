import asyncio
import os
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME, TARGET_CHANNEL
import pymorphy2

LAST_ID_FILE = 'last_id.txt'
filter_words = set()
last_processed_id = 0
morph = pymorphy2.MorphAnalyzer()

def load_filter_words():
    global filter_words
    if os.path.exists('filter_words.txt'):
        with open('filter_words.txt', 'r', encoding='utf-8') as f:
            filter_words = set(line.strip().lower() for line in f if line.strip())

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

def normalize_text(text):
    words = text.split()
    normalized = set()
    for word in words:
        p = morph.parse(word)[0]
        normalized.add(p.normal_form.lower())
    return normalized

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    load_filter_words()
    load_last_processed_id()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        load_filter_words()

        if event.id <= last_processed_id:
            return

        if event.poll:
            return

        message_text = event.raw_text.lower()
        norm_words = normalize_text(message_text)

        if any(fw in norm_words for fw in filter_words):
            return  # Нашлось совпадение по лемме — фильтруем

        if event.is_channel and not event.out:
            await event.forward_to(TARGET_CHANNEL)
            save_last_processed_id(event.id)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
