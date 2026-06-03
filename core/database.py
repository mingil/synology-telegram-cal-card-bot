import sqlite3
import logging
from typing import List
from contextlib import contextmanager

from . import config

logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """안전한 DB 커넥션 관리를 위한 컨텍스트 매니저 (WAL 모드 적용)"""
    # timeout=10.0: 다중 접속 시 DB Lock 에러 방지용 대기 시간
    # check_same_thread=False: 비동기 텔레그램 환경 필수 속성
    conn = sqlite3.connect(config.DB_FILE, timeout=10.0, check_same_thread=False)
    try:
        # 시놀로지 환경 I/O 최적화 및 동시성 문제 해결을 위한 설정
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        yield conn
    finally:
        conn.close()

def init_db():
    """DB 테이블 초기화"""
    try:
        with get_db_connection() as conn:
            with conn: # 에러가 없으면 트랜잭션 자동 commit
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sent_notifications (
                        event_uid TEXT NOT NULL,
                        target_date_str TEXT NOT NULL,
                        notification_type TEXT NOT NULL,
                        sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (event_uid, target_date_str, notification_type)
                    );
                    CREATE TABLE IF NOT EXISTS banned_users (
                        user_id INTEGER PRIMARY KEY NOT NULL,
                        banned_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS permitted_users (
                        user_id INTEGER PRIMARY KEY NOT NULL,
                        permitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)
        logger.info(f"✅ DB 초기화 및 WAL 모드 활성화 완료: {config.DB_FILE}")
    except Exception as e:
        logger.error(f"❌ DB 초기화 실패: {e}")

# --- 사용자 관리 함수들 ---
def is_user_banned(user_id: int) -> bool:
    with get_db_connection() as conn:
        return conn.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)).fetchone() is not None

def ban_user(user_id: int):
    with get_db_connection() as conn:
        with conn:
            conn.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
    logger.warning(f"🚫 사용자 차단됨: {user_id}")

def unban_user_db(user_id: int) -> bool:
    with get_db_connection() as conn:
        with conn:
            cursor = conn.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0

def get_banned_users() -> List[int]:
    with get_db_connection() as conn:
        return [row[0] for row in conn.execute("SELECT user_id FROM banned_users").fetchall()]

def is_user_permitted(user_id: int) -> bool:
    with get_db_connection() as conn:
        return conn.execute("SELECT 1 FROM permitted_users WHERE user_id = ?", (user_id,)).fetchone() is not None

def add_permitted_user(user_id: int):
    with get_db_connection() as conn:
        with conn:
            conn.execute("INSERT OR IGNORE INTO permitted_users (user_id) VALUES (?)", (user_id,))

def get_permitted_users() -> List[int]:
    with get_db_connection() as conn:
        return [row[0] for row in conn.execute("SELECT user_id FROM permitted_users").fetchall()]

def revoke_permission(user_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            with conn:
                cursor = conn.execute("DELETE FROM permitted_users WHERE user_id = ?", (user_id,))
                return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"❌ 허용 취소 실패: {e}")
        return False

# --- 알림 기록 함수들 ---
def mark_notification_sent(event_uid: str, target_date: str, noti_type: str):
    try:
        with get_db_connection() as conn:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO sent_notifications (event_uid, target_date_str, notification_type) VALUES (?, ?, ?)",
                    (event_uid, target_date, noti_type)
                )
    except Exception as e:
        logger.error(f"❌ DB 알림 기록 실패: {e}")

def is_notification_sent(event_uid: str, target_date: str, noti_type: str) -> bool:
    with get_db_connection() as conn:
        query = "SELECT 1 FROM sent_notifications WHERE event_uid=? AND target_date_str=? AND notification_type=?"
        return conn.execute(query, (event_uid, target_date, noti_type)).fetchone() is not None
