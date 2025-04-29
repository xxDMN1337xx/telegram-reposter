import asyncio
import os
from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME, TARGET_CHANNEL

filter_words = set()

def load_filter_words():
    global filter_words
    if os.path.exists('filter_words.txt'):
        with open('filter_words.txt', 'r', encoding='utf-8') as f:
            filter_words = set(line.strip().lower() for line in f if line.strip())

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    load_filter_words()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        load_filter_words()  # переcчитывать файл каждый раз (можно оптимизировать)

        message_text = event.raw_text.lower()
        if any(word in message_text for word in filter_words):
            return  # пропускаем запрещенные сообщения

        if event.is_channel and not event.out:
            await event.forward_to(TARGET_CHANNEL)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
