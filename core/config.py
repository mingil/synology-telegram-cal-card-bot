# core/config.py
import os
import logging
from dotenv import load_dotenv

# [중요] .env 파일 경로 수정: 현재 파일(core/config.py)의 부모(core)의 부모(root) 폴더
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")

if os.path.exists(DOTENV_PATH):
    load_dotenv(dotenv_path=DOTENV_PATH)
    print(f"✅ 설정 로드 완료: {DOTENV_PATH}")
else:
    print(f"⚠️ .env 파일을 찾을 수 없습니다: {DOTENV_PATH}")

# --- 로깅 설정 ---
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# --- 텔레그램 & AI ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")
if TARGET_CHAT_ID:
    TARGET_CHAT_ID = int(TARGET_CHAT_ID)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_MODEL_NAME = "gemini-2.5-flash"

# --- 인증 & 보안 ---
BOT_PASSWORD = os.getenv("BOT_PASSWORD")
MAX_PASSWORD_ATTEMPTS = 3
TRUSTED_USER_IDS_STR = os.getenv("TRUSTED_USER_IDS", "")
TRUSTED_USER_IDS = []
if TRUSTED_USER_IDS_STR:
    try:
        TRUSTED_USER_IDS = [
            int(uid.strip())
            for uid in TRUSTED_USER_IDS_STR.split(",")
            if uid.strip().isdigit()
        ]
    except ValueError:
        pass

# 관리자 ID (기본적으로 TARGET_CHAT_ID를 관리자로 간주)
ADMIN_CHAT_ID = TARGET_CHAT_ID

# --- CalDAV (캘린더) ---
CALDAV_URL = os.getenv("CALDAV_URL")
CALDAV_USERNAME = os.getenv("CALDAV_USERNAME")
CALDAV_PASSWORD = os.getenv("CALDAV_PASSWORD")

# --- CardDAV (연락처) ---
CARDDAV_URL = os.getenv("CARDDAV_URL")
CARDDAV_USERNAME = os.getenv("CARDDAV_USERNAME")
CARDDAV_PASSWORD = os.getenv("CARDDAV_PASSWORD")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# --- 스케줄링 설정 ---
TIMEZONE = os.getenv("TZ", "Asia/Seoul")
SCHEDULE_HOUR = 7  # 오전 7시 알림
SCHEDULE_MINUTE = 0

# --- 데이터베이스 파일 경로 ---
# data 폴더는 루트 폴더 아래에 위치
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
DB_FILE = os.path.join(DATA_DIR, "notifications.db")
