import os
import logging
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")

if os.path.exists(DOTENV_PATH):
    load_dotenv(dotenv_path=DOTENV_PATH)
    print(f"✅ 설정 로드 완료: {DOTENV_PATH}")

def _get_env_int(key: str, default: int = 0) -> int:
    """환경변수를 안전하게 int로 변환하는 헬퍼 함수 (에러 방어)"""
    val = os.getenv(key)
    if val and val.strip().lstrip('-').isdigit():
        return int(val.strip())
    return default

# --- 로깅 설정 ---
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# --- 텔레그램 & AI ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = _get_env_int("TARGET_CHAT_ID") or None
ADMIN_CHAT_ID = TARGET_CHAT_ID

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_MODEL_NAME = os.getenv("AI_MODEL_NAME", "gemini-2.5-flash")

# --- 인증 & 보안 ---
BOT_PASSWORD = os.getenv("BOT_PASSWORD")
MAX_PASSWORD_ATTEMPTS = 3

TRUSTED_USER_IDS = []
_trusted_str = os.getenv("TRUSTED_USER_IDS", "")
if _trusted_str:
    TRUSTED_USER_IDS = [
        int(uid.strip())
        for uid in _trusted_str.split(",")
        if uid.strip().lstrip('-').isdigit()
    ]

# --- CalDAV (캘린더) ---
CALDAV_URL = os.getenv("CALDAV_URL")
CALDAV_USERNAME = os.getenv("CALDAV_USERNAME") or os.getenv("CALDAV_USER")
CALDAV_USER = CALDAV_USERNAME
CALDAV_PASSWORD = os.getenv("CALDAV_PASSWORD")
CALENDAR_NAME = os.getenv("CALENDAR_NAME")

# --- CardDAV (연락처) ---
CARDDAV_URL = os.getenv("CARDDAV_URL")
CARDDAV_USERNAME = os.getenv("CARDDAV_USERNAME") or os.getenv("CARDDAV_USER")
CARDDAV_USER = CARDDAV_USERNAME
CARDDAV_PASSWORD = os.getenv("CARDDAV_PASSWORD")

# --- 이메일 설정 ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = _get_env_int("SMTP_PORT", 587)
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# --- 스케줄링 설정 ---
TIMEZONE = os.getenv("TZ", "Asia/Seoul")
SCHEDULE_HOUR = _get_env_int("SCHEDULE_HOUR", 7)
SCHEDULE_MINUTE = _get_env_int("SCHEDULE_MINUTE", 0)

# --- 데이터베이스 파일 경로 ---
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True) # if문 없이 한 줄로 안전하게 폴더 생성
DB_FILE = os.path.join(DATA_DIR, "notifications.db")
