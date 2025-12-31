# core/config.py
import os
import logging
from dotenv import load_dotenv

# [중요] .env 파일 경로 설정 (기존 유지)
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
    try:
        TARGET_CHAT_ID = int(TARGET_CHAT_ID)
    except ValueError:
        TARGET_CHAT_ID = None

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_MODEL_NAME = "gemini-2.5-flash"  # 또는 gemini-pro

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

# 관리자 ID
ADMIN_CHAT_ID = TARGET_CHAT_ID

# --- CalDAV (캘린더) [수정됨] ---
CALDAV_URL = os.getenv("CALDAV_URL")
# .env에는 USERNAME으로 되어있을 수 있으므로 둘 다 호환되게 처리
CALDAV_USERNAME = os.getenv("CALDAV_USERNAME", os.getenv("CALDAV_USER"))
CALDAV_USER = CALDAV_USERNAME  # 서비스 코드와의 호환성을 위해 Alias 추가
CALDAV_PASSWORD = os.getenv("CALDAV_PASSWORD")
CALENDAR_NAME = os.getenv("CALENDAR_NAME", None)  # 특정 캘린더 이름 (없으면 전체)

# --- CardDAV (연락처) [수정됨] ---
CARDDAV_URL = os.getenv("CARDDAV_URL")
CARDDAV_USERNAME = os.getenv("CARDDAV_USERNAME", os.getenv("CARDDAV_USER"))
CARDDAV_USER = CARDDAV_USERNAME  # 서비스 코드와의 호환성을 위해 Alias 추가
CARDDAV_PASSWORD = os.getenv("CARDDAV_PASSWORD")

# --- 이메일 설정 ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# --- 스케줄링 설정 ---
TIMEZONE = os.getenv("TZ", "Asia/Seoul")
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "7"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))

# --- 데이터베이스 파일 경로 ---
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
DB_FILE = os.path.join(DATA_DIR, "notifications.db")
