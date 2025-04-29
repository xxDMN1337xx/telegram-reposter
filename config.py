import os

API_ID = int(os.getenv("API_ID"))  # Получи у Telegram
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "session")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")  # id канала, куда репостить
