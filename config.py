# config.py 파일 전체 내용 (수정됨)

import os
import logging
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    print(f".env 파일 로드 성공: {dotenv_path}")
else:
    print(f".env 파일을 찾을 수 없습니다: {dotenv_path}")

# --- 로거 설정 ---
# 로그 레벨 설정 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL = logging.INFO
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

# --- Telegram & AI ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_MODEL_NAME = 'gemini-1.5-pro-latest'

# --- CalDAV ---
CALDAV_URL = os.getenv("CALDAV_URL")
CALDAV_USERNAME = os.getenv("CALDAV_USERNAME")
CALDAV_PASSWORD = os.getenv("CALDAV_PASSWORD")

# --- CardDAV ---
CARDDAV_URL = os.getenv("CARDDAV_URL")
CARDDAV_USERNAME = os.getenv("CARDDAV_USERNAME")
CARDDAV_PASSWORD = os.getenv("CARDDAV_PASSWORD")

# --- Notifications & Bot Settings ---
TARGET_CHAT_ID_STR = os.getenv("TARGET_CHAT_ID")
ADMIN_CHAT_ID = None # *** 수정: 초기값을 None으로 설정

# TARGET_CHAT_ID를 정수로 변환하고, ADMIN_CHAT_ID에도 할당
if TARGET_CHAT_ID_STR and TARGET_CHAT_ID_STR.isdigit():
    TARGET_CHAT_ID = int(TARGET_CHAT_ID_STR)
    ADMIN_CHAT_ID = TARGET_CHAT_ID # *** 수정: TARGET_CHAT_ID 값을 ADMIN_CHAT_ID에도 할당
    logger.info(f"TARGET_CHAT_ID (관리자 ID) 로드 성공: {TARGET_CHAT_ID}")
else:
    logger.warning("WARNING: TARGET_CHAT_ID가 .env 파일에 설정되지 않았거나 숫자가 아닙니다. 알림 및 관리자 기능이 제한될 수 있습니다.")
    TARGET_CHAT_ID = None # *** 추가: 오류 시 None으로 명시적 설정

BOT_PASSWORD = os.getenv("BOT_PASSWORD")
MAX_PASSWORD_ATTEMPTS = 10
SCHEDULE_HOUR = 7
SCHEDULE_MINUTE = 0
TIMEZONE = os.getenv("TZ", "Asia/Seoul")

# --- Trusted Users ---
# .env 파일에서 TRUSTED_USER_IDS 읽기 (쉼표 구분 문자열)
TRUSTED_USER_IDS_STR = os.getenv("TRUSTED_USER_IDS", "") # 기본값 빈 문자열
# 문자열을 쉼표로 분리하고, 각 ID를 정수로 변환하여 리스트 생성
TRUSTED_USER_IDS = []
if TRUSTED_USER_IDS_STR:
    try:
        # 각 ID 앞뒤 공백 제거 후 정수로 변환
        TRUSTED_USER_IDS = [int(uid.strip()) for uid in TRUSTED_USER_IDS_STR.split(',') if uid.strip().isdigit()]
        logger.info(f"신뢰된 사용자 ID 목록 로드 성공: {TRUSTED_USER_IDS}")
    except ValueError as e:
        logger.error(f"TRUSTED_USER_IDS 환경 변수 값 오류 (숫자 아님): {TRUSTED_USER_IDS_STR} - {e}")
        TRUSTED_USER_IDS = [] # 오류 시 빈 리스트로 초기화
else:
    logger.info("TRUSTED_USER_IDS 환경 변수가 설정되지 않았거나 비어 있습니다.")

# --- Database ---
DB_FILE = os.path.join("data", "notifications.db") # ./data 폴더 안에 저장되도록 수정 (볼륨 마운트 고려)

# --- 필수 환경 변수 체크 ---
if not TELEGRAM_BOT_TOKEN: logger.critical("CRITICAL: TELEGRAM_BOT_TOKEN is not set!")
if not GOOGLE_API_KEY: logger.warning("WARNING: GOOGLE_API_KEY is not set. AI features will be disabled.")
if not (CALDAV_URL and CALDAV_USERNAME and CALDAV_PASSWORD): logger.warning("WARNING: CalDAV environment variables are not fully set.")
if not (CARDDAV_URL and CARDDAV_USERNAME and CARDDAV_PASSWORD): logger.warning("WARNING: CardDAV environment variables are not fully set.")
# *** 수정: TARGET_CHAT_ID가 None인지 확인 (정수로 변환 후 체크)
if TARGET_CHAT_ID is None: logger.warning("WARNING: TARGET_CHAT_ID is not set or invalid. Notification features will be disabled.")
if not BOT_PASSWORD: logger.warning("WARNING: BOT_PASSWORD is not set. Authentication might not work as expected.")

# --- End of File ---