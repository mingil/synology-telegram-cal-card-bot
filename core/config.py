import os
import logging
from typing import Optional
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")

if os.path.exists(DOTENV_PATH):
    load_dotenv(dotenv_path=DOTENV_PATH, override=True)
    print(f"✅ 설정 로드 완료: {DOTENV_PATH}")


def _get_env_str(key: str, default: Optional[str] = None) -> Optional[str]:
    """환경변수를 안전하게 문자열로 읽고 앞뒤 공백/개행문자를 제거하는 헬퍼 함수"""
    val = os.getenv(key)
    if val is not None:
        cleaned = val.strip()
        return cleaned if cleaned else default
    return default


def _get_env_int(key: str, default: int = 0) -> int:
    """환경변수를 안전하게 int로 변환하는 헬퍼 함수 (에러 방어)"""
    val = _get_env_str(key)
    if val and val.lstrip("-").isdigit():
        return int(val)
    return default


# --- 로깅 설정 ---
LOG_LEVEL_STR = (_get_env_str("LOG_LEVEL", "INFO") or "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# --- 텔레그램 & AI ---
TELEGRAM_BOT_TOKEN = _get_env_str("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = _get_env_int("TARGET_CHAT_ID") or None
ADMIN_CHAT_ID = TARGET_CHAT_ID

GOOGLE_API_KEY = _get_env_str("GOOGLE_API_KEY")
AI_MODEL_NAME = _get_env_str("AI_MODEL_NAME", "gemini-3.6-flash") or "gemini-3.6-flash"

# --- 인증 & 보안 ---
BOT_PASSWORD = _get_env_str("BOT_PASSWORD")
MAX_PASSWORD_ATTEMPTS = _get_env_int("MAX_PASSWORD_ATTEMPTS", 3) or 3

TRUSTED_USER_IDS = []
_trusted_str = _get_env_str("TRUSTED_USER_IDS", "")
if _trusted_str:
    TRUSTED_USER_IDS = [
        int(uid.strip())
        for uid in _trusted_str.split(",")
        if uid.strip().lstrip("-").isdigit()
    ]

# 관리자 ID(TARGET_CHAT_ID)가 설정되어 있다면 자동으로 신뢰 목록에 포함 (초기 설정 실수 방지)
if ADMIN_CHAT_ID and ADMIN_CHAT_ID not in TRUSTED_USER_IDS:
    TRUSTED_USER_IDS.append(ADMIN_CHAT_ID)

# --- CalDAV (캘린더) ---
CALDAV_URL = _get_env_str("CALDAV_URL")
CALDAV_USERNAME = _get_env_str("CALDAV_USERNAME") or _get_env_str("CALDAV_USER")
CALDAV_USER = CALDAV_USERNAME
CALDAV_PASSWORD = _get_env_str("CALDAV_PASSWORD")
CALENDAR_NAME = _get_env_str("CALENDAR_NAME")

# --- CardDAV (연락처) ---
CARDDAV_URL = _get_env_str("CARDDAV_URL")
CARDDAV_USERNAME = _get_env_str("CARDDAV_USERNAME") or _get_env_str("CARDDAV_USER")
CARDDAV_USER = CARDDAV_USERNAME
CARDDAV_PASSWORD = _get_env_str("CARDDAV_PASSWORD")

# --- 이메일 설정 ---
SMTP_SERVER = _get_env_str("SMTP_SERVER", "smtp.gmail.com") or "smtp.gmail.com"
SMTP_PORT = _get_env_int("SMTP_PORT", 587)
SMTP_EMAIL = _get_env_str("SMTP_EMAIL", "") or ""
SMTP_PASSWORD = _get_env_str("SMTP_PASSWORD", "") or ""

# --- 스케줄링 설정 ---
TIMEZONE = _get_env_str("TZ", "Asia/Seoul") or "Asia/Seoul"
SCHEDULE_HOUR = max(0, min(23, _get_env_int("SCHEDULE_HOUR", 7)))
SCHEDULE_MINUTE = max(0, min(59, _get_env_int("SCHEDULE_MINUTE", 0)))

# --- 데이터베이스 파일 경로 ---
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "notifications.db")
