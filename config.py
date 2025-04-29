import os
from dotenv import load_dotenv

load_dotenv()  # ← эта строка ОБЯЗАТЕЛЬНА

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "session")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")
