# database.py
"""
알림 기록용 SQLite 데이터베이스 처리 함수 모듈 (음력 알림 지원 수정)
"""
import sqlite3
import logging
import config # 설정값 가져오기
from datetime import datetime # 기본값 설정을 위해
import os  # <--- 이 라인을 추가하세요!

logger = logging.getLogger(__name__)

# 설정 파일에서 DB 파일 경로 가져오기 (전역 변수 사용 시)
DATABASE_FILE = config.DB_FILE

# ----- 테이블 스키마 정의 추가 -----
# !!!!! 추가: sent_notifications 테이블 스키마 정의 !!!!!
SENT_NOTIFICATIONS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_notifications (
    event_uid TEXT NOT NULL,
    target_date_str TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (event_uid, target_date_str, notification_type)
)
"""
# -----------------------------------------------

BANNED_USERS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    banned_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""
# ======[ Permit List 테이블 스키마 추가 ]======
PERMITTED_USERS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS permitted_users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    permitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""
# ==========================================


# ----- 데이터베이스 및 테이블 초기화 (수정됨: permitted_users 추가) -----
def init_db():
    """데이터베이스 및 테이블 초기화/확인 (sent_notifications, banned_users, permitted_users)"""
    conn = None
    try:
        # 데이터베이스 파일 폴더 생성 (없으면) - Docker 환경 고려
        db_dir = os.path.dirname(DATABASE_FILE)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"데이터베이스 디렉토리 생성: {db_dir}")

        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # sent_notifications 테이블 처리
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sent_notifications'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(sent_notifications)")
            columns = [col[1].lower() for col in cursor.fetchall()]
            if 'event_uid' not in columns or 'target_date_str' not in columns or 'notification_type' not in columns:
                logger.warning("sent_notifications 테이블 구조 변경 감지, 재생성 (데이터 손실!)")
                cursor.execute("DROP TABLE IF EXISTS sent_notifications")
                cursor.execute(SENT_NOTIFICATIONS_TABLE_SCHEMA)
        else:
            cursor.execute(SENT_NOTIFICATIONS_TABLE_SCHEMA)
            logger.info("sent_notifications 테이블 생성 완료.")

        # banned_users 테이블 처리
        cursor.execute(BANNED_USERS_TABLE_SCHEMA)
        logger.info("banned_users 테이블 초기화/확인 완료.")

        # ======[ permitted_users 테이블 생성/확인 추가 ]======
        cursor.execute(PERMITTED_USERS_TABLE_SCHEMA)
        logger.info("permitted_users 테이블 초기화/확인 완료.")
        # ==============================================

        conn.commit()
        # ======[ 로그 메시지 수정 ]======
        logger.info("알림 기록, 차단 목록, 허용 목록 데이터베이스 초기화/확인 완료.")
        # ============================
    except sqlite3.Error as e:
        logger.error(f"데이터베이스 초기화 실패: {e}", exc_info=True)
        if conn:
            try: conn.rollback()
            except: pass
    finally:
        if conn:
            conn.close()


# ----- 알림 발송 여부 확인 함수 (수정됨) -----
def has_notification_been_sent(event_uid: str, target_date_str: str, notification_type: str) -> bool:
    """특정 이벤트의 특정 대상 날짜, 특정 유형의 알림이 이미 보내졌는지 확인"""
    conn = None
    found = False # 기본값 False
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        # SQL 쿼리에서 컬럼명 변경 (target_date_str 사용)
        cursor.execute("""
        SELECT 1 FROM sent_notifications
        WHERE event_uid = ? AND target_date_str = ? AND notification_type = ?
        """, (event_uid, target_date_str, notification_type))
        result = cursor.fetchone()
        found = result is not None # 결과가 있으면 True
        # logger.debug(f"Check sent: UID={event_uid}, Date={target_date_str}, Type={notification_type}, Found={found}")
    except sqlite3.Error as e:
        # 오류 발생 시 False 반환 (안 보낸 것으로 간주)
        logger.error(f"알림 기록 확인 실패: {e}", exc_info=True)
        found = False
    finally:
        if conn:
            conn.close()
    return found

# ----- 알림 발송 기록 저장 함수 (수정됨) -----
def record_notification_sent(event_uid: str, target_date_str: str, notification_type: str):
    """알림 발송 기록 저장 (변경된 컬럼명 사용)"""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        # sent_at 은 기본값(CURRENT_TIMESTAMP) 사용, 컬럼명 변경 반영
        cursor.execute("""
        INSERT OR IGNORE INTO sent_notifications (event_uid, target_date_str, notification_type)
        VALUES (?, ?, ?)
        """, (event_uid, target_date_str, notification_type))
        conn.commit()

        # 변경된 행 수 확인 (실제 INSERT 성공 여부)
        # Note: conn.total_changes는 마지막 commit 이후 총 변경 수이므로,
        # cursor.rowcount를 사용하는 것이 INSERT OR IGNORE의 성공 여부 판단에 더 적합할 수 있음.
        # 단, cursor.rowcount는 모든 DB 드라이버에서 동일하게 동작하지 않을 수 있음.
        # 여기서는 conn.total_changes로 확인 (이전 상태 대비 변화 여부)
        # 또는 INSERT 후 SELECT로 확인하는 방법도 있음.
        # 여기서는 단순화하여, IGNORE 되었을 가능성을 염두에 두고 로깅
        logger.debug(f"알림 기록 시도: UID={event_uid}, Date={target_date_str}, Type={notification_type} (IGNORE 가능)")

    except sqlite3.Error as e:
        logger.error(f"알림 기록 저장 실패: {e}", exc_info=True)
        if conn:
            try: conn.rollback()
            except: pass
    finally:
        if conn:
            conn.close()

# ======[ 허용 목록 확인 함수 추가 ]======
def is_user_permitted(user_id: int) -> bool:
    """사용자가 허용 목록 DB에 있는지 확인합니다."""
    conn = None
    permitted = False
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM permitted_users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        permitted = result is not None # 결과가 있으면 True
    except sqlite3.Error as e:
        logger.error(f"허용 목록 확인 실패 (User ID: {user_id}): {e}", exc_info=True)
        permitted = False # 오류 시 허용되지 않은 것으로 간주
    finally:
        if conn:
            conn.close()
    logger.debug(f"Permit check for user {user_id}: {permitted}")
    return permitted
# ====================================

# ======[ 허용 목록 추가 함수 추가 ]======
def add_permitted_user(user_id: int):
    """사용자를 허용 목록 DB에 추가합니다 (이미 있으면 무시)."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        # INSERT OR IGNORE 사용: 이미 존재하면 오류 없이 넘어감
        cursor.execute("INSERT OR IGNORE INTO permitted_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        # conn.total_changes > 0 으로 실제 추가되었는지 확인 가능
        if conn.total_changes > 0:
             logger.info(f"User ID {user_id} added to the permit list.")
        else:
             logger.debug(f"User ID {user_id} already exists in the permit list or DB error.")
    except sqlite3.Error as e:
        logger.error(f"허용 목록 추가 실패 (User ID: {user_id}): {e}", exc_info=True)
        if conn:
            try: conn.rollback()
            except: pass
    finally:
        if conn:
            conn.close()
# ====================================

# !!!!! 사용자 차단 함수 추가 !!!!!
def ban_user(user_id: int):
    """사용자를 차단 목록에 추가합니다."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        if conn.total_changes > 0:
             logger.warning(f"User ID {user_id} has been added to the ban list.")
        else:
             logger.debug(f"User ID {user_id} is already in the ban list.")
    except sqlite3.Error as e:
        logger.error(f"Failed to ban user ID {user_id}: {e}", exc_info=True)
        if conn:
            try: conn.rollback()
            except: pass
    finally:
        if conn:
            conn.close()         

# !!!!! 사용자 차단 여부 확인 함수 추가 !!!!!
def is_user_banned(user_id: int) -> bool:
    """사용자가 차단 목록에 있는지 확인합니다."""
    conn = None
    banned = False
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        banned = result is not None
    except sqlite3.Error as e:
        logger.error(f"Failed to check ban status for user ID {user_id}: {e}", exc_info=True)
        # 오류 발생 시 안전하게 차단된 것으로 간주할 수도 있으나, 여기서는 False 반환
        banned = False
    finally:
        if conn:
            conn.close()
    # logger.debug(f"Ban check for user {user_id}: {banned}") # 디버깅 시
    return banned

# !!!!! 사용자 차단 해제 함수 추가 !!!!!
def unban_user_db(user_id: int) -> bool:
    """
    사용자를 차단 목록에서 제거합니다.
    성공적으로 제거했거나 원래 없었으면 True, 오류 발생 시 False를 반환합니다.
    """
    conn = None
    success = False # 기본값 False
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        # DELETE 쿼리 실행
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        conn.commit()

        # 변경된 행 수 확인 (실제로 삭제되었는지 확인)
        if conn.total_changes > 0:
             logger.warning(f"User ID {user_id} has been removed from the ban list.")
             success = True
        else:
             logger.info(f"User ID {user_id} was not found in the ban list (or already removed).")
             success = True # 사용자가 목록에 없어도 "성공"으로 간주 (목표 달성)

    except sqlite3.Error as e:
        logger.error(f"Failed to unban user ID {user_id} from database: {e}", exc_info=True)
        success = False # 오류 발생 시 False
        if conn:
            try: conn.rollback() # 오류 시 롤백 시도
            except: pass
    finally:
        if conn:
            conn.close()
    return success

# --- 사용자 차단 관련 함수 ---

def get_banned_users() -> list[int]:
    """차단된 모든 사용자의 ID 리스트를 반환합니다."""
    query = "SELECT user_id FROM banned_users ORDER BY user_id;"
    conn = None  # ***** 수정: conn 변수 초기화 *****
    results = [] # ***** 수정: 결과를 담을 빈 리스트 초기화 *****
    try:
        # ***** 수정: sqlite3.connect 직접 사용 *****
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        # ---------------------------------------
        cursor.execute(query)
        # fetchall()은 튜플의 리스트를 반환하므로 각 튜플의 첫 번째 요소(ID)만 추출
        results = [row[0] for row in cursor.fetchall()]
        logger.info(f"차단된 사용자 목록 조회: {len(results)} 명")
        # ***** 수정: return 위치를 finally 밖으로 이동 *****
        # return results
    except sqlite3.Error as e:
        logger.error(f"차단된 사용자 목록 조회 중 오류: {e}", exc_info=True) # ***** 수정: 오류 로그에 exc_info 추가 *****
        results = [] # 오류 시 빈 리스트 반환
    finally: # ***** 수정: finally 블록 추가하여 연결 닫기 *****
        if conn:
            conn.close()
    return results # ***** 수정: 함수 마지막에서 결과 반환 *****   

# database.py 파일 내

# ======[ 허용 목록 조회 함수 추가 ]======
def get_permitted_users() -> list[int]:
    """허용 목록 DB에 있는 모든 사용자의 ID 리스트를 반환합니다."""
    query = "SELECT user_id FROM permitted_users ORDER BY permitted_at DESC;" # 최근 허용된 순서로 정렬 (선택 사항)
    conn = None
    results = []
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute(query)
        # fetchall()은 튜플의 리스트를 반환하므로 각 튜플의 첫 번째 요소(ID)만 추출
        results = [row[0] for row in cursor.fetchall()]
        logger.info(f"허용된 사용자 목록 조회: {len(results)} 명")
    except sqlite3.Error as e:
        logger.error(f"허용된 사용자 목록 조회 중 오류: {e}", exc_info=True)
        results = [] # 오류 시 빈 리스트 반환
    finally:
        if conn:
            conn.close()
    return results
# ====================================

# --- End of File ---