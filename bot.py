import asyncio
import os
import json
import csv
import pymorphy2
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.tl.functions.messages import GetMessagesRequest
from config import API_ID, API_HASH, SESSION_NAME, TARGET_CHANNEL

LAST_ID_FILE = 'last_ids.json'
POSTED_LOG_FILE = 'posted_messages.json'
GOOD_LOG_FILE = 'good_log.csv'
DELETED_LOG_FILE = 'deleted_log.csv'

last_processed_ids = {}
filter_words = set()
posted_messages = {}
morph = pymorphy2.MorphAnalyzer(lang='ru')


# ===== Служебные функции =====

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
        except:
            last_processed_ids = {}


def save_last_processed_id(chat_id, message_id):
    last_processed_ids[str(chat_id)] = message_id
    with open(LAST_ID_FILE, 'w') as f:
        json.dump(last_processed_ids, f)


def load_posted_messages():
    global posted_messages
    if os.path.exists(POSTED_LOG_FILE):
        with open(POSTED_LOG_FILE, 'r') as f:
            posted_messages.update(json.load(f))


def save_posted_messages():
    with open(POSTED_LOG_FILE, 'w') as f:
        json.dump(posted_messages, f)


def log_deleted(chat_id, msg_id, text):
    with open(DELETED_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{chat_id},{msg_id},\"{text.replace('\"', '\"\"')[:1000]}\"\n")


def log_good(chat_id, msg_id, text):
    with open(GOOD_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{chat_id},{msg_id},\"{text.replace('\"', '\"\"')[:1000]}\"\n")


def cleanup_old_posts():
    now = datetime.utcnow()
    to_remove = []
    for key, data in posted_messages.items():
        ts = datetime.fromisoformat(data["timestamp"])
        if now - ts > timedelta(days=7):
            log_good(data["chat_id"], data["msg_id"], data["text"])
            to_remove.append(key)
    for key in to_remove:
        del posted_messages[key]
    if to_remove:
        save_posted_messages()
        print(f"[CLEANUP] Добавлено в good_log: {len(to_remove)}")


# ===== Основной бот =====

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    load_filter_words()
    load_last_processed_ids()
    load_posted_messages()
    cleanup_old_posts()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        load_filter_words()

        chat_id = str(event.chat_id)
        message_id = event.id

        if event.poll:
            print("[SKIP] Это опрос")
            return

        if event.voice or event.video_note:
            print("[SKIP] Голосовое сообщение или кружочек")
            return

        if getattr(event.message, 'grouped_id', None):
            print("[SKIP] Это часть альбома")
            return

        if chat_id in last_processed_ids and message_id <= last_processed_ids[chat_id]:
            print(f"[SKIP] Уже обработано: {message_id}")
            return

        message_text = event.raw_text or ""
        print(f"[NEW] {chat_id}:{message_id} — {message_text[:100]}")

        normalized = normalize_text(message_text)
        if filter_words.intersection(normalized):
            print("[FILTERED] Фильтр по словам")
            return

        if event.chat and getattr(event.chat, 'broadcast', False) and not event.out:
            try:
                await event.forward_to(TARGET_CHANNEL)
                save_last_processed_id(chat_id, message_id)

                # логируем для последующего анализа (через 7 дней)
                key = f"{chat_id}:{message_id}"
                posted_messages[key] = {
                    "chat_id": chat_id,
                    "msg_id": message_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "text": message_text[:1000]
                }
                save_posted_messages()
                print("[OK] Репост успешно")
            except Exception as e:
                print(f"[ERROR] Репост не удался: {e}")

    @client.on(events.Album)
    async def album_handler(event):
        chat_id = str(event.chat_id)
        grouped_id = getattr(event.messages[0], 'grouped_id', 'unknown')
        print(f"[ALBUM] {chat_id}:{grouped_id}")

        caption = event.messages[0].raw_text or ""
        normalized = normalize_text(caption)
        if filter_words.intersection(normalized):
            print("[FILTERED] Альбом по фильтру")
            return

        try:
            await client.forward_messages(TARGET_CHANNEL, event.messages)
            last_id = max(msg.id for msg in event.messages)
            save_last_processed_id(chat_id, last_id)

            key = f"{chat_id}:{last_id}"
            posted_messages[key] = {
                "chat_id": chat_id,
                "msg_id": last_id,
                "timestamp": datetime.utcnow().isoformat(),
                "text": caption[:1000]
            }
            save_posted_messages()
            print("[OK] Альбом отправлен")
        except Exception as e:
            print(f"[ERROR] Репост альбома не удался: {e}")

    @client.on(events.MessageDeleted())
    async def deleted_handler(event):
        for msg_id in event.deleted_ids:
            key = f"{event.chat_id}:{msg_id}"
            try:
                result = await client(GetMessagesRequest(id=[msg_id]))
                msg = result.messages[0]
                text = msg.raw_text or "[нет текста]"
                log_deleted(event.chat_id, msg_id, text)
                if key in posted_messages:
                    del posted_messages[key]
                    save_posted_messages()
                print(f"[DELETED] Лог удалённого {msg_id}")
            except Exception as e:
                print(f"[ERROR] Не удалось логировать удаление: {e}")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
