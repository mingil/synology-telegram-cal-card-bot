# core/database.py
import sqlite3
import logging
from datetime import datetime
from typing import List, Optional

# 같은 폴더(package) 내의 config 모듈 임포트
from . import config 

logger = logging.getLogger(__name__)

def init_db():
    """DB 테이블 초기화"""
    conn = None
    try:
        conn = sqlite3.connect(config.DB_FILE)
        cursor = conn.cursor()
        
        # 1. 알림 기록 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                event_uid TEXT NOT NULL,
                target_date_str TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_uid, target_date_str, notification_type)
            )
        """)
        
        # 2. 차단 유저 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY NOT NULL,
                banned_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. 허용 유저 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS permitted_users (
                user_id INTEGER PRIMARY KEY NOT NULL,
                permitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        logger.info(f"데이터베이스 초기화 완료: {config.DB_FILE}")
    except Exception as e:
        logger.error(f"DB 초기화 실패: {e}")
    finally:
        if conn: conn.close()

# --- 사용자 관리 함수들 ---

def is_user_banned(user_id: int) -> bool:
    """차단 여부 확인"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def ban_user(user_id: int):
    """사용자 차단"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        logger.warning(f"사용자 차단됨: {user_id}")
    finally:
        conn.close()

def unban_user_db(user_id: int) -> bool:
    """차단 해제"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        if cursor.rowcount > 0:
            conn.commit()
            return True
        return False
    finally:
        conn.close()

def get_banned_users() -> List[int]:
    """차단 목록 조회"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM banned_users")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def is_user_permitted(user_id: int) -> bool:
    """허용 목록 확인"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM permitted_users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_permitted_user(user_id: int):
    """허용 목록 추가"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO permitted_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
    finally:
        conn.close()

def get_permitted_users() -> List[int]:
    """허용 목록 조회"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM permitted_users")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

# core/database.py (하단에 추가)

def mark_notification_sent(event_uid: str, target_date: str, noti_type: str):
    """알림 발송 기록 저장"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO sent_notifications (event_uid, target_date_str, notification_type) VALUES (?, ?, ?)",
            (event_uid, target_date, noti_type)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"DB 기록 실패: {e}")
    finally:
        conn.close()

def is_notification_sent(event_uid: str, target_date: str, noti_type: str) -> bool:
    """이미 알림을 보냈는지 확인"""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM sent_notifications WHERE event_uid=? AND target_date_str=? AND notification_type=?",
        (event_uid, target_date, noti_type)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None