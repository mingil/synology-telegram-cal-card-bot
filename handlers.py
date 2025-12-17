# handlers.py
"""
텔레그램 명령어 핸들러 및 콜백 함수 모듈
"""
import functools # 데코레이터 작성을 위해 추가
import asyncio
import calendar
import logging
import html
import re # 정규식 사용
import os
from enum import IntEnum
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date, time, timedelta

# --- Telegram 라이브러리 임포트 ---
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberUpdated, # 봇 상태 변경 감지에 사용
    Chat # Chat 객체 타입 힌트 등에 사용 (예: chat.type)
)
from telegram.constants import (
    ChatAction,
    ParseMode,
    ChatMemberStatus, # 봇 상태 변경 감지에 사용
    ChatType # 채팅 타입 확인에 사용
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ChatMemberHandler # <<<--- 수정: ChatMemberUpdatedHandler 대신 사용
)
from telegram.error import Forbidden, BadRequest

# --- 로컬 모듈 임포트 ---
import config
import database
import helpers

logger = logging.getLogger(__name__)

# ======================================
#  인증 및 차단 확인 데코레이터
# ======================================

def check_ban(func):
    """사용자가 차단되었는지 확인하는 데코레이터"""
    @functools.wraps(func) # 원본 함수의 메타데이터 유지
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user: # 사용자를 특정할 수 없는 업데이트는 그냥 통과 (혹은 에러 처리)
            logger.warning("데코레이터 @check_ban: effective_user를 찾을 수 없음.")
            return await func(update, context, *args, **kwargs)

        user_id = user.id
        if database.is_user_banned(user_id):
            logger.warning(f"차단된 사용자 접근 시도: {user.first_name} (ID: {user_id}) - Handler: {func.__name__}")
            # 콜백 쿼리인지 메시지인지 확인하여 적절히 응답
            query = update.callback_query
            if query:
                try:
                    await query.answer("🚫 접근이 차단되었습니다.", show_alert=True)
                except Exception as e:
                    logger.error(f"차단된 사용자 콜백 응답 실패: {e}")
            else:
                # 메시지가 있는 경우에만 답장 시도
                if update.message:
                    try:
                         await update.message.reply_text("🚫 접근이 차단된 사용자입니다.")
                    except Exception as e:
                        logger.error(f"차단된 사용자 메시지 전송 실패: {e}")
            # 대화 핸들러 내부에서 사용될 수 있으므로 END 반환하여 중단
            return ConversationHandler.END
        # 차단되지 않았으면 원래 함수 실행
        return await func(update, context, *args, **kwargs)
    return wrapper

def require_auth(func):
    """사용자가 인증되었는지 확인하는 데코레이터 (신뢰된 사용자는 통과)"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            logger.warning("데코레이터 @require_auth: effective_user를 찾을 수 없음.")
            return await func(update, context, *args, **kwargs)

        user_id = user.id
        # 신뢰된 사용자는 인증된 것으로 간주
        is_trusted = user_id in config.TRUSTED_USER_IDS
        is_authenticated = context.user_data.get('authenticated', False)

        if not is_authenticated and not is_trusted:
            logger.info(f"인증되지 않은 사용자 접근 시도: {user.first_name} (ID: {user_id}) - Handler: {func.__name__}")
            query = update.callback_query
            if query:
                try:
                    # 콜백에는 간단히 알림 표시 후 채팅 메시지 전송
                    await query.answer("🔒 먼저 /start 인증 필요", show_alert=False)
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="🔒 먼저 /start 명령어를 통해 인증해주세요."
                    )
                except Exception as e:
                    logger.error(f"인증 필요 콜백 응답/메시지 실패: {e}")
            else:
                if update.message:
                    try:
                        await update.message.reply_text("🔒 먼저 /start 명령어를 통해 인증해주세요.")
                    except Exception as e:
                        logger.error(f"인증 필요 메시지 전송 실패: {e}")
            return ConversationHandler.END
        # 인증되었거나 신뢰된 사용자면 원래 함수 실행
        # 이미 인증된 경우 추가적인 메시지 없이 바로 함수 실행
        return await func(update, context, *args, **kwargs)
    return wrapper

# ======[ @require_admin 데코레이터 추가 ]======
def require_admin(func):
    """관리자만 함수를 실행할 수 있도록 제한하는 데코레이터"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            logger.warning("데코레이터 @require_admin: effective_user를 찾을 수 없음.")
            return None # 또는 적절한 오류 처리

        user_id_str = str(user.id)
        admin_id_str = str(config.ADMIN_CHAT_ID) # config에서 가져온 ID도 문자열로

        if not admin_id_str:
            logger.error("ADMIN_CHAT_ID가 설정되지 않았습니다. 관리자 기능을 확인할 수 없습니다.")
            # 관리자에게만 오류 메시지를 보내는 것을 고려하거나, 그냥 무시
            # if update.message: await update.message.reply_text("봇 설정 오류: 관리자 ID가 지정되지 않음.")
            return None # 실행 중지

        if user_id_str == admin_id_str:
            # 관리자가 맞으면 원래 함수 실행
            logger.debug(f"관리자(ID: {user_id_str})가 '{func.__name__}' 실행 시도.")
            return await func(update, context, *args, **kwargs)
        else:
            # 관리자가 아니면 경고 로그만 남기고 아무런 응답 없이 종료 (보안상 권장)
            logger.warning(f"관리자 아님(ID: {user_id_str})이 관리자 명령어 '{func.__name__}' 실행 시도.")
            # 필요시 사용자에게 권한 없음 메시지 전송 가능
            # if update.message: await update.message.reply_text("이 명령어를 사용할 권한이 없습니다.")
            return None # 실행 중지
    return wrapper
# ============================================
# ======================================
#  핸들러 함수 정의 시작
# ======================================  

# ======================================대화 상태 정의 시작======================================
# ... (기존 상태 정의 코드 - 변경 없음) ...
class DeleteContactStates(IntEnum):
    WAITING_TARGET = 1
    CONFIRM_DELETION = 2

class DateInputStates(IntEnum):
    WAITING_DATE = 1

class FindContactStates(IntEnum):
    WAITING_NAME = 1

class AskAIStates(IntEnum):
    WAITING_QUESTION = 1

class AddContactStates(IntEnum):
    WAITING_NAME = 1
    WAITING_PHONE = 2
    WAITING_EMAIL = 3

class SearchContactStates(IntEnum):
    WAITING_KEYWORD = 1

# !!!!! 아래 클래스 정의가 정확히 있는지 확인하세요 !!!!!
class AuthStates(IntEnum):
    WAITING_PASSWORD = 1
# !!!!! AuthStates 정의 끝 !!!!!    

class SearchEventsStates(IntEnum):
    WAITING_KEYWORD = 1

class AddEventStates(IntEnum):
    SELECT_CALENDAR = 1 # 캘린더 선택
    WAITING_TITLE = 2   # 제목 입력 대기
    WAITING_START = 3   # 시작 날짜/시간 입력 대기
    WAITING_END_OR_ALLDAY = 4 # 종료 날짜/시간 또는 종일 여부 입력 대기    

# ======[ Unban 대화 상태 추가 ]======
class UnbanStates(IntEnum):
    WAITING_TARGET_ID = 1

# ======[ 이벤트 삭제 대화 상태 추가 ]======
class DeleteEventStates(IntEnum):
    SELECT_METHOD = 1      # 삭제 방법 선택 (최근/검색)
    WAITING_KEYWORD = 2    # 검색 키워드 입력 대기
    SELECT_EVENT = 3       # 삭제할 이벤트 선택
    CONFIRM_DELETION = 4   # 최종 삭제 확인
# ======================================
#=================================대화상태 정의 끝===============================================

# ====================================== 대화 데이터 키 및 정리 함수 ======================================
# ... (기존 CONVERSATION_USER_DATA_KEYS 및 _clear_other_conversations 함수 - 변경 없음) ...
CONVERSATION_USER_DATA_KEYS = ['new_contact', 'contact_to_delete', 'password_attempts']
CONVERSATION_USER_DATA_KEYS = [
    'new_contact',
    'contact_to_delete',
    'password_attempts',
    'new_event_details' # <--- 이 줄 추가
]
# ==================================== 대화 데이터 키 및 정리 함수끝 ======================================

# ======[ 추가: 메인 인라인 키보드 생성 함수 ]======
def _get_main_inline_keyboard() -> InlineKeyboardMarkup:
    """시작 시 보여줄 메인 인라인 키보드를 생성하여 반환합니다."""
    keyboard = [
        # 1행: 주요 조회 기능
        [InlineKeyboardButton("📆 이번 달 일정", callback_data="show_month"),
         InlineKeyboardButton("🔎 일정 검색", callback_data="search_events_prompt")],
        # 2행: 주요 추가/검색 기능
        [InlineKeyboardButton("➕ 일정 추가", callback_data="add_event_prompt"),
         InlineKeyboardButton("👤 연락처 검색", callback_data="find_contact_prompt")],
        # 3행: 전체 명령어 보기
        [InlineKeyboardButton("📋 전체 명령어 보기", callback_data="show_all_commands")]
    ]
    return InlineKeyboardMarkup(keyboard)
# ================================================

async def _clear_other_conversations(context: ContextTypes.DEFAULT_TYPE, current_keys_to_keep: List[str] = None) -> bool:
    # ... (기존 _clear_other_conversations 함수 - 변경 없음) ...
    if current_keys_to_keep is None:
        current_keys_to_keep = []
    was_cleared = False
    keys_to_remove = []
    for key in CONVERSATION_USER_DATA_KEYS:
        if key not in current_keys_to_keep and key in context.user_data:
            keys_to_remove.append(key)
    if keys_to_remove:
        logger.warning(f"새 대화 시작 전, 이전 대화 데이터 정리: {keys_to_remove}")
        for key in keys_to_remove:
            try: del context.user_data[key]
            except KeyError: pass
        was_cleared = True
    return was_cleared

# ======================================
#  관리자 기능 핸들러
# ======================================

@check_ban      # 1. 차단된 관리자는 사용 불가
@require_auth   # 2. 인증된 사용자여야 함
@require_admin  # 3. 관리자여야 함
async def banlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[Admin Only] 현재 차단된 사용자 ID 목록을 보여줍니다."""
    user = update.effective_user
    logger.info(f"Admin {user.first_name} (ID: {user.id}) requested ban list.")

    try:
        # database.py에 차단 목록을 가져오는 함수가 필요합니다. (아래에서 정의 가정)
        banned_users = await asyncio.to_thread(database.get_banned_users)

        if banned_users:
            response_html = "🚫 <b>차단된 사용자 목록</b> 🚫\n\n"
            # 사용자 ID 목록을 코드 블록으로 표시
            response_html += "<pre>"
            for user_id in banned_users:
                # user_id가 튜플의 첫 번째 요소일 수 있으므로 확인
                actual_id = user_id[0] if isinstance(user_id, tuple) else user_id
                response_html += f"{actual_id}\n"
            response_html += "</pre>\n\n"
            response_html += f"총 {len(banned_users)} 명의 사용자가 차단되었습니다.\n"
            response_html += "차단을 해제하려면 <code>/unban 사용자ID</code> 명령어를 사용하세요." # 대화형으로 변경 예정 알림
        else:
            response_html = "✅ 현재 차단된 사용자가 없습니다."

        await update.message.reply_html(response_html)

    except Exception as e:
        logger.error(f"Error fetching or sending ban list: {e}", exc_info=True)
        await update.message.reply_text("❌ 차단 목록을 가져오는 중 오류가 발생했습니다.")

# handlers.py 파일 내

# ======[ 허용 목록 조회 명령어 핸들러 추가 ]======
@check_ban      # 1. 차단된 관리자는 사용 불가
@require_auth   # 2. 인증된 사용자여야 함
@require_admin  # 3. 관리자여야 함
async def permitlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[Admin Only] 현재 허용 목록(DB)에 있는 사용자 ID 목록을 보여줍니다."""
    user = update.effective_user
    logger.info(f"Admin {user.first_name} (ID: {user.id}) requested permit list.")

    try:
        # database.py에 새로 추가한 함수 호출
        permitted_users = await asyncio.to_thread(database.get_permitted_users)

        if permitted_users:
            response_html = "✅ <b>허용된 사용자 목록 (DB)</b> ✅\n\n"
            response_html += "<pre>"
            for user_id in permitted_users:
                response_html += f"{user_id}\n"
            response_html += "</pre>\n\n"
            response_html += f"총 {len(permitted_users)} 명의 사용자가 허용 목록에 있습니다.\n"
            # 필요시 허용 목록 제거 명령어 안내 추가 가능
            # response_html += "허용 목록에서 제거하려면 `/unpermit 사용자ID` (구현 필요) ..."
        else:
            response_html = "ℹ️ 현재 허용 목록(DB)에 등록된 사용자가 없습니다.\n(Trusted User는 여기에 표시되지 않을 수 있습니다.)"

        await update.message.reply_html(response_html)

    except Exception as e:
        logger.error(f"Error fetching or sending permit list: {e}", exc_info=True)
        await update.message.reply_text("❌ 허용 목록을 가져오는 중 오류가 발생했습니다.")
# ===========================================

# ... (banlist_command 함수 등 나머지 코드는 유지) ...

# --- /start 명령어 처리 함수 (수정됨: 키보드 변경) ---
# handlers.py 파일 내

# handlers.py 파일 내

# ======[ 수정 후: start 함수 (Permit List + 새 사용자 알림 추가) ]======
@check_ban
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    user = update.effective_user
    if not user:
        logger.warning("start handler called without effective_user.")
        return ConversationHandler.END # 혹은 None

    user_id = user.id
    reply_markup = _get_main_inline_keyboard()

    # --- 1. DB에서 허용된 사용자인지 먼저 확인 ---
    is_permitted_db = await asyncio.to_thread(database.is_user_permitted, user_id)
    if is_permitted_db:
        logger.info(f"Permitted user {user.first_name} (ID: {user_id}) started. (from DB)")
        context.user_data['authenticated'] = True
        if 'password_attempts' in context.user_data:
            try: del context.user_data['password_attempts']
            except KeyError: pass
        welcome_message = f"✅ 다시 오셨군요! <b>{user.mention_html()}</b>님!\n(이전에 인증되었습니다)\n\n"
        welcome_message += "주요 기능을 아래 버튼으로 바로 사용하거나, 전체 명령어 목록을 확인하세요."
        try: await update.message.reply_html(welcome_message, reply_markup=reply_markup)
        except Exception as e: logger.error(f"Failed to send welcome message to permitted user {user_id}: {e}")
        return ConversationHandler.END

    # --- 2. DB에 없고, Trusted User 인지 확인 ---
    is_trusted = user_id in config.TRUSTED_USER_IDS
    if is_trusted:
        logger.info(f"Trusted user {user.first_name} (ID: {user_id}) started. Auto-authenticating and adding to permit list.")
        context.user_data['authenticated'] = True
        if 'password_attempts' in context.user_data:
            try: del context.user_data['password_attempts']
            except KeyError: pass
        await asyncio.to_thread(database.add_permitted_user, user_id)
        logger.info(f"Added trusted user {user_id} to permit list.")
        welcome_message = f"✅ 신뢰된 사용자 자동 인증! 👋 안녕하세요, <b>{user.mention_html()}</b>님!\n\n"
        welcome_message += "주요 기능을 아래 버튼으로 바로 사용하거나, 전체 명령어 목록을 확인하세요."
        try: await update.message.reply_html(welcome_message, reply_markup=reply_markup)
        except Exception as e: logger.error(f"Failed to send welcome message to trusted user {user_id}: {e}")
        return ConversationHandler.END

    # --- 3. DB에도 없고, Trusted User도 아닐 때: 현재 세션 인증 여부 확인 ---
    elif context.user_data.get('authenticated'):
        logger.info(f"Authenticated user {user.first_name} started (current session). Adding to permit list.")
        await asyncio.to_thread(database.add_permitted_user, user_id)
        welcome_message = f"👋 안녕하세요, <b>{user.mention_html()}</b>님! (현재 세션 인증됨)\n\n"
        welcome_message += "주요 기능을 아래 버튼으로 바로 사용하거나, 전체 명령어 목록을 확인하세요."
        try: await update.message.reply_html(welcome_message, reply_markup=reply_markup)
        except Exception as e: logger.error(f"Failed to send welcome message to session-authenticated user {user_id}: {e}")
        return ConversationHandler.END

    # --- 4. 위 모든 경우에 해당하지 않으면 새 사용자 + 비밀번호 요청 ---
    else:
        logger.info(f"New or unauthenticated user {user.first_name} (ID: {user_id}) started. Requesting password.")

        # ======[ 관리자에게 새 사용자 알림 전송 ]======
        admin_id = config.ADMIN_CHAT_ID
        if admin_id:
            try:
                admin_id_int = int(admin_id) # config에서 이미 int일 수 있음
                # 사용자 정보 포함하여 메시지 생성
                user_info = f"이름: {user.mention_html()}"
                if user.username:
                    user_info += f" (@{user.username})"
                user_info += f"\nID: <code>{user_id}</code>"

                admin_message = (f"🔔 <b>새 사용자 시작 알림</b> 🔔\n\n"
                                 f"{user_info}\n\n"
                                 f"비밀번호 입력을 요청했습니다.")
                await context.bot.send_message(chat_id=admin_id_int, text=admin_message, parse_mode=ParseMode.HTML)
                logger.info(f"New user notification sent to admin ({admin_id}) for user {user_id}.")
            except (ValueError, TypeError) as e:
                 logger.error(f"ADMIN_CHAT_ID ({admin_id}) is not a valid integer: {e}")
            except Forbidden:
                 logger.error(f"Bot is blocked by the admin ({admin_id}). Cannot send new user notification.")
            except Exception as e:
                 logger.error(f"Failed to send new user notification to admin ({admin_id}): {e}")
        else:
            logger.warning("ADMIN_CHAT_ID not set. Cannot send new user notification.")
        # ===========================================

        context.user_data['password_attempts'] = 0 # 비밀번호 시도 횟수 초기화
        try:
            await update.message.reply_text("🔒 봇 사용을 위해 설정된 비밀번호를 입력해주세요:")
        except Exception as e:
             logger.error(f"Failed to send password request message to user {user_id}: {e}")
             return ConversationHandler.END
        return AuthStates.WAITING_PASSWORD
# ========================================================================

# handlers.py 파일 내

# ======[ 수정 후: password_received 함수 (인증 성공 시 관리자 알림 추가) ]======
async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        logger.warning("password_received: Received update without user or message.")
        return ConversationHandler.END

    user_id = user.id
    entered_password = update.message.text
    try:
        max_attempts_str = config.MAX_PASSWORD_ATTEMPTS
        max_attempts = int(max_attempts_str) if max_attempts_str and max_attempts_str.isdigit() else 10
    except Exception as e:
        logger.error(f"Error reading or converting MAX_PASSWORD_ATTEMPTS from config: {e}. Using default 10.")
        max_attempts = 10

    if entered_password == config.BOT_PASSWORD:
        logger.info(f"User {user.first_name} (ID: {user_id}) entered correct password. Authenticated.")
        context.user_data['authenticated'] = True
        if 'password_attempts' in context.user_data:
            try: del context.user_data['password_attempts']
            except KeyError: pass

        logger.info(f"Adding user {user_id} to permit list after password auth.")
        await asyncio.to_thread(database.add_permitted_user, user_id)

        # ======[ 관리자에게 비밀번호 인증 성공 알림 추가 ]======
        admin_id = config.ADMIN_CHAT_ID
        if admin_id:
            try:
                admin_id_int = int(admin_id) # config 로직에 따라 이미 int일 수 있음
                # 사용자 정보 포함 메시지 생성
                user_info = f"이름: {user.mention_html()}"
                if user.username:
                    user_info += f" (@{user.username})"
                user_info += f"\nID: <code>{user_id}</code>"

                admin_message = (f"✅ <b>비밀번호 인증 성공 알림</b> ✅\n\n"
                                 f"{user_info}\n\n"
                                 f"사용자가 올바른 비밀번호를 입력하여 인증되었습니다.\n"
                                 f"(이제 허용 목록에 추가되어 다음부터 자동 인증됩니다.)")
                await context.bot.send_message(chat_id=admin_id_int, text=admin_message, parse_mode=ParseMode.HTML)
                logger.info(f"Password success notification sent to admin ({admin_id}) for user {user_id}.")
            except (ValueError, TypeError) as e:
                 logger.error(f"ADMIN_CHAT_ID ({admin_id}) is not a valid integer: {e}")
            except Forbidden:
                 logger.error(f"Bot is blocked by the admin ({admin_id}). Cannot send password success notification.")
            except Exception as e:
                 logger.error(f"Failed to send password success notification to admin ({admin_id}): {e}")
        else:
            logger.warning("ADMIN_CHAT_ID not set. Cannot send password success notification.")
        # ==================================================

        # 사용자에게 환영 메시지 전송
        welcome_message = f"✅ 비밀번호 인증 완료! 👋 안녕하세요, <b>{user.mention_html()}</b>님!\n\n"
        welcome_message += "주요 기능을 아래 버튼으로 바로 사용하거나, 전체 명령어 목록을 확인하세요."
        reply_markup = _get_main_inline_keyboard()

        try:
            await update.message.reply_html(welcome_message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to send welcome message after password auth to {user_id}: {e}")

        return ConversationHandler.END # 대화 종료

    else:
        # --- 비밀번호 오류 처리 (기존과 동일, 허용 목록 제거 로직은 여전히 주석 처리) ---
        attempts = context.user_data.get('password_attempts', 0) + 1
        context.user_data['password_attempts'] = attempts
        logger.warning(f"User {user.first_name} (ID: {user_id}) entered incorrect password. Attempt {attempts}/{max_attempts}.")

        if attempts >= max_attempts:
            logger.warning(f"User {user.first_name} (ID: {user_id}) exceeded max password attempts. Banning user.")
            try:
                await asyncio.to_thread(database.ban_user, user_id)
                # !!!!! 중요: 차단 시 허용 목록에서도 제거하는 로직 필요 !!!!!
                logger.warning(f"Need to implement removal from permit list for banned user {user_id}.")
                # ------------------------------------------
                await update.message.reply_text(f"🚫 비밀번호 오류 횟수 초과 ({attempts}/{max_attempts}). 보안을 위해 접근이 차단되었습니다. 관리자에게 문의하세요.")
            except Exception as e:
                 logger.error(f"Failed to ban user {user_id} or send ban message: {e}")
                 await update.message.reply_text("🚫 비밀번호 오류 횟수 초과. 사용자 차단 중 오류 발생.")
            # 관리자 알림
            admin_id = config.ADMIN_CHAT_ID
            if admin_id:
                 try:
                     admin_id_int = int(admin_id)
                     admin_message = (f"🚨 <b>사용자 차단 알림</b> 🚨\n\n"
                                      f"사용자: {user.mention_html()} (ID: <code>{user_id}</code>)\n"
                                      f"사유: 비밀번호 오류 횟수 초과 ({attempts}회 시도)\n"
                                      f"조치: 해당 사용자 차단됨 (/banlist 확인)")
                     await context.bot.send_message(chat_id=admin_id_int, text=admin_message, parse_mode=ParseMode.HTML)
                     logger.info(f"Ban notification sent to admin ({admin_id}).")
                 except (ValueError, TypeError) as e: logger.error(f"ADMIN_CHAT_ID ({admin_id}) is not a valid integer: {e}")
                 except Forbidden: logger.error(f"Bot is blocked by the admin ({admin_id}).")
                 except Exception as e: logger.error(f"Failed to send ban notification to admin ({admin_id}): {e}")
            else: logger.warning("ADMIN_CHAT_ID not set. Cannot send ban notification.")

            if 'password_attempts' in context.user_data:
                try: del context.user_data['password_attempts']
                except KeyError: pass
            return ConversationHandler.END
        else:
            remaining_attempts = max_attempts - attempts
            try:
                await update.message.reply_text(f"❌ 비밀번호가 틀렸습니다. (시도: {attempts}/{max_attempts})\n남은 기회: {remaining_attempts}번\n\n다시 입력하거나 /cancel 로 취소하세요.")
            except Exception as e:
                logger.error(f"Failed to send incorrect password message to user {user_id}: {e}")
            return AuthStates.WAITING_PASSWORD
        # ------------------------------------
# ========================================================================

# ======[ 수정 후: button_callback_handler 함수 (직접 CalDAV 조회 및 포맷팅) ]======
@check_ban
@require_auth
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        logger.warning("button_callback_handler received update without query or message.")
        return # 처리할 대상 없음

    callback_data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    user_name = query.from_user.first_name

    logger.info(f"Button clicked: {callback_data} by {user_name} (ID: {user_id})")

    # !!!!! 키보드는 항상 유지되도록 미리 정의 !!!!!
    reply_markup = _get_main_inline_keyboard()

    try:
        await query.answer() # 버튼 로딩 표시 빠르게 제거
    except BadRequest as e:
        logger.warning(f"Failed to answer callback query (maybe expired or answered): {e}")
        # 응답 실패해도 계속 진행 시도
    except Exception as e:
        logger.error(f"Failed to answer callback query: {e}")
        return # 치명적 오류 시 종료

    # --- 변수 초기화 ---
    initial_edit_text = ""  # "확인 중..." 메시지
    final_text = ""         # 최종 결과 HTML
    fetch_events = False    # CalDAV 조회 필요한지 여부
    start_dt = None         # 조회 시작 시간
    end_dt = None           # 조회 종료 시간
    period_str = ""         # 기간 표시 문자열

    try:
        # --- 1. 콜백 데이터에 따라 작업 결정 ---
        if callback_data == "show_today":
            fetch_events = True
            today = date.today()
            start_dt = datetime.combine(today, time.min)
            end_dt = datetime.combine(today, time.max)
            period_str = f"오늘 ({today.strftime('%Y-%m-%d')})"
            initial_edit_text = f"🗓️ {period_str} 일정 확인 중..."

        elif callback_data == "show_week":
            fetch_events = True
            today = date.today()
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            start_dt = datetime.combine(start_of_week, time.min)
            end_dt = datetime.combine(end_of_week, time.max)
            period_str = f"이번 주 ({start_of_week.strftime('%m/%d')} ~ {end_of_week.strftime('%m/%d')})"
            initial_edit_text = f"📅 {period_str} 일정 확인 중..."

        elif callback_data == "show_month":
            fetch_events = True
            today = date.today()
            first_day_of_month = today.replace(day=1)
            _, last_day_num = calendar.monthrange(today.year, today.month)
            last_day_of_month = today.replace(day=last_day_num)
            start_dt = datetime.combine(first_day_of_month, time.min)
            end_dt = datetime.combine(last_day_of_month, time.max)
            period_str = f"이번 달 ({today.strftime('%Y년 %m월')})"
            initial_edit_text = f"📆 {period_str} 일정 확인 중..."

        elif callback_data == "search_events_prompt":
            final_text = "일정을 검색하려면 /search_events 명령어를 입력해주세요."

        elif callback_data == "add_event_prompt":
            final_text = "새 일정을 추가하려면 /addevent 명령어를 입력해주세요."

        elif callback_data == "find_contact_prompt":
             # final_text = "연락처를 검색하려면 /findcontact 또는 /searchcontact 명령어를 입력해주세요."
             # 바로 검색 시작하도록 변경 (searchcontact_start 호출)
             logger.info(f"Triggering /searchcontact from button for user {user_name}")
             await query.edit_message_text("🔎 연락처 키워드 검색을 시작합니다...") # 임시 메시지
             # searchcontact_start 함수를 직접 호출하여 대화 시작
             return await searchcontact_start(update, context) # 여기서 함수 종료하고 대화 시작

        elif callback_data == "show_all_commands":
            final_text = helpers.get_command_list_message(user_id) # HTML 형식
            # 이 경우는 CalDAV 조회가 필요 없으므로 바로 최종 메시지 수정

        else:
            logger.warning(f"Received unknown callback_data: {callback_data}")
            final_text = "알 수 없는 버튼입니다."

        # --- 2. "확인 중..." 메시지 수정 (CalDAV 조회 필요시) ---
        if initial_edit_text:
            try:
                await context.bot.edit_message_text(
                    text=initial_edit_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup # 키보드 유지
                )
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except BadRequest as e:
                logger.warning(f"Failed to edit initial message for {callback_data} (BadRequest): {e}")
                try: await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except Exception: pass
            except Exception as e:
                logger.error(f"Error editing initial message for {callback_data}: {e}")
                try: await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except Exception: pass

        # --- 3. CalDAV 이벤트 조회 수행 (필요시) ---
        if fetch_events:
            if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
                final_text = "캘린더(CalDAV) 설정이 필요합니다."
            elif start_dt is None or end_dt is None:
                final_text = "오류: 조회 기간 설정 실패."
                logger.error(f"Date range calculation failed for callback: {callback_data}")
            else:
                success, result_or_error = await asyncio.to_thread(
                    helpers.fetch_caldav_events, start_dt, end_dt, config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD
                )

                if success:
                    events_details = result_or_error
                    if events_details:
                        # ===== 이벤트 포맷팅 로직 (show_week/month와 동일하게) =====
                        response_html = f"🗓️ <b>{period_str}</b> 일정입니다.\n" # 아이콘은 상황에 맞게 변경 가능
                        events_by_date: Dict[str, List[Dict[str, Any]]] = {}
                        for event in events_details:
                            event_date_str = "Unknown Date"; start_str = event.get('start_str')
                            if start_str:
                                try:
                                    event_date = datetime.strptime(start_str.split()[0], '%Y-%m-%d').date()
                                    event_date_str = event_date.strftime('%Y-%m-%d (%a)')
                                except (ValueError, IndexError): event_date_str = start_str.split()[0] if start_str else "날짜 정보 없음"
                            else: event_date_str = "날짜 정보 없음"
                            if event_date_str not in events_by_date: events_by_date[event_date_str] = []
                            events_by_date[event_date_str].append(event)

                        for event_date_str in sorted(events_by_date.keys()):
                            response_html += f"\n<b>{event_date_str}</b>\n"
                            for event in events_by_date[event_date_str]:
                                summary = event.get('summary', '제목 없음'); is_allday = event.get('is_allday', False)
                                start_str_ev = event.get('start_str'); end_str_ev = event.get('end_str')
                                start_time_str = event.get('start_time_str'); end_time_str = event.get('end_time_str')
                                response_html += f"  • <b>{html.escape(summary)}</b>"
                                if is_allday:
                                    response_html += " (종일) ☀️"
                                    start_date_part = start_str_ev.split()[0] if start_str_ev else ""
                                    end_date_part = ""
                                    if end_str_ev:
                                        try:
                                            end_date_obj = datetime.strptime(end_str_ev.split()[0], '%Y-%m-%d').date() - timedelta(days=1)
                                            end_date_part = end_date_obj.strftime('%Y-%m-%d')
                                        except (ValueError, IndexError): end_date_part = end_str_ev.split()[0] if end_str_ev else ""
                                    if end_date_part and start_date_part and end_date_part != start_date_part:
                                         response_html += f"\n    <pre>  기간: {html.escape(start_date_part)} ~ {html.escape(end_date_part)}</pre>"
                                else:
                                    response_html += " ✨"
                                    time_info = start_time_str if start_time_str else ''
                                    if end_time_str and end_time_str != start_time_str: time_info += f" ~ {end_time_str}"
                                    if time_info: response_html += f"\n    <pre>  ⏰ {html.escape(time_info)}</pre>"
                                response_html += "\n"
                        # =======================================================
                        final_text = response_html
                    else: # 이벤트 없음
                        final_text = f"✅ {period_str}에는 예정된 일정이 없습니다."
                else: # 조회 실패
                    logger.error(f"CalDAV fetch failed for {callback_data}. Original error: {result_or_error}")
                    final_text = f"죄송합니다, {period_str} 일정을 가져오는 중 문제가 발생했어요. 😥"

                # 메시지 길이 제한
                if len(final_text.encode('utf-8')) > 4096:
                    final_text = final_text[:4000] + "...\n\n(일정이 너무 많아 일부만 표시합니다.)"

        # --- 4. 최종 결과 메시지로 수정 ---
        if final_text:
            try:
                 await context.bot.edit_message_text(
                     text=final_text,
                     chat_id=chat_id,
                     message_id=message_id,
                     reply_markup=reply_markup, # 키보드 유지
                     parse_mode=ParseMode.HTML, # HTML 파싱 사용
                     disable_web_page_preview=True
                 )
            except BadRequest as e:
                  logger.warning(f"Final edit failed for {callback_data} (BadRequest): {e}. Maybe content identical or msg expired.")
            except Exception as e:
                  logger.error(f"Error editing final message for {callback_data}: {e}")

    # 핸들러 전체의 예외 처리
    except Exception as handler_err:
        logger.error(f"Error processing callback data '{callback_data}': {handler_err}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                 text="요청 처리 중 오류가 발생했습니다.",
                 chat_id=chat_id,
                 message_id=message_id,
                 reply_markup=None # 오류 시 키보드 제거
            )
        except Exception as send_err:
            logger.error(f"Failed to send error message for callback '{callback_data}': {send_err}")
# ============================================================================

# --- CalDAV 명령어 핸들러 ---
# ... (기존 show_today_events, show_week_events, show_month_events - ChatAction 추가는 선택사항이므로 일단 유지) ...
# ======[ 수정: show_today_events 함수 (문자열 반환) ]======
# ======[ 수정 후: show_today_events 함수 (직접 메시지 전송) ]======
@check_ban
@require_auth
async def show_today_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # 반환 타입 None으로 변경
    """[명령어 핸들러] 오늘의 캘린더 일정을 조회하고 사용자에게 메시지를 보냅니다."""
    if not update.message: # CommandHandler로 호출되었는지 확인 (message 객체 필요)
        logger.warning("show_today_events called without update.message (likely from callback). Ignoring direct send.")
        # 콜백 핸들러에서 호출된 경우, 메시지 전송 없이 반환값만 필요한 경우가 있을 수 있으나,
        # 현재 button_callback_handler 구조에서는 이 함수를 직접 호출하지 않으므로,
        # 여기서는 CommandHandler로 직접 호출된 경우만 처리하도록 가정합니다.
        # 만약 콜백에서도 이 함수를 재사용하고 싶다면, 호출 방식을 구분하는 로직이 필요합니다.
        return # 직접 메시지 보내지 않음

    user = update.effective_user
    logger.info(f"User {user.first_name} (ID: {user.id}) requested /today.")

    if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
        await update.message.reply_text("캘린더(CalDAV) 설정이 필요합니다.")
        return

    today = date.today()
    start_dt = datetime.combine(today, time.min)
    end_dt = datetime.combine(today, time.max)
    period_str = f"오늘 ({today.strftime('%Y-%m-%d')})"

    # 사용자에게 작업 진행 중 알림 (선택 사항이지만 권장)
    processing_msg = None
    try:
        processing_msg = await update.message.reply_text(f"🗓️ {period_str} 일정을 확인하는 중...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning(f"Could not send processing message or typing action for /today: {e}")
        processing_msg = None # 메시지 수정 불가

    # CalDAV 이벤트 조회 (기존과 동일)
    success, result_or_error = await asyncio.to_thread(
        helpers.fetch_caldav_events, start_dt, end_dt, config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD
    )

    response_html = ""
    if success:
        events_details = result_or_error
        if events_details:
            response_html = f"🗓️ <b>{period_str}</b> 일정입니다.\n"
            for event in events_details:
                summary = event.get('summary', '제목 없음')
                is_allday = event.get('is_allday', False)
                start_str = event.get('start_str')
                end_str = event.get('end_str')
                start_time_str = event.get('start_time_str')
                end_time_str = event.get('end_time_str')
                response_html += f"\n• <b>{html.escape(summary)}</b>"
                if is_allday:
                    response_html += " (종일) ☀️"
                    # 날짜 비교는 문자열 비교 대신 date 객체 비교 권장 (추후 개선 가능)
                    start_date_part = start_str.split()[0] if start_str else ""
                    end_date_part = ""
                    if end_str: # end_str가 None이 아니고 비어있지 않은 경우
                        try:
                            # CalDAV의 종일 일정 종료일은 보통 다음날 자정이므로 하루 빼줘야 함
                            end_date_obj = datetime.strptime(end_str.split()[0], '%Y-%m-%d').date() - timedelta(days=1)
                            end_date_part = end_date_obj.strftime('%Y-%m-%d')
                        except (ValueError, IndexError):
                            end_date_part = end_str.split()[0] if end_str else ""

                    if end_date_part and start_date_part and end_date_part != start_date_part:
                        response_html += f"\n  <pre>  기간: {html.escape(start_date_part)} ~ {html.escape(end_date_part)}</pre>"
                else:
                    response_html += " ✨"
                    time_info = start_time_str if start_time_str else ''
                    # 종료 시간이 시작 시간과 같지 않을 때만 표시 (단일 시점 이벤트)
                    if end_time_str and end_time_str != start_time_str:
                         time_info += f" ~ {end_time_str}"
                    if time_info: response_html += f"\n  <pre>  ⏰ {html.escape(time_info)}</pre>"
                response_html += "\n"
        else:
            response_html = f"✅ {period_str}에는 예정된 일정이 없습니다."
    else:
        user_friendly_error = "죄송합니다, 오늘 일정을 가져오는 중 문제가 발생했어요. 😥"
        logger.error(f"/today command failed. Original error: {result_or_error}")
        response_html = user_friendly_error

    # ----- 수정된 부분: 결과 메시지 전송 -----
    try:
        if processing_msg: # 진행 메시지가 성공적으로 보내졌다면 수정
             await processing_msg.edit_text(response_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        else: # 진행 메시지 전송 실패 시 새 메시지로 전송
             await update.message.reply_html(response_html, disable_web_page_preview=True)
    except BadRequest as e:
        logger.warning(f"Failed to edit message for /today (BadRequest): {e}. Sending as new message.")
        try:
            await update.message.reply_html(response_html, disable_web_page_preview=True)
        except Exception as final_send_err:
            logger.error(f"Error sending /today result as new message: {final_send_err}")
    except Exception as send_err:
        logger.error(f"Error sending /today result: {send_err}")
        # 오류 발생 시 사용자에게 간단한 오류 메시지 전송 시도
        try:
            error_fallback_msg = "결과를 표시하는 중 오류가 발생했습니다."
            if processing_msg: await processing_msg.edit_text(error_fallback_msg)
            else: await update.message.reply_text(error_fallback_msg)
        except Exception: pass
    # ------------------------------------

# =====================================================


# ======[ 수정 후: show_week_events 함수 (직접 메시지 전송) ]======
@check_ban
@require_auth
async def show_week_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # 반환 타입 None
    """[명령어 핸들러] 이번 주의 캘린더 일정을 조회하고 사용자에게 메시지를 보냅니다."""
    if not update.message:
        logger.warning("show_week_events called without update.message.")
        return

    user = update.effective_user
    logger.info(f"User {user.first_name} (ID: {user.id}) requested /week.")

    if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
        await update.message.reply_text("캘린더(CalDAV) 설정이 필요합니다.")
        return

    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) # 한 주의 시작 (월요일)
    end_of_week = start_of_week + timedelta(days=6) # 한 주의 끝 (일요일)
    start_dt = datetime.combine(start_of_week, time.min)
    end_dt = datetime.combine(end_of_week, time.max)
    period_str = f"이번 주 ({start_of_week.strftime('%m/%d')} ~ {end_of_week.strftime('%m/%d')})"

    processing_msg = None
    try:
        processing_msg = await update.message.reply_text(f"📅 {period_str} 일정을 확인하는 중...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning(f"Could not send processing message or typing action for /week: {e}")
        processing_msg = None

    success, result_or_error = await asyncio.to_thread(
        helpers.fetch_caldav_events, start_dt, end_dt, config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD
    )

    response_html = ""
    if success:
        events_details = result_or_error
        if events_details:
            response_html = f"📅 <b>{period_str}</b> 일정입니다.\n"
            events_by_date: Dict[str, List[Dict[str, Any]]] = {}
            # 이벤트들을 날짜별로 그룹화
            for event in events_details:
                event_date_str = "Unknown Date"
                start_str = event.get('start_str')
                if start_str:
                    try:
                        # start_str에서 날짜 부분만 추출하여 키로 사용
                        event_date = datetime.strptime(start_str.split()[0], '%Y-%m-%d').date()
                        # 요일 정보 추가 ('월', '화' 등)
                        event_date_str = event_date.strftime('%Y-%m-%d (%a)') # 예: 2025-05-01 (Thu)
                    except (ValueError, IndexError):
                        event_date_str = start_str.split()[0] if start_str else "날짜 정보 없음"
                else:
                    event_date_str = "날짜 정보 없음"

                if event_date_str not in events_by_date:
                    events_by_date[event_date_str] = []
                events_by_date[event_date_str].append(event)

            # 날짜 순서대로 정렬하여 출력
            for event_date_str in sorted(events_by_date.keys()):
                response_html += f"\n<b>{event_date_str}</b>\n" # 날짜 헤더
                for event in events_by_date[event_date_str]: # 해당 날짜의 이벤트들
                    summary = event.get('summary', '제목 없음')
                    is_allday = event.get('is_allday', False)
                    start_str_ev = event.get('start_str')
                    end_str_ev = event.get('end_str')
                    start_time_str = event.get('start_time_str')
                    end_time_str = event.get('end_time_str')

                    response_html += f"  • <b>{html.escape(summary)}</b>"
                    if is_allday:
                        response_html += " (종일) ☀️"
                        # 기간 표시 로직 (show_today_events와 동일하게 개선)
                        start_date_part = start_str_ev.split()[0] if start_str_ev else ""
                        end_date_part = ""
                        if end_str_ev:
                            try:
                                end_date_obj = datetime.strptime(end_str_ev.split()[0], '%Y-%m-%d').date() - timedelta(days=1)
                                end_date_part = end_date_obj.strftime('%Y-%m-%d')
                            except (ValueError, IndexError):
                                end_date_part = end_str_ev.split()[0] if end_str_ev else ""
                        if end_date_part and start_date_part and end_date_part != start_date_part:
                            response_html += f"\n    <pre>  기간: {html.escape(start_date_part)} ~ {html.escape(end_date_part)}</pre>"
                    else:
                        response_html += " ✨"
                        # 시간 표시 로직 (show_today_events와 동일하게 개선)
                        time_info = start_time_str if start_time_str else ''
                        if end_time_str and end_time_str != start_time_str:
                            time_info += f" ~ {end_time_str}"
                        if time_info: response_html += f"\n    <pre>  ⏰ {html.escape(time_info)}</pre>"
                    response_html += "\n"
        else:
            response_html = f"✅ {period_str}에는 예정된 일정이 없습니다."
    else:
        logger.error(f"/week command failed. Original error: {result_or_error}")
        response_html = "죄송합니다, 이번 주 일정을 가져오는 중 문제가 발생했어요. 😥"

    # 메시지 길이 제한 처리
    if len(response_html.encode('utf-8')) > 4096:
        response_html = response_html[:4000] + "...\n\n(일정이 너무 많아 일부만 표시합니다.)"

    # ----- 수정된 부분: 결과 메시지 전송 -----
    try:
        if processing_msg:
             await processing_msg.edit_text(response_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        else:
             await update.message.reply_html(response_html, disable_web_page_preview=True)
    except BadRequest as e:
        logger.warning(f"Failed to edit message for /week (BadRequest): {e}. Sending as new message.")
        try:
            await update.message.reply_html(response_html, disable_web_page_preview=True)
        except Exception as final_send_err:
            logger.error(f"Error sending /week result as new message: {final_send_err}")
    except Exception as send_err:
        logger.error(f"Error sending /week result: {send_err}")
        try:
            error_fallback_msg = "결과를 표시하는 중 오류가 발생했습니다."
            if processing_msg: await processing_msg.edit_text(error_fallback_msg)
            else: await update.message.reply_text(error_fallback_msg)
        except Exception: pass
    # ------------------------------------

# ======================================================


# ======[ 수정 후: show_month_events 함수 (직접 메시지 전송) ]======
@check_ban
@require_auth
async def show_month_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # 반환 타입 None
    """[명령어 핸들러] 이번 달의 캘린더 일정을 조회하고 사용자에게 메시지를 보냅니다."""
    if not update.message:
        logger.warning("show_month_events called without update.message.")
        return

    user = update.effective_user
    logger.info(f"User {user.first_name} (ID: {user.id}) requested /month.")

    if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
        await update.message.reply_text("캘린더(CalDAV) 설정이 필요합니다.")
        return

    today = date.today()
    # 이번 달의 첫날과 마지막 날 계산
    first_day_of_month = today.replace(day=1)
    # calendar.monthrange(year, month)는 해당 월의 시작 요일과 마지막 날짜를 튜플로 반환
    _, last_day_num = calendar.monthrange(today.year, today.month)
    last_day_of_month = today.replace(day=last_day_num)

    start_dt = datetime.combine(first_day_of_month, time.min)
    end_dt = datetime.combine(last_day_of_month, time.max)
    period_str = f"이번 달 ({today.strftime('%Y년 %m월')})"

    processing_msg = None
    try:
        processing_msg = await update.message.reply_text(f"📆 {period_str} 일정을 확인하는 중...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning(f"Could not send processing message or typing action for /month: {e}")
        processing_msg = None

    success, result_or_error = await asyncio.to_thread(
        helpers.fetch_caldav_events, start_dt, end_dt, config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD
    )

    response_html = ""
    if success:
        events_details = result_or_error
        if events_details:
            response_html = f"📆 <b>{period_str}</b> 일정입니다.\n"
            events_by_date: Dict[str, List[Dict[str, Any]]] = {}
            # 날짜별 그룹화 (show_week_events와 동일)
            for event in events_details:
                event_date_str = "Unknown Date"
                start_str = event.get('start_str')
                if start_str:
                    try:
                        event_date = datetime.strptime(start_str.split()[0], '%Y-%m-%d').date()
                        event_date_str = event_date.strftime('%Y-%m-%d (%a)')
                    except (ValueError, IndexError):
                        event_date_str = start_str.split()[0] if start_str else "날짜 정보 없음"
                else:
                    event_date_str = "날짜 정보 없음"

                if event_date_str not in events_by_date:
                    events_by_date[event_date_str] = []
                events_by_date[event_date_str].append(event)

            # 날짜 순서대로 출력 (show_week_events와 동일)
            for event_date_str in sorted(events_by_date.keys()):
                response_html += f"\n<b>{event_date_str}</b>\n"
                for event in events_by_date[event_date_str]:
                    summary = event.get('summary', '제목 없음')
                    is_allday = event.get('is_allday', False)
                    start_str_ev = event.get('start_str')
                    end_str_ev = event.get('end_str')
                    start_time_str = event.get('start_time_str')
                    end_time_str = event.get('end_time_str')

                    response_html += f"  • <b>{html.escape(summary)}</b>"
                    if is_allday:
                        response_html += " (종일) ☀️"
                        start_date_part = start_str_ev.split()[0] if start_str_ev else ""
                        end_date_part = ""
                        if end_str_ev:
                             try:
                                 end_date_obj = datetime.strptime(end_str_ev.split()[0], '%Y-%m-%d').date() - timedelta(days=1)
                                 end_date_part = end_date_obj.strftime('%Y-%m-%d')
                             except (ValueError, IndexError):
                                 end_date_part = end_str_ev.split()[0] if end_str_ev else ""
                        if end_date_part and start_date_part and end_date_part != start_date_part:
                             response_html += f"\n    <pre>  기간: {html.escape(start_date_part)} ~ {html.escape(end_date_part)}</pre>"
                    else:
                        response_html += " ✨"
                        time_info = start_time_str if start_time_str else ''
                        if end_time_str and end_time_str != start_time_str:
                             time_info += f" ~ {end_time_str}"
                        if time_info: response_html += f"\n    <pre>  ⏰ {html.escape(time_info)}</pre>"
                    response_html += "\n"
        else:
            response_html = f"✅ {period_str}에는 예정된 일정이 없습니다."
    else:
        logger.error(f"/month command failed. Original error: {result_or_error}")
        response_html = "죄송합니다, 이번 달 일정을 가져오는 중 문제가 발생했어요. 😥"

    # 메시지 길이 제한 처리
    if len(response_html.encode('utf-8')) > 4096:
        response_html = response_html[:4000] + "...\n\n(일정이 너무 많아 일부만 표시합니다.)"

    # ----- 수정된 부분: 결과 메시지 전송 -----
    try:
        if processing_msg:
             await processing_msg.edit_text(response_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        else:
             await update.message.reply_html(response_html, disable_web_page_preview=True)
    except BadRequest as e:
        logger.warning(f"Failed to edit message for /month (BadRequest): {e}. Sending as new message.")
        try:
            await update.message.reply_html(response_html, disable_web_page_preview=True)
        except Exception as final_send_err:
            logger.error(f"Error sending /month result as new message: {final_send_err}")
    except Exception as send_err:
        logger.error(f"Error sending /month result: {send_err}")
        try:
            error_fallback_msg = "결과를 표시하는 중 오류가 발생했습니다."
            if processing_msg: await processing_msg.edit_text(error_fallback_msg)
            else: await update.message.reply_text(error_fallback_msg)
        except Exception: pass
    # ------------------------------------

# =======================================================

# --- /deletecontact 관련 핸들러 ---
# ... (기존 deletecontact_start 함수 - 변경 없음) ...
@check_ban
@require_auth
@require_admin # <--- 관리자 확인 데코레이터 추가!
async def deletecontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    if not config.CARDDAV_URL or not config.CARDDAV_USERNAME or not config.CARDDAV_PASSWORD:
        await update.message.reply_text("연락처(CardDAV) 설정 필요")
        return ConversationHandler.END
    logger.info(f"User {update.effective_user.first_name} initiated /deletecontact conversation.")
    await update.message.reply_text(
        "🗑️ 어떤 연락처를 삭제하시겠습니까?\n"
        "삭제할 연락처의 <b>정확한 이름</b> 또는 <b>ID</b>를 입력해주세요.\n"
        "(ID는 보통 URL 형태입니다)\n\n"
        "취소하려면 /cancel 을 입력하세요.",
        parse_mode='HTML'
    )
    return DeleteContactStates.WAITING_TARGET

# ... (기존 deletecontact_target_received 함수 - 변경 없음) ...
async def deletecontact_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    name_or_id_to_delete = update.message.text.strip()
    if not name_or_id_to_delete:
        await update.message.reply_text("삭제할 연락처 이름/ID를 입력해주세요.")
        return DeleteContactStates.WAITING_TARGET
    logger.info(f"User {update.effective_user.first_name} entered target for deletion: {name_or_id_to_delete}")
    context.user_data['contact_to_delete'] = name_or_id_to_delete
    keyboard = [[InlineKeyboardButton("✅ 예, 삭제합니다", callback_data="confirm_delete"), InlineKeyboardButton("❌ 아니요", callback_data="cancel_delete")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(
        f"🗑️ 연락처 '<b>{html.escape(name_or_id_to_delete)}</b>' 을(를) 정말로 삭제하시겠습니까?\n"
        f"🚨 이 작업은 되돌릴 수 없습니다!",
        reply_markup=reply_markup
    )
    return DeleteContactStates.CONFIRM_DELETION

# !!!!! delete_confirmation_callback 함수 수정 !!!!!
@check_ban
@require_auth
async def delete_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    
    query = update.callback_query
    if not query: return

    query = update.callback_query
    if not query: return ConversationHandler.END
    await query.answer()

    callback_data = query.data
    final_message = ""
    name_or_id_to_delete = context.user_data.get('contact_to_delete')

    if callback_data == "confirm_delete":
        if not name_or_id_to_delete:
            # ... (오류 처리) ...
            final_message = "오류: 삭제 대상 정보 없음."
            try: await query.edit_message_text(final_message)
            except Exception: pass
            if 'contact_to_delete' in context.user_data: del context.user_data['contact_to_delete']
            return ConversationHandler.END

        logger.warning(f"Deletion confirmed for: {name_or_id_to_delete}")

        try:
            await query.edit_message_text("🗑️ 삭제를 진행합니다...")
            # --- ChatAction 추가 ---
            await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
            # ----------------------
        except Exception as e:
            logger.warning(f"Could not edit message or send typing action before delete: {e}")

        try:
            # --- 시간이 걸리는 작업: CardDAV 삭제 ---
            success, result_or_error = await asyncio.to_thread(
                helpers.delete_carddav_contact, config.CARDDAV_URL, config.CARDDAV_USERNAME, config.CARDDAV_PASSWORD, name_or_id_to_delete
            )
            # ... (결과 처리) ...
            if success:
                final_message = f"{result_or_error}"
                logger.info(f"Successfully deleted contact: {name_or_id_to_delete}")
            else:
                final_message = f"❌ 연락처 삭제 실패."
                logger.error(f"/deletecontact failed for '{name_or_id_to_delete}'. Error: {result_or_error}")

        except Exception as thread_err:
            # ... (오류 처리) ...
            logger.error(f"Error calling helpers.delete_carddav_contact in thread: {thread_err}", exc_info=True)
            final_message = "연락처 삭제 중 오류 발생."

        try: await query.edit_message_text(final_message) # 최종 결과 메시지 수정
        except Exception as edit_err:
            # ... (메시지 수정 실패 시 새 메시지 전송) ...
            logger.error(f"Failed to edit message after delete attempt: {edit_err}")
            try: await context.bot.send_message(chat_id=query.message.chat_id, text=final_message)
            except Exception: pass

    elif callback_data == "cancel_delete":
        # ... (취소 처리) ...
        logger.info(f"Contact deletion cancelled for target: {name_or_id_to_delete}")
        final_message = "삭제가 취소되었습니다."
        try: await query.edit_message_text(final_message)
        except Exception: pass
    else:
        # ... (알 수 없는 콜백 처리) ...
        logger.warning(f"Unknown callback_data in delete_confirmation: {callback_data}")
        final_message = "알 수 없는 응답입니다."
        try: await query.edit_message_text(final_message)
        except Exception: pass

    if 'contact_to_delete' in context.user_data:
        del context.user_data['contact_to_delete']
    return ConversationHandler.END

# --- /cancel 명령어 처리 함수 ---
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id # user_id 가져오기 추가

    logger.info(f"User {user.first_name} canceled conversation.")
    cleared_keys = []
    # CONVERSATION_USER_DATA_KEYS 에 정의된 모든 키를 정리
    for key in CONVERSATION_USER_DATA_KEYS: # 리스트 직접 순회
        if key in context.user_data:
            try:
                del context.user_data[key]
                cleared_keys.append(key)
            except KeyError:
                pass # 이미 없으면 무시

    if cleared_keys:
        logger.debug(f"Cleared user_data keys on cancel: {cleared_keys}")
        await update.message.reply_text('진행 중이던 작업을 취소했습니다.')
    else:
        # 로그상 이 메시지가 나온 것은 정상일 수 있음 (정리할 데이터가 없을 때)
        await update.message.reply_text('취소할 작업이 없거나 이미 완료되었습니다.')
    return ConversationHandler.END

# --- Echo 핸들러 ---
# ... (기존 echo 함수 - 변경 없음) ...
@check_ban
@require_auth
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    user_message = update.message.text
    logger.info(f"Received non-command text: {user_message}")
    response_message = (
        f"'{html.escape(user_message)}'? 🤔\n\n"
        f"명령어 형식이 아니에요.\n"
        f"AI 질문은 <code>/ask {html.escape(user_message)}</code> 처럼 보내주시겠어요?\n\n"
        f"다른 기능은 <b>/start</b> 를 눌러 확인해보세요! 😊"
    )
    try: await update.message.reply_html(response_message)
    except Exception as send_err: logger.error(f"Error sending echo reply: {send_err}")

# --- /date 관련 핸들러 ---
# ... (기존 date_command_start 함수 - 변경 없음) ...
@check_ban
@require_auth
async def date_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    logger.info(f"User {update.effective_user.first_name} initiated /date conversation.")
    await _clear_other_conversations(context, [])
    await update.message.reply_text(
        "📅 어떤 날짜의 일정을 알려드릴까요?\n"
        "날짜를 <b>YYYY-MM-DD</b> 형식으로 입력해주세요.\n"
        "(예: 2024-12-25)\n\n"
        "취소하려면 /cancel 을 입력하세요.",
        parse_mode='HTML'
    )
    return DateInputStates.WAITING_DATE

# !!!!! date_input_received 함수 수정 !!!!!
async def date_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    date_str = update.message.text.strip()
    logger.info(f"User {update.effective_user.first_name} entered date: {date_str}")

    if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
        await update.message.reply_text("캘린더(CalDAV) 설정 필요...")
        return ConversationHandler.END

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_dt = datetime.combine(target_date, time.min)
        end_dt = datetime.combine(target_date, time.max)
        period_str = f"{target_date.strftime('%Y-%m-%d (%a)')}"

        processing_msg = await update.message.reply_text(f"🗓️ {period_str} 일정을 확인하는 중...")
        # --- ChatAction 추가 ---
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        # ----------------------

        # --- 시간이 걸리는 작업: CalDAV 조회 ---
        success, result_or_error = await asyncio.to_thread(
            helpers.fetch_caldav_events, start_dt, end_dt, config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD
        )

        response_html = ""
        # ... (결과 처리 로직 - 기존과 동일) ...
        if success:
            events_details = result_or_error
            if events_details:
                response_html = f"🗓️ <b>{period_str}</b> 일정입니다.\n"
                # ... (이벤트 포맷팅) ...
                for event in events_details:
                    response_html += f"\n• <b>{html.escape(event['summary'])}</b>"
                    if event['is_allday']: response_html += " (종일) ☀️"
                    else: response_html += " ✨"
                    # ... (시간 등 상세 정보 추가) ...
                    response_html += "\n"
            else:
                response_html = f"✅ {period_str}에는 예정된 일정이 없습니다."
        else:
             response_html = f"죄송합니다, {period_str} 일정 조회 중 오류 발생 😥"
             logger.error(f"/date failed for date '{date_str}'. Error: {result_or_error}")

        try: await processing_msg.edit_text(response_html, parse_mode='HTML') # 결과 메시지 수정
        except Exception as edit_err:
            # ... (메시지 수정 실패 시 새 메시지 전송) ...
            logger.error(f"Failed to edit message for /date: {edit_err}")
            try: await update.message.reply_html(response_html)
            except Exception as send_err: logger.error(f"Error sending /date result HTML: {send_err}")

    except ValueError:
        await update.message.reply_text(
            f"😵 입력하신 '{html.escape(date_str)}'는 YYYY-MM-DD 형식이 아닙니다.\n"
            "다시 입력해주세요. (예: 2024-05-15)\n\n"
            "취소하려면 /cancel 을 입력하세요.",
            parse_mode='HTML'
        )
        return DateInputStates.WAITING_DATE

    return ConversationHandler.END

# --- /findcontact 관련 핸들러 ---
# ... (기존 findcontact_start 함수 - 변경 없음) ...
@check_ban
@require_auth
async def findcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    logger.info(f"User {update.effective_user.first_name} initiated /findcontact conversation.")
    await _clear_other_conversations(context, [])
    await update.message.reply_text(
        "👤 누구의 연락처를 찾아드릴까요?\n"
        "검색할 이름을 입력해주세요.\n\n"
        "취소하려면 /cancel 을 입력하세요."
    )
    return FindContactStates.WAITING_NAME

# !!!!! findcontact_name_received 함수 전체를 아래 코드로 교체 !!!!!
async def findcontact_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    """사용자로부터 이름을 받아 CardDAV 서버에서 검색하고 상세 정보를 보여줍니다."""
    name_to_find = update.message.text.strip()
    user = update.effective_user
    logger.info(f"User {user.first_name} searching for contact name: {name_to_find}")

    if not config.CARDDAV_URL or not config.CARDDAV_USERNAME or not config.CARDDAV_PASSWORD:
        await update.message.reply_text("연락처(CardDAV) 설정이 필요합니다. 작업을 취소합니다.")
        return ConversationHandler.END

    # --- ChatAction 추가 ---
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    # ----------------------

    # --- 시간이 걸리는 작업: CardDAV 조회 ---
    # helpers.find_contact_details는 (성공여부, 결과리스트_또는_오류메시지) 튜플 반환 가정
    success, result_or_message = await asyncio.to_thread(
        helpers.find_contact_details, config.CARDDAV_URL, config.CARDDAV_USERNAME, config.CARDDAV_PASSWORD, name_to_find
    )

    response_html = ""
    if success:
        if isinstance(result_or_message, str): # 결과 없음 또는 helpers 내부 오류 메시지
            response_html = result_or_message # helpers가 제공하는 메시지 그대로 사용
        elif isinstance(result_or_message, list) and result_or_message: # 결과 리스트가 있고 비어있지 않다면
            found_contacts_details = result_or_message
            response_html = f"✨ <b>'{html.escape(name_to_find)}'</b> 연락처 검색 결과 ({len(found_contacts_details)}개) ✨\n"

            for i, contact in enumerate(found_contacts_details):
                response_html += f"\n<b>===== {i+1}. {html.escape(contact.get('name', '이름 없음'))} =====</b>\n" # 이름 기본값 추가

                # ===== 모든 정보 표시 로직 복원 =====
                if contact.get('nickname'):
                    response_html += f"<i>(별명: {html.escape(contact['nickname'])})</i>\n"
                if contact.get('tel'):
                    # tel: 링크 생성 및 하이픈 제거
                    tel_links = [f"<a href='tel:{t.replace('-', '')}'>{html.escape(t)}</a>" for t in contact['tel'] if t]
                    if tel_links: response_html += f"☎️ <b>전화:</b> {', '.join(tel_links)}\n"
                if contact.get('email'):
                    email_links = [f"<a href='mailto:{e}'>{html.escape(e)}</a>" for e in contact['email'] if e]
                    if email_links: response_html += f"📧 <b>이메일:</b> {', '.join(email_links)}\n"
                if contact.get('title'):
                    response_html += f"🧑‍💼 <b>직책:</b> {html.escape(contact['title'])}\n"
                if contact.get('org'):
                    org_display = " / ".join(filter(None, map(html.escape, contact['org']))) # 빈 문자열 필터링
                    if org_display: response_html += f"🏢 <b>소속:</b> {org_display}\n"
                if contact.get('adr'):
                    response_html += f"🏠 <b>주소:</b> {html.escape(contact['adr'])}\n"
                if contact.get('url'):
                    url_links = [f"<a href=\"{u}\">{html.escape(u)}</a>" for u in contact['url'] if u] # URL은 큰따옴표 유지
                    if url_links: response_html += f"🌐 <b>웹사이트:</b> {', '.join(url_links)}\n"
                if contact.get('impp'):
                    impp_display = ", ".join(filter(None, map(html.escape, contact['impp'])))
                    if impp_display: response_html += f"💬 <b>메신저:</b> {impp_display}\n"
                if contact.get('birthday'):
                    response_html += f"🎂 <b>생일:</b> {html.escape(contact['birthday'])}\n"
                if contact.get('note'):
                    # pre 태그 사용 시 들여쓰기 유의
                    safe_note = html.escape(contact['note']).strip() # 양쪽 공백 제거
                    if safe_note: # 메모 내용 있을 때만 표시
                       response_html += f"📝 <b>메모:</b>\n<pre>{safe_note}</pre>\n"
                # ===== 정보 표시 로직 끝 =====
                response_html += "\n" # 연락처 간 간격

        elif isinstance(result_or_message, list) and not result_or_message: # 빈 리스트 (이름 못찾음)
             response_html = f"🤷 '{html.escape(name_to_find)}' 이름과 일치하는 연락처를 찾을 수 없습니다."
        else: # 예상치 못한 결과 타입
            logger.error(f"Unexpected result type from helpers.find_contact_details: {type(result_or_message)}")
            response_html = "❌ 연락처 검색 결과를 처리하는 중 오류가 발생했습니다."

    else: # helpers.find_contact_details 함수 자체가 실패
        logger.error(f"/findcontact failed for name '{name_to_find}'. Original error: {result_or_message}")
        response_html = f"❌ 연락처 검색 중 오류 발생: {result_or_message}"

    # 메시지 길이 제한 확인 및 전송
    if len(response_html.encode('utf-8')) > 4096: # 텔레그램 최대 길이
         response_html = response_html[:4000] + "...\n\n(정보가 너무 많아 일부만 표시합니다.)"

    try:
        # disable_web_page_preview=True 추가하여 URL 미리보기 방지
        await update.message.reply_html(response_html, disable_web_page_preview=True)
    except Exception as send_err:
         logger.error(f"Error sending /findcontact result HTML: {send_err}", exc_info=True)
         await update.message.reply_text("결과 표시 중 오류가 발생했습니다.")

    return ConversationHandler.END

# --- /ask 관련 핸들러 ---
# ... (기존 ask_ai_start 함수 - 변경 없음) ...
@check_ban
@require_auth
async def ask_ai_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    logger.info(f"User {update.effective_user.first_name} initiated /ask conversation.")
    await _clear_other_conversations(context, [])
    await update.message.reply_text(
        "🤖 AI에게 무엇이 궁금하신가요?\n"
        "질문을 입력해주세요.\n\n"
        "취소하려면 /cancel 을 입력하세요."
    )
    return AskAIStates.WAITING_QUESTION

# !!!!! ask_ai_question_received 함수 수정 !!!!!
async def ask_ai_question_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    question = update.message.text
    logger.info(f"User {update.effective_user.first_name} asked AI: {question}")

    ai_model = context.bot_data.get('ai_model')
    if not ai_model:
        await update.message.reply_text("AI 기능 사용 불가...")
        return ConversationHandler.END

    # AI 처리 중 메시지 수정 및 ChatAction 추가
    processing_message = await update.message.reply_text("AI가 생각 중... 🤔")
    # --- ChatAction 추가 ---
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    # ----------------------

    try:
        # --- 시간이 걸리는 작업: AI 모델 호출 ---
        response = await ai_model.generate_content_async(question)
        ai_response = response.text
        await processing_message.edit_text(f"🤖 AI 답변:\n\n{ai_response}")
        logger.info(f"AI Response sent.")
    except Exception as e:
        logger.error(f"Error generating AI content: {e}", exc_info=True)
        await processing_message.edit_text("AI 답변 생성 오류 😵")

    return ConversationHandler.END

# --- /addcontact 관련 핸들러 ---
# ... (기존 addcontact_start, addcontact_name_received, addcontact_phone_received - 변경 없음) ...
async def addcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    logger.info(f"User {update.effective_user.first_name} initiated /addcontact conversation.")
    await _clear_other_conversations(context, ['new_contact'])
    context.user_data['new_contact'] = {}
    await update.message.reply_text(
        "✏️ 새로 추가할 연락처의 <b>이름</b>을 입력해주세요.\n\n"
        "취소하려면 /cancel 을 입력하세요.",
        parse_mode='HTML'
    )
    return AddContactStates.WAITING_NAME

@check_ban
@require_auth
async def addcontact_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("이름 비워둘 수 없음...")
        return AddContactStates.WAITING_NAME
    context.user_data['new_contact']['name'] = name
    logger.info(f"Received contact name: {name}")
    await update.message.reply_text(
        f"📞 <b>{name}</b>님의 <b>전화번호</b>를 입력해주세요.\n"
        "없으면 '<b>건너뛰기</b>' 또는 '-' 입력\n\n"
        "취소하려면 /cancel",
        parse_mode='HTML'
    )
    return AddContactStates.WAITING_PHONE

async def addcontact_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    phone_input = update.message.text.strip()
    phone = None
    name = context.user_data.get('new_contact', {}).get('name', '새 연락처')
    if phone_input.lower() in ['건너뛰기', '-']: phone = None; logger.info("Phone skipped.")
    elif re.fullmatch(r'^[0-9+ -]+$', phone_input): phone = phone_input; logger.info(f"Received phone: {phone}")
    else:
        await update.message.reply_text(
            f"😵 전화번호 형식이 아니거나 '건너뛰기'가 아닙니다.\n\n"
            f"📞 <b>{name}</b>님의 <b>전화번호</b>를 다시 입력하거나,\n"
            "'<b>건너뛰기</b>' 또는 '<b>-</b>'를 입력해주세요.",
            parse_mode='HTML'
        )
        return AddContactStates.WAITING_PHONE
    context.user_data['new_contact']['phone'] = phone
    await update.message.reply_text(
        f"📧 <b>{name}</b>님의 <b>이메일 주소</b>를 입력해주세요.\n"
        "없으면 '<b>건너뛰기</b>' 또는 '-' 입력\n\n"
        "취소하려면 /cancel",
        parse_mode='HTML'
    )
    return AddContactStates.WAITING_EMAIL

# !!!!! addcontact_email_received 함수 수정 !!!!!
async def addcontact_email_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    email_input = update.message.text.strip()
    email = None
    name = context.user_data.get('new_contact', {}).get('name', '새 연락처')

    if email_input.lower() in ['건너뛰기', '-']: email = None; logger.info("Email skipped.")
    elif '@' in email_input and '.' in email_input.split('@')[-1]: email = email_input; logger.info(f"Received email: {email}")
    else:
        await update.message.reply_text(
            f"😵 이메일 형식이 아니거나 '건너뛰기'가 아닙니다.\n\n"
            f"📧 <b>{name}</b>님의 <b>이메일 주소</b>를 다시 입력하거나,\n"
            "'<b>건너뛰기</b>' 또는 '<b>-</b>'를 입력해주세요.",
            parse_mode='HTML'
        )
        return AddContactStates.WAITING_EMAIL

    context.user_data['new_contact']['email'] = email

    new_contact_info = context.user_data.get('new_contact', {})
    name = new_contact_info.get('name') # 이름은 필수
    phone = new_contact_info.get('phone')
    email = new_contact_info.get('email') # email 변수 재사용

    if not config.CARDDAV_URL or not config.CARDDAV_USERNAME or not config.CARDDAV_PASSWORD:
        # ... (설정 오류 처리) ...
        await update.message.reply_text("CardDAV 설정 필요...")
        if 'new_contact' in context.user_data: del context.user_data['new_contact']
        return ConversationHandler.END
    if not name:
        # ... (이름 누락 오류 처리) ...
        await update.message.reply_text("오류: 이름 정보 없음...")
        if 'new_contact' in context.user_data: del context.user_data['new_contact']
        return ConversationHandler.END

    processing_msg = await update.message.reply_text(f"⏳ '{name}' 연락처 저장 중...")
    # --- ChatAction 추가 ---
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    # ----------------------

    try:
        # --- 시간이 걸리는 작업: CardDAV 추가 ---
        success, result_or_error = await asyncio.to_thread(
            helpers.add_new_contact,
            config.CARDDAV_URL, config.CARDDAV_USERNAME, config.CARDDAV_PASSWORD,
            name, phone, email
        )
        final_message = f"{result_or_error}" if success else f"❌ 추가 실패: {result_or_error}"
        if success: logger.info(f"Successfully added contact: {name}")
        else: logger.error(f"/addcontact failed for '{name}'. Error: {result_or_error}")
        await processing_msg.edit_text(final_message)

    except Exception as thread_err:
        # ... (오류 처리) ...
        logger.error(f"Error calling helpers.add_new_contact in thread: {thread_err}", exc_info=True)
        try: await processing_msg.edit_text("연락처 추가 중 오류 발생.")
        except Exception: pass

    finally:
        if 'new_contact' in context.user_data: del context.user_data['new_contact']
        logger.debug("Exiting addcontact conversation.")

    return ConversationHandler.END

# --- /searchcontact 관련 핸들러 ---
# ... (기존 searchcontact_start 함수 - 변경 없음) ...
@check_ban
@require_auth
async def searchcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    logger.info(f"User {update.effective_user.first_name} initiated /searchcontact conversation.")
    await _clear_other_conversations(context, [])
    await update.message.reply_text(
        "🔎 어떤 키워드로 연락처를 검색하시겠어요?\n"
        "찾고 싶은 <b>이름, 이메일, 전화번호의 일부</b>를 입력해주세요.\n\n"
        "취소하려면 /cancel",
        parse_mode='HTML'
    )
    return SearchContactStates.WAITING_KEYWORD

# !!!!! searchcontact_keyword_received 함수 전체를 아래 코드로 교체 !!!!!
async def searchcontact_keyword_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    """사용자로부터 검색 키워드를 받아 CardDAV 서버에서 검색하고 상세 결과를 보여줍니다."""
    keyword = update.message.text.strip()
    if not keyword: # 빈 입력 방지
         await update.message.reply_text("검색할 키워드를 입력해주세요.")
         return SearchContactStates.WAITING_KEYWORD # 다시 키워드 입력 상태 유지

    user = update.effective_user
    logger.info(f"User {user.first_name} searching contacts with keyword: {keyword}")

    # CardDAV 정보 확인
    if not config.CARDDAV_URL or not config.CARDDAV_USERNAME or not config.CARDDAV_PASSWORD:
        await update.message.reply_text("연락처(CardDAV) 설정이 필요합니다. 작업을 취소합니다.")
        return ConversationHandler.END

    # 검색 진행 메시지 + Typing Action
    processing_msg = await update.message.reply_text(f"🔎 '{html.escape(keyword)}' 키워드로 연락처 검색 중...")
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning(f"Could not send typing action for /searchcontact: {e}")

    # --- helpers.search_carddav_contacts 호출 (상세 정보 반환 가정) ---
    success, result_or_message = await asyncio.to_thread(
        helpers.search_carddav_contacts, config.CARDDAV_URL, config.CARDDAV_USERNAME, config.CARDDAV_PASSWORD, keyword
    )

    response_html = ""
    if success:
        if isinstance(result_or_message, str): # 결과 없음 또는 helpers 내부 오류 메시지
            response_html = result_or_message
        elif isinstance(result_or_message, list): # 연락처 목록 (상세 정보 포함 가정)
            contacts_found = result_or_message
            if contacts_found:
                response_html = f"🔎 <b>'{html.escape(keyword)}' 연락처 검색 결과 ({len(contacts_found)}개):</b>\n"

                # ===== findcontact와 동일한 상세 정보 포맷팅 로직 적용 =====
                for i, contact in enumerate(contacts_found):
                    response_html += f"\n<b>===== {i+1}. {html.escape(contact.get('name', '이름 없음'))} =====</b>\n"

                    if contact.get('nickname'):
                        response_html += f"<i>(별명: {html.escape(contact['nickname'])})</i>\n"
                    if contact.get('tel'):
                        tel_links = [f"<a href='tel:{t.replace('-', '')}'>{html.escape(t)}</a>" for t in contact['tel'] if t]
                        if tel_links: response_html += f"☎️ <b>전화:</b> {', '.join(tel_links)}\n"
                    if contact.get('email'):
                        email_links = [f"<a href='mailto:{e}'>{html.escape(e)}</a>" for e in contact['email'] if e]
                        if email_links: response_html += f"📧 <b>이메일:</b> {', '.join(email_links)}\n"
                    if contact.get('title'):
                        response_html += f"🧑‍💼 <b>직책:</b> {html.escape(contact['title'])}\n"
                    if contact.get('org'):
                        org_display = " / ".join(filter(None, map(html.escape, contact['org'])))
                        if org_display: response_html += f"🏢 <b>소속:</b> {org_display}\n"
                    if contact.get('adr'):
                        response_html += f"🏠 <b>주소:</b> {html.escape(contact['adr'])}\n"
                    if contact.get('url'):
                        url_links = [f"<a href=\"{u}\">{html.escape(u)}</a>" for u in contact['url'] if u]
                        if url_links: response_html += f"🌐 <b>웹사이트:</b> {', '.join(url_links)}\n"
                    if contact.get('impp'):
                        impp_display = ", ".join(filter(None, map(html.escape, contact['impp'])))
                        if impp_display: response_html += f"💬 <b>메신저:</b> {impp_display}\n"
                    if contact.get('birthday'):
                        response_html += f"🎂 <b>생일:</b> {html.escape(contact['birthday'])}\n"
                    if contact.get('note'):
                        safe_note = html.escape(contact['note']).strip()
                        if safe_note: response_html += f"📝 <b>메모:</b>\n<pre>{safe_note}</pre>\n"
                    # ====================================================
                    response_html += "\n" # 연락처 간 간격

                # 결과가 너무 많을 경우 메시지 추가 (예: 10개 초과 시)
                if len(contacts_found) > 10:
                    response_html += "\n\n(결과가 너무 많습니다. 더 구체적인 키워드로 다시 검색해보세요.)"

            else: # 빈 리스트 (일치하는 연락처 없음)
                response_html = f"🤷 '{html.escape(keyword)}' 키워드와 일치하는 연락처를 찾을 수 없습니다."
        else: # 예상치 못한 결과 타입
            logger.error(f"Unexpected result type from helpers.search_carddav_contacts: {type(result_or_message)}")
            response_html = "❌ 검색 결과 처리 중 오류가 발생했습니다."

    else: # helpers 함수 자체가 실패
        logger.error(f"/searchcontact failed for keyword '{keyword}'. Original error: {result_or_message}")
        response_html = f"❌ 연락처 검색 중 오류 발생: {result_or_message}"

    # 메시지 길이 제한 확인 및 전송
    if len(response_html.encode('utf-8')) > 4096:
         response_html = response_html[:4000] + "...\n\n(정보가 너무 많아 일부만 표시합니다.)"

    try:
        # 기존 '검색 중...' 메시지를 결과로 수정
        await processing_msg.edit_text(response_html, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as edit_err:
         logger.error(f"Failed to edit message for /searchcontact: {edit_err}", exc_info=True)
         # 수정 실패 시 새 메시지로 보내기 시도
         try:
             await update.message.reply_html(response_html, disable_web_page_preview=True)
         except Exception as send_err:
             logger.error(f"Error sending /searchcontact result HTML: {send_err}", exc_info=True)
             await update.message.reply_text("검색 결과 표시 중 오류 발생")

    # 성공/실패 여부와 관계없이 대화 종료
    return ConversationHandler.END

# --- 대화 중 다른 명령어 입력 시 안내 ---
# ... (기존 inform_cancel_needed 함수 - 변경 없음) ...
async def inform_cancel_needed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    attempted_command = update.message.text
    logger.warning(f"User {update.effective_user.first_name} attempted command '{attempted_command}' during conversation.")
    reply_message = (
        f"⚠️ 지금 다른 작업을 진행하고 있어요.\n"
        f"'{attempted_command}' 명령을 실행하려면, 먼저 <b>/cancel</b> 을 입력해서 현재 작업을 취소해주세요."
    )
    await update.message.reply_html(reply_message)

# --- /unban 대화 시작 함수 (기존 unban_user 함수 수정) ---
@check_ban
@require_auth
@require_admin
async def unban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """[Admin Only] 사용자 차단 해제 대화를 시작합니다."""
    user = update.effective_user
    logger.info(f"Admin {user.first_name} (ID: {user.id}) initiated /unban conversation.")
    await _clear_other_conversations(context, []) # 다른 대화 정리

    # 사용자 ID를 직접 입력받도록 요청
    await update.message.reply_text(
        "🚫 <b>사용자 차단 해제</b> 🚫\n\n"
        "차단을 해제할 사용자의 <b>숫자 ID</b>를 입력해주세요.\n"
        "차단 목록은 /banlist 명령어로 확인할 수 있습니다.\n\n"
        "취소하려면 /cancel 을 입력하세요.",
        parse_mode=ParseMode.HTML
    )
    return UnbanStates.WAITING_TARGET_ID # 다음 상태: ID 입력 대기

# --- 사용자 ID 입력 처리 함수 (새로 추가) ---
@check_ban      # 데코레이터 유지 (차단된 관리자 방지)
@require_auth   # 데코레이터 유지
@require_admin  # 데코레이터 유지
async def unban_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """관리자로부터 차단 해제할 사용자 ID를 입력받아 처리합니다."""
    admin_user = update.effective_user # 이미 관리자임이 확인됨
    target_id_str = update.message.text.strip()

    if not target_id_str.isdigit():
        await update.message.reply_text("⚠️ 사용자 ID는 숫자만 입력해주세요. 다시 입력하세요.")
        return UnbanStates.WAITING_TARGET_ID # ID 입력 상태 유지

    try:
        user_id_to_unban = int(target_id_str)
    except ValueError:
        # isdigit()에서 걸렀지만 만약을 위해 처리
        await update.message.reply_text("⚠️ 유효하지 않은 숫자 형식입니다. 다시 입력하세요.")
        return UnbanStates.WAITING_TARGET_ID

    logger.info(f"Admin {admin_user.first_name} attempting to unban user ID: {user_id_to_unban}")

    # DB 차단 해제 시도
    processing_msg = await update.message.reply_text(f"⏳ 사용자 ID <code>{user_id_to_unban}</code> 차단 해제 시도 중...", parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception: pass

    try:
        unbanned = await asyncio.to_thread(database.unban_user_db, user_id_to_unban)
        final_message = ""
        if unbanned:
            final_message = f"✅ 사용자 ID <code>{user_id_to_unban}</code>의 차단을 성공적으로 해제했습니다."
            # 사용자에게 알림 (선택 사항)
            try:
                await context.bot.send_message(chat_id=user_id_to_unban, text="🎉 봇 접근 차단이 해제되었습니다. /start")
            except Exception as notify_err:
                logger.warning(f"Could not send unban notification to {user_id_to_unban}: {notify_err}")
                final_message += "\n\nℹ️ 사용자에게 차단 해제 알림 전송 실패 (봇 차단 등)."
        else:
            final_message = f"ℹ️ 사용자 ID <code>{user_id_to_unban}</code>는 차단 목록에 없거나 해제 중 오류 발생. (/banlist 확인)"

        await processing_msg.edit_text(final_message, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error during unban process for user ID {user_id_to_unban}: {e}", exc_info=True)
        await processing_msg.edit_text(f"❌ 사용자 ID <code>{user_id_to_unban}</code> 차단 해제 중 오류 발생.", parse_mode=ParseMode.HTML)

    return ConversationHandler.END # 대화 종료

@check_ban
@require_auth
async def search_events_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """이벤트 검색 대화를 시작하고 키워드를 요청합니다."""

    # --- CalDAV 설정 확인 ---
    if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
        # !!!!! 수정: query/message 구분하여 응답 !!!!!
        reply_target = update.callback_query.message if update.callback_query else update.message
        if reply_target:
            try:
                # 콜백에서 호출될 수도 있으므로 edit_message_text도 고려 가능하나,
                # 여기서는 새 메시지 전송이 더 일반적일 수 있음.
                await reply_target.reply_text("캘린더(CalDAV) 설정이 필요합니다.")
            except Exception as e:
                logger.error(f"Failed to send CalDAV config error message in search_events_start: {e}")
        return ConversationHandler.END
    # ------------------------

    logger.info(f"User {update.effective_user.first_name} initiated /search_events conversation.")
    await _clear_other_conversations(context, []) # 다른 대화 데이터 정리

    # !!!!! 수정: query/message 구분하여 응답 !!!!!
    reply_target = update.callback_query.message if update.callback_query else update.message
    if reply_target:
        try:
            await reply_target.reply_text(
                "🔎 어떤 키워드로 일정을 검색하시겠어요?\n"
                "검색할 단어를 입력해주세요.\n\n"
                "취소하려면 /cancel 을 입력하세요."
            )
        except Exception as e:
             logger.error(f"Failed to send search prompt message in search_events_start: {e}")
             return ConversationHandler.END # 메시지 전송 실패 시 대화 종료
    else: # 메시지 객체가 없는 예외적 상황
        logger.error("Could not find message object to reply to in search_events_start.")
        return ConversationHandler.END

    return SearchEventsStates.WAITING_KEYWORD

# --- search_events_start 함수 끝 ---

# --- /search_events 관련 핸들러 ---
@check_ban
@require_auth
async def search_events_keyword_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """사용자로부터 키워드를 받아 이벤트를 검색하고 결과를 보여줍니다."""

    # !!!!! 이 부분이 중요합니다 !!!!!
    if not update.message or not update.message.text:
        logger.warning("search_events_keyword_received: Received update without message text.")
        await update.message.reply_text("오류: 검색어를 받지 못했습니다. 다시 시도해주세요.")
        return SearchEventsStates.WAITING_KEYWORD

    keyword = update.message.text.strip() # 사용자 입력 텍스트를 keyword 변수에 할당
    # !!!!! 여기까지 !!!!!

    if not keyword:
        await update.message.reply_text("검색할 키워드를 입력해주세요.")
        return SearchEventsStates.WAITING_KEYWORD

    logger.info(f"User {update.effective_user.first_name} searching events with keyword: {keyword}")

    # --- CalDAV 설정 확인 ---
    if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
        await update.message.reply_text("캘린더(CalDAV) 설정이 필요합니다.")
        return ConversationHandler.END
    # ------------------------

    # 검색 기간 설정
    start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=90)
    period_str = f"{start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}"

    processing_msg = await update.message.reply_text(f"🔎 '{html.escape(keyword)}' 키워드로 {period_str} 기간의 일정 검색 중...")
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning(f"Could not send typing action for /search_events: {e}")

    # --- helpers 함수 호출 ---
    success, result_or_error = await asyncio.to_thread(
        helpers.search_caldav_events_by_keyword,
        config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD,
        keyword, start_dt, end_dt
    )

    response_html = ""
    if success:
        # ... (결과 포맷팅 로직은 이전과 동일하게 유지) ...
        if isinstance(result_or_error, str):
            response_html = result_or_error
        elif isinstance(result_or_error, list) and result_or_error:
            found_events = result_or_error
            response_html = f"🔎 <b>'{html.escape(keyword)}'</b> 키워드 검색 결과 ({len(found_events)}개, {period_str}):\n"
            events_by_date: Dict[str, List[Dict[str, Any]]] = {}
            for event in found_events:
                event_date_str = "Unknown Date"
                start_str = event.get('start_str')
                if start_str:
                    try:
                        event_date = datetime.strptime(start_str.split()[0], '%Y-%m-%d').date()
                        event_date_str = event_date.strftime('%Y-%m-%d (%a)')
                    except (ValueError, IndexError):
                        event_date_str = start_str.split()[0] if start_str else "날짜 정보 없음"
                else: event_date_str = "날짜 정보 없음"
                if event_date_str not in events_by_date: events_by_date[event_date_str] = []
                events_by_date[event_date_str].append(event)
            for event_date_str in sorted(events_by_date.keys()):
                response_html += f"\n<b>{event_date_str}</b>\n"
                for event in events_by_date[event_date_str]:
                    summary = event.get('summary', '제목 없음'); is_allday = event.get('is_allday', False)
                    start_str_ev = event.get('start_str'); end_str_ev = event.get('end_str')
                    start_time_str = event.get('start_time_str'); end_time_str = event.get('end_time_str')
                    response_html += f"  • <b>{html.escape(summary)}</b>"
                    if is_allday:
                        response_html += " (종일) ☀️"
                        if end_str_ev and start_str_ev and end_str_ev != start_str_ev:
                            response_html += f"\n    <pre>  기간: {html.escape(start_str_ev)} ~ {html.escape(end_str_ev)}</pre>"
                    else:
                        response_html += " ✨"
                        time_info = start_time_str if start_time_str else ''
                        if end_time_str: time_info += f" ~ {end_time_str}"
                        if time_info: response_html += f"\n    <pre>  ⏰ {html.escape(time_info)}</pre>"
                    response_html += "\n"
        elif isinstance(result_or_error, list) and not result_or_error:
             response_html = f"🤷 '{html.escape(keyword)}' 키워드를 포함하는 일정을 찾을 수 없습니다 ({period_str})."
        else:
            logger.error(f"Unexpected result type from helpers.search_caldav_events_by_keyword: {type(result_or_error)}")
            response_html = "❌ 일정 검색 결과를 처리하는 중 오류가 발생했습니다."
    else:
        logger.error(f"/search_events failed for keyword '{keyword}'. Original error: {result_or_error}")
        response_html = f"❌ 일정 검색 중 오류 발생: {html.escape(str(result_or_error))}"

    # 메시지 길이 제한 처리
    if len(response_html.encode('utf-8')) > 4096:
        response_html = response_html[:4000] + "...\n\n(검색 결과가 너무 많아 일부만 표시합니다.)"

    # 결과 메시지 전송
    try:
        await processing_msg.edit_text(response_html, parse_mode='HTML')
    except Exception as edit_err:
        logger.error(f"Failed to edit message for /search_events: {edit_err}")
        try:
            await update.message.reply_html(response_html)
        except Exception as send_err:
            logger.error(f"Error sending /search_events result HTML: {send_err}")
            await update.message.reply_text("검색 결과 표시 중 오류가 발생했습니다.")

    return ConversationHandler.END

# ------------------------------------------

# handlers.py - addevent_start 함수 전체

@check_ban
@require_auth
async def addevent_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """새 이벤트 추가 대화를 시작하고 캘린더 목록을 보여줍니다."""

    # --- CalDAV 설정 확인 ---
    if not config.CALDAV_URL or not config.CALDAV_USERNAME or not config.CALDAV_PASSWORD:
        await update.message.reply_text("캘린더(CalDAV) 설정이 필요합니다.")
        return ConversationHandler.END
    # ------------------------

    logger.info(f"User {update.effective_user.first_name} initiated /addevent conversation.")
    await _clear_other_conversations(context, ['new_event_details']) # 다른 대화 정리, 새 이벤트 정보는 유지
    context.user_data['new_event_details'] = {} # 새 이벤트 정보 저장용 딕셔너리 초기화

    # --- 사용 가능한 캘린더 목록 가져오기 ---
    processing_msg = await update.message.reply_text("📅 캘린더 목록 가져오는 중...")
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        # helpers.get_calendars 함수 호출 (이 함수는 helpers.py 에 있어야 함)
        success, calendars_or_error = await asyncio.to_thread(
             helpers.get_calendars, config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD
        )

        if success and isinstance(calendars_or_error, list):
            calendars = calendars_or_error # 캘린더 딕셔너리 리스트 ({'name': '...', 'url': '...'})
            if not calendars:
                await processing_msg.edit_text("접근 가능한 캘린더가 없습니다.")
                return ConversationHandler.END

            # !!!!! 수정: 사용자가 선택할 캘린더 정보를 user_data에 임시 저장 !!!!!
            # 캘린더 이름이 너무 길거나 특수문자가 많으면 문제가 될 수 있으므로 주의
            # 여기서는 간단히 이름:URL 딕셔너리로 저장
            available_calendars_data = {cal['name']: cal['url'] for cal in calendars if cal.get('name') and cal.get('url')}
            context.user_data['_available_calendars'] = available_calendars_data
            if not available_calendars_data: # 이름이나 URL이 없는 캘린더만 있었을 경우
                 logger.warning("No calendars with valid names and URLs found.")
                 await processing_msg.edit_text("사용 가능한 캘린더 정보를 찾을 수 없습니다.")
                 return ConversationHandler.END

            logger.debug(f"Stored available calendars in user_data: {context.user_data['_available_calendars']}")

            # 인라인 키보드 생성
            keyboard = []
            # 저장된 데이터의 key(캘린더 이름)를 사용
            for cal_name in available_calendars_data.keys():
                # !!!!! 수정: callback_data 에 URL 대신 캘린더 이름 사용 !!!!!
                # 64바이트 제한을 고려하여 너무 긴 이름은 잘라냄 (40자 예시)
                # 콜백 데이터는 접두사 + 구분자 + 인코딩된 이름 일부 등 더 안전한 방식 고려 가능
                callback_data = f"addevent_cal_name_{cal_name[:40]}"
                keyboard.append([InlineKeyboardButton(f"📅 {cal_name}", callback_data=callback_data)])

            # 취소 버튼 추가
            keyboard.append([InlineKeyboardButton("🚫 취소", callback_data="addevent_cancel")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await processing_msg.edit_text(
                "어떤 캘린더에 새 일정을 추가하시겠어요?",
                reply_markup=reply_markup
            )
            return AddEventStates.SELECT_CALENDAR # 다음 상태: 캘린더 선택 대기

        else: # 캘린더 목록 가져오기 실패
            error_message = calendars_or_error if isinstance(calendars_or_error, str) else "캘린더 목록 조회 오류"
            logger.error(f"Failed to get calendar list for /addevent: {error_message}")
            # !!!!! 수정: 오류 발생 시 기존 메시지 수정 시도 및 예외 처리 강화 !!!!!
            try:
                await processing_msg.edit_text(f"❌ 캘린더 목록을 가져오는 데 실패했습니다: {error_message}")
            except telegram.error.BadRequest as e:
                 # edit_text 실패 시 (예: 메시지 찾을 수 없음) 새 메시지 전송 시도
                 logger.error(f"Failed to edit message in addevent_start error handler: {e}")
                 await update.message.reply_text(f"❌ 캘린더 목록을 가져오는 데 실패했습니다: {error_message}")
            except Exception as e: # 기타 예외
                 logger.error(f"Unexpected error editing message in addevent_start error handler: {e}")
                 # 최후의 수단
                 await update.message.reply_text("❌ 캘린더 목록 조회 중 오류가 발생했습니다.")

            return ConversationHandler.END

    except Exception as e:
        logger.exception("Error starting /addevent conversation")
        # !!!!! 수정: 오류 발생 시 기존 메시지 수정 시도 및 예외 처리 강화 !!!!!
        try:
            await processing_msg.edit_text("❌ 캘린더 목록 조회 중 오류가 발생했습니다.")
        except telegram.error.BadRequest as e:
            logger.error(f"Failed to edit message in addevent_start main exception handler: {e}")
            await update.message.reply_text("❌ 캘린더 목록 조회 중 오류가 발생했습니다.")
        except Exception as e:
            logger.error(f"Unexpected error editing message in addevent_start main exception handler: {e}")
            await update.message.reply_text("❌ 캘린더 목록 조회 중 오류가 발생했습니다.")
        return ConversationHandler.END

# handlers.py - addevent_calendar_selected 함수 전체

@check_ban
@require_auth
async def addevent_calendar_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """캘린더 선택 버튼 콜백을 처리하고 제목 입력을 요청합니다."""
    query = update.callback_query
    if not query: return ConversationHandler.END # 콜백 쿼리 없으면 종료

    try:
        await query.answer() # 버튼 로딩 표시 제거
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    callback_data = query.data

    # 취소 버튼 처리
    if callback_data == "addevent_cancel":
        logger.info("User cancelled /addevent at calendar selection.")
        try: await query.edit_message_text("일정 추가가 취소되었습니다.")
        except Exception as e: logger.error(f"Error editing message on cancel: {e}")
        # 임시 데이터 정리
        if '_available_calendars' in context.user_data: del context.user_data['_available_calendars']
        if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
        return ConversationHandler.END

    # 캘린더 선택 처리
    if callback_data.startswith("addevent_cal_name_"):
        selected_calendar_name_prefix = callback_data[len("addevent_cal_name_"):]

        # user_data 에서 캘린더 목록 가져오기
        available_calendars = context.user_data.get('_available_calendars')
        if not available_calendars:
            logger.error("'_available_calendars' not found in user_data (calendar selection).")
            try: await query.edit_message_text("오류: 캘린더 정보를 찾을 수 없습니다. 다시 /addevent 를 시작해주세요.")
            except Exception as e: logger.error(f"Error editing message on missing calendar data: {e}")
            if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
            return ConversationHandler.END

        # callback_data 와 일치하는 캘린더 이름과 URL 찾기
        selected_calendar_name = None
        selected_calendar_url = None
        for name, url in available_calendars.items():
             # callback_data 생성 시 사용한 길이(40)만큼 비교하여 정확도 높임
             if name[:40] == selected_calendar_name_prefix:
                 selected_calendar_name = name
                 selected_calendar_url = url
                 break

        if not selected_calendar_url:
            logger.error(f"Could not find calendar URL for name prefix: {selected_calendar_name_prefix}")
            try: await query.edit_message_text("오류: 선택한 캘린더 정보를 찾을 수 없습니다. 다시 /addevent 를 시작해주세요.")
            except Exception as e: logger.error(f"Error editing message on URL not found: {e}")
            # 임시 데이터 정리
            if '_available_calendars' in context.user_data: del context.user_data['_available_calendars']
            if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
            return ConversationHandler.END

        # 찾은 URL과 이름을 이벤트 상세 정보에 저장
        if 'new_event_details' not in context.user_data: context.user_data['new_event_details'] = {}
        context.user_data['new_event_details']['calendar_url'] = selected_calendar_url
        context.user_data['new_event_details']['calendar_name'] = selected_calendar_name # 이름도 저장

        # 임시 캘린더 목록 데이터 삭제
        if '_available_calendars' in context.user_data: del context.user_data['_available_calendars']

        logger.info(f"User selected calendar: Name='{selected_calendar_name}', URL='{selected_calendar_url}'")

        # 제목 입력 요청 메시지 전송 (메시지 수정 시도)
        try:
            await query.edit_message_text(
                f"🗓️ 선택된 캘린더: <b>{html.escape(selected_calendar_name)}</b>\n\n"
                "✏️ 추가할 일정의 <b>제목</b>을 입력해주세요.\n\n"
                "취소하려면 /cancel",
                parse_mode='HTML'
            )
        except telegram.error.BadRequest as e:
            # 수정 실패 시 (예: 메시지가 너무 오래됨) 새 메시지로 보냄
            logger.warning(f"Failed to edit message after calendar selection (BadRequest: {e}), sending new message.")
            try:
                await context.bot.send_message(
                     chat_id=query.message.chat_id,
                     text=f"🗓️ 선택된 캘린더: <b>{html.escape(selected_calendar_name)}</b>\n\n"
                          "✏️ 추가할 일정의 <b>제목</b>을 입력해주세요.\n\n"
                          "취소하려면 /cancel",
                     parse_mode='HTML'
                )
            except Exception as send_err:
                logger.error(f"Failed to send new message for title prompt: {send_err}")
        except Exception as e: # 기타 수정 오류
             logger.error(f"Unexpected error editing message after calendar selection: {e}")
             # 최후의 수단: 새 메시지 전송
             try:
                 await context.bot.send_message(
                     chat_id=query.message.chat_id,
                     text="✏️ 추가할 일정의 <b>제목</b>을 입력해주세요.\n\n취소하려면 /cancel",
                     parse_mode='HTML'
                 )
             except Exception as send_err:
                 logger.error(f"Also failed to send new message for title prompt: {send_err}")


        return AddEventStates.WAITING_TITLE # 다음 상태: 제목 입력 대기
    else:
        logger.warning(f"Received unknown callback in addevent_calendar_selected: {callback_data}")
        try: await query.edit_message_text("알 수 없는 선택입니다. 다시 /addevent 를 시작해주세요.")
        except Exception as e: logger.error(f"Error editing message on unknown callback: {e}")
        # 임시 데이터 정리
        if '_available_calendars' in context.user_data: del context.user_data['_available_calendars']
        if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
        return ConversationHandler.END

# handlers.py - /addevent 관련 핸들러 섹션

async def addevent_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """사용자로부터 제목을 입력받아 저장하고, 시작 날짜/시간 입력을 요청합니다."""
    if not update.message or not update.message.text: # 혹시 모를 오류 방지
        return AddEventStates.WAITING_TITLE # 예상치 못한 입력 시 제목 다시 요청

    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("✏️ 일정 제목은 비워둘 수 없습니다. 다시 입력해주세요.")
        return AddEventStates.WAITING_TITLE # 제목 다시 입력 상태 유지

    if 'new_event_details' not in context.user_data: # 이전 단계 데이터 유실 시
        logger.error("User data 'new_event_details' missing in addevent_title_received.")
        await update.message.reply_text("오류가 발생했습니다. /addevent 를 다시 시작해주세요.")
        return ConversationHandler.END

    context.user_data['new_event_details']['summary'] = title
    logger.info(f"Received event title: {title}")

    # 시작 날짜/시간 입력 요청
    await update.message.reply_text(
        f"✔️ 제목: {html.escape(title)}\n\n"
        "🗓️ 일정 <b>시작 날짜와 시간</b>을 입력해주세요.\n\n"
        "<b>형식 예시:</b>\n"
        "- 오늘 오후 3시: <code>오늘 15:00</code> 또는 <code>now 15:00</code>\n"
        "- 내일 오전 9시 30분: <code>내일 09:30</code>\n"
        "- 특정 날짜: <code>2024-12-25 10:00</code>\n"
        "- 종일 일정: <code>2024-12-26</code> 또는 <code>내일</code> (시간 없이 날짜만)\n\n"
        "취소하려면 /cancel",
        parse_mode='HTML'
    )
    return AddEventStates.WAITING_START # 다음 상태: 시작 날짜/시간 입력 대기           

# handlers.py - /addevent 관련 핸들러 섹션

# (addevent_title_received 함수 아래에 추가)

async def addevent_start_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """시작 날짜/시간 입력을 받아 파싱하고, 종료 시간 또는 종일 여부를 묻습니다."""
    if not update.message or not update.message.text:
        return AddEventStates.WAITING_START

    start_input = update.message.text.strip()
    logger.info(f"Received start date/time input: {start_input}")

    if 'new_event_details' not in context.user_data:
        logger.error("User data 'new_event_details' missing in addevent_start_received.")
        await update.message.reply_text("오류 발생. /addevent 다시 시작.")
        return ConversationHandler.END

    # --- 입력된 날짜/시간 문자열 파싱 시도 ---
    parsed_start_dt: Optional[Union[datetime, date]] = None
    is_allday_event = False
    today = date.today()
    now = datetime.now() # 현재 시간도 참고

    try:
        # 1. "오늘 HH:MM" 또는 "now HH:MM" 형식 (시간 포함)
        match_today_time = re.fullmatch(r"(?:오늘|now)\s+(\d{1,2}):(\d{2})", start_input, re.IGNORECASE)
        if match_today_time:
            hour, minute = map(int, match_today_time.groups())
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                parsed_start_dt = datetime.combine(today, time(hour, minute))
                logger.debug(f"Parsed as 'today HH:MM': {parsed_start_dt}")

        # 2. "내일 HH:MM" 형식 (시간 포함)
        elif re.match(r"내일\s+(\d{1,2}):(\d{2})", start_input, re.IGNORECASE):
             match_tomorrow_time = re.fullmatch(r"내일\s+(\d{1,2}):(\d{2})", start_input, re.IGNORECASE)
             if match_tomorrow_time: # 안전하게 한 번 더 확인
                hour, minute = map(int, match_tomorrow_time.groups())
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    tomorrow = today + timedelta(days=1)
                    parsed_start_dt = datetime.combine(tomorrow, time(hour, minute))
                    logger.debug(f"Parsed as 'tomorrow HH:MM': {parsed_start_dt}")

        # 3. "YYYY-MM-DD HH:MM" 형식 (시간 포함)
        elif re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})", start_input):
             try:
                 parsed_start_dt = datetime.strptime(start_input, "%Y-%m-%d %H:%M")
                 logger.debug(f"Parsed as 'YYYY-MM-DD HH:MM': {parsed_start_dt}")
             except ValueError: pass # 파싱 실패 시 다른 형식 시도

        # 4. "YYYY-MM-DD" 형식 (종일)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", start_input):
             try:
                 parsed_start_dt = datetime.strptime(start_input, "%Y-%m-%d").date()
                 is_allday_event = True
                 logger.debug(f"Parsed as 'YYYY-MM-DD' (allday): {parsed_start_dt}")
             except ValueError: pass

        # 5. "오늘" 또는 "now" (종일)
        elif start_input.lower() in ["오늘", "now"]:
             parsed_start_dt = today
             is_allday_event = True
             logger.debug(f"Parsed as 'today' (allday): {parsed_start_dt}")

        # 6. "내일" (종일)
        elif start_input.lower() == "내일":
             parsed_start_dt = today + timedelta(days=1)
             is_allday_event = True
             logger.debug(f"Parsed as 'tomorrow' (allday): {parsed_start_dt}")

        # --- 파싱 성공 여부 확인 ---
        if parsed_start_dt is None:
             raise ValueError("지원하지 않는 날짜/시간 형식")

        # 파싱된 시작 시간 저장
        context.user_data['new_event_details']['dtstart'] = parsed_start_dt
        context.user_data['new_event_details']['is_allday'] = is_allday_event

        # --- 종료 시간 또는 종일 여부 확인 요청 ---
        start_display = parsed_start_dt.strftime('%Y-%m-%d %H:%M') if isinstance(parsed_start_dt, datetime) else parsed_start_dt.strftime('%Y-%m-%d (종일)')
        title_display = context.user_data['new_event_details'].get('summary', '')

        reply_message = (
            f"✔️ 시작: {start_display}\n"
            f"✔️ 제목: {html.escape(title_display)}\n\n"
        )

        if is_allday_event:
             reply_message += (
                 "🗓️ 이 일정은 <b>종일</b> 일정입니다.\n"
                 "혹시 <b>다른 종료 날짜</b>를 원하시면 <code>YYYY-MM-DD</code> 형식으로 입력해주세요.\n"
                 "같은 날 종료면 '<b>종료일 없음</b>' 또는 '<b>-</b>'를 입력하세요.\n\n"
             )
        else: # 시간 지정 이벤트
             reply_message += (
                 "⏱️ 일정 <b>종료 날짜와 시간</b>을 입력해주세요.\n\n"
                 "<b>형식 예시:</b>\n"
                 "- 같은 날 오후 5시: <code>17:00</code>\n"
                 "- 다음 날 오전 10시: <code>내일 10:00</code>\n"
                 "- 특정 날짜/시간: <code>2024-12-25 18:00</code>\n"
                 "- 종료 시간 없으면 '<b>종료 없음</b>' 또는 '<b>-</b>' 입력\n\n"
             )

        reply_message += "취소하려면 /cancel"
        await update.message.reply_html(reply_message)

        return AddEventStates.WAITING_END_OR_ALLDAY # 다음 상태: 종료 정보 입력 대기

    except ValueError as e:
        logger.warning(f"Failed to parse start date/time input '{start_input}': {e}")
        await update.message.reply_text(
            f"😵 날짜/시간 형식을 이해하기 어렵습니다.\n"
            "지원하는 형식 예시를 참고하여 다시 입력해주세요:\n"
            "<code>오늘 15:00</code>, <code>내일 09:30</code>, <code>2024-12-25 10:00</code>, <code>2024-12-26</code>, <code>내일</code>\n\n"
            "취소하려면 /cancel",
            parse_mode='HTML'
        )
        return AddEventStates.WAITING_START # 시작 날짜/시간 입력 상태 유지
    except Exception as e:
        logger.exception(f"Unexpected error processing start date/time: {e}")
        await update.message.reply_text("오류 발생. /addevent 다시 시작.")
        if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
        return ConversationHandler.END

# handlers.py - /addevent 관련 핸들러 섹션

# ======[ 수정: addevent_end_received 함수 (종료 시간 파싱 추가) ]======
async def addevent_end_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    사용자로부터 종료 날짜/시간 또는 종일 여부 입력을 받고 최종적으로 CalDAV에 저장 시도.
    종료 시간 파싱 로직 추가됨.
    """
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id

    # --- 입력값 가져오기 ---
    end_input = ""
    if message and message.text:
        end_input = message.text.strip()
        logger.info(f"Received end date/time input from {user.first_name}: {end_input}")
    else:
         logger.warning("No message text found in addevent_end_received.")
         # 유효한 입력이 아니므로 다시 요청 (상태 유지)
         # await context.bot.send_message(chat_id, "오류: 입력 값을 받지 못했습니다. 다시 입력해주세요.")
         # return AddEventStates.WAITING_END_OR_ALLDAY # 상태 유지하며 재입력 요청
         # 또는 그냥 종료
         await context.bot.send_message(chat_id, "오류: 입력 값을 받지 못했습니다. /addevent 를 다시 시작해주세요.")
         if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
         return ConversationHandler.END


    # --- 필수 데이터 확인 ---
    if 'new_event_details' not in context.user_data or 'dtstart' not in context.user_data['new_event_details']:
        logger.error(f"User {user.id}: Missing 'new_event_details' or 'dtstart' in user_data at addevent_end_received.")
        await context.bot.send_message(chat_id, "오류가 발생했습니다. 일정 추가를 다시 시작해주세요. /addevent")
        if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
        return ConversationHandler.END

    event_details = context.user_data['new_event_details']
    is_allday_event = event_details.get('is_allday', False)
    parsed_start_dt: Union[datetime, date] = event_details['dtstart'] # 시작 날짜/시간은 반드시 있음

    # --- 종료 정보 파싱 로직 ---
    parsed_end_dt: Optional[Union[datetime, date]] = None
    skip_end_time = end_input.lower() in ['-', '종료 없음', '종료일 없음']

    if not skip_end_time:
        logger.debug(f"Attempting to parse end input: '{end_input}' (All-day: {is_allday_event})")
        today = date.today() # 오늘 날짜 다시 가져오기
        try:
            if is_allday_event:
                # 종일 이벤트: YYYY-MM-DD 형식의 종료 날짜 입력 기대
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end_input):
                    parsed_end_dt = datetime.strptime(end_input, "%Y-%m-%d").date()
                    # 유효성 검사: 종료 날짜는 시작 날짜보다 같거나 커야 함
                    if parsed_end_dt < parsed_start_dt:
                        logger.warning(f"Invalid end date: {parsed_end_dt} is before start date {parsed_start_dt}.")
                        await message.reply_text("❌ 종료 날짜는 시작 날짜보다 이전일 수 없습니다. 다시 입력해주세요.")
                        return AddEventStates.WAITING_END_OR_ALLDAY # 상태 유지
                    logger.debug(f"Parsed allday end date: {parsed_end_dt}")
                else:
                    raise ValueError("종일 일정의 종료 날짜는 YYYY-MM-DD 형식이어야 합니다.")

            else: # 시간 지정 이벤트
                # 1. HH:MM 형식 (같은 날)
                match_time_only = re.fullmatch(r"(\d{1,2}):(\d{2})", end_input)
                if match_time_only:
                    hour, minute = map(int, match_time_only.groups())
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        # 시작 날짜 가져오기 (datetime 객체여야 함)
                        start_date_part = parsed_start_dt.date() if isinstance(parsed_start_dt, datetime) else parsed_start_dt
                        parsed_end_dt = datetime.combine(start_date_part, time(hour, minute))
                        logger.debug(f"Parsed end time (same day): {parsed_end_dt}")

                # 2. 내일 HH:MM 형식
                elif re.match(r"내일\s+(\d{1,2}):(\d{2})", end_input, re.IGNORECASE):
                     match_tomorrow_time = re.fullmatch(r"내일\s+(\d{1,2}):(\d{2})", end_input, re.IGNORECASE)
                     if match_tomorrow_time:
                        hour, minute = map(int, match_tomorrow_time.groups())
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            start_date_part = parsed_start_dt.date() if isinstance(parsed_start_dt, datetime) else parsed_start_dt
                            tomorrow_date = start_date_part + timedelta(days=1) # 시작 날짜 기준 다음 날
                            parsed_end_dt = datetime.combine(tomorrow_date, time(hour, minute))
                            logger.debug(f"Parsed end time (tomorrow): {parsed_end_dt}")

                # 3. YYYY-MM-DD HH:MM 형식
                elif re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})", end_input):
                     parsed_end_dt = datetime.strptime(end_input, "%Y-%m-%d %H:%M")
                     logger.debug(f"Parsed end time (specific date): {parsed_end_dt}")

                else:
                     raise ValueError("지원하지 않는 종료 시간 형식입니다.")

                # 시간 지정 이벤트 유효성 검사: 종료 시간이 시작 시간보다 이전이면 안 됨
                if isinstance(parsed_start_dt, datetime) and parsed_end_dt <= parsed_start_dt:
                     logger.warning(f"Invalid end datetime: {parsed_end_dt} is not after start datetime {parsed_start_dt}.")
                     await message.reply_text("❌ 종료 시간은 시작 시간보다 이후여야 합니다. 다시 입력해주세요.")
                     return AddEventStates.WAITING_END_OR_ALLDAY # 상태 유지

        except ValueError as e:
            logger.warning(f"Failed to parse end input '{end_input}': {e}")
            # 사용자에게 오류 메시지 전송 및 재입력 요청
            error_message = f"😵 종료 날짜/시간 형식을 이해하기 어렵습니다: {e}\n\n"
            if is_allday_event:
                error_message += "종료 날짜(YYYY-MM-DD)를 입력하거나 '-'를 입력하세요."
            else:
                error_message += "종료 시간(HH:MM, 내일 HH:MM, YYYY-MM-DD HH:MM)을 입력하거나 '-'를 입력하세요."
            error_message += "\n\n취소하려면 /cancel"
            await message.reply_html(error_message)
            return AddEventStates.WAITING_END_OR_ALLDAY # 상태 유지

    else: # 사용자가 종료 시간을 건너뜀
        logger.info("User skipped end date/time.")
        parsed_end_dt = None # 종료 시간 없음 명시

    # 파싱된 종료 시간을 event_details에 저장
    event_details['dtend'] = parsed_end_dt # None일 수도 있음
    logger.debug(f"Final event details before saving: {event_details}")

    # --- 필수 정보 확인 (기존 로직 유지) ---
    required_keys = ['calendar_url', 'summary', 'dtstart']
    if not all(key in event_details for key in required_keys):
        missing_keys = [key for key in required_keys if key not in event_details]
        logger.error(f"User {user.id}: Missing required event details: {missing_keys}")
        await context.bot.send_message(chat_id, f"오류: 일정 정보가 부족합니다 ({', '.join(missing_keys)}). 다시 시도해주세요. /addevent")
        if 'new_event_details' in context.user_data: del context.user_data['new_event_details']
        return ConversationHandler.END

    # --- CalDAV 저장 시도 (기존 로직 유지, config 로딩 방식 수정) ---
    processing_msg = None
    try:
        processing_msg = await context.bot.send_message(chat_id, "⏳ 캘린더에 일정을 저장하는 중...")
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception as e:
        logger.error(f"Error sending 'saving' message or chat action: {e}")
        processing_msg = None

    success = False
    result_or_error = "오류: 초기화 실패"

    try:
        # config 모듈에서 CalDAV 정보 가져오기
        caldav_url_base = config.CALDAV_URL
        caldav_username = config.CALDAV_USERNAME
        caldav_password = config.CALDAV_PASSWORD
        if not caldav_url_base or not caldav_username or not caldav_password:
             raise ValueError("CalDAV 설정(URL, 사용자 이름, 비밀번호) 로드 실패.")

        # helpers.add_caldav_event 호출
        caldav_result = await asyncio.to_thread(
            helpers.add_caldav_event,
            caldav_url_base,
            caldav_username,
            caldav_password,
            event_details['calendar_url'],
            event_details # dtend 포함 가능
        )

        # 결과 처리 (기존과 동일)
        if isinstance(caldav_result, tuple) and len(caldav_result) == 2:
            success, result_or_error = caldav_result
            if not isinstance(success, bool): success = False; result_or_error = "CalDAV 반환값 형식 오류 (bool 아님)"
            if not isinstance(result_or_error, str): result_or_error = str(result_or_error)
        elif caldav_result is None: success = False; result_or_error = "CalDAV 함수가 None 반환"; logger.error("CalDAV helper returned None.")
        else: success = False; result_or_error = f"CalDAV 함수 반환값 형식 오류 ({type(caldav_result)})"; logger.error(f"Unexpected return type from CalDAV helper: {type(caldav_result)}, value: {caldav_result}")

    except ValueError as ve: logger.error(f"CalDAV 설정 로딩 오류: {ve}"); success = False; result_or_error = f"설정 오류: {ve}"
    except Exception as e: logger.error(f"Error calling add_caldav_event: {e}", exc_info=True); success = False; result_or_error = f"일정 저장 중 오류: {type(e).__name__}"

    # --- 최종 결과 메시지 생성 및 전송 (기존 로직 유지) ---
    if success:
        summary_safe = html.escape(event_details.get('summary', 'N/A'))
        dtstart_obj = event_details.get('dtstart')
        dtstart_safe = html.escape(dtstart_obj.strftime('%Y-%m-%d %H:%M') if isinstance(dtstart_obj, datetime) else dtstart_obj.strftime('%Y-%m-%d') if isinstance(dtstart_obj, date) else 'N/A')
        final_message = f"✅ 일정 저장 성공!\n\n<b>제목:</b> {summary_safe}\n<b>시작:</b> {dtstart_safe}"
        if event_details.get('is_allday'): final_message += " (종일)"
        dtend_obj = event_details.get('dtend')
        if dtend_obj:
            dtend_safe = html.escape(dtend_obj.strftime('%Y-%m-%d %H:%M') if isinstance(dtend_obj, datetime) else dtend_obj.strftime('%Y-%m-%d') if isinstance(dtend_obj, date) else str(dtend_obj))
            final_message += f"\n<b>종료:</b> {dtend_safe}"
        if isinstance(result_or_error, str) and result_or_error and result_or_error.startswith("✅"): final_message += f"\n\n<i>{html.escape(result_or_error)}</i>"
    else:
        final_message = f"❌ 일정 저장 중 오류가 발생했습니다.\n\n<b>오류:</b> {html.escape(result_or_error)}"

    if processing_msg:
        try: await context.bot.edit_message_text(text=final_message, chat_id=chat_id, message_id=processing_msg.message_id, parse_mode=ParseMode.HTML)
        except Exception as e: logger.error(f"Error editing final status message: {e}"); await context.bot.send_message(chat_id, final_message, parse_mode=ParseMode.HTML)
    else:
        try: await context.bot.send_message(chat_id, final_message, parse_mode=ParseMode.HTML)
        except Exception as final_e: logger.error(f"Error sending final status message: {final_e}")

    # --- 대화 종료 및 데이터 정리 ---
    if 'new_event_details' in context.user_data:
        try: del context.user_data['new_event_details']; logger.debug("Cleaned up 'new_event_details'.")
        except KeyError: pass
    return ConversationHandler.END
# =====================================================================

# handlers.py 파일 내 (다른 핸들러 함수들과 분리된 곳에 추가)

from telegram import ChatMemberUpdated
from telegram.constants import ChatMemberStatus, ChatType

# ======[ 봇 퇴장 알림 핸들러 추가 ]======
async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """봇 자신의 채팅 멤버 상태 변경(특히 그룹 퇴장)을 감지하고 관리자에게 알립니다."""
    if not update.my_chat_member:
        # 이 핸들러는 my_chat_member 업데이트만 처리해야 함
        return

    # 상태 변경 정보 추출
    chat_member_update: ChatMemberUpdated = update.my_chat_member
    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status
    chat = chat_member_update.chat

    logger.info(f"Bot's chat member status changed in chat {chat.id} ('{chat.title}'): {old_status} -> {new_status}")

    # 봇이 그룹/슈퍼그룹에서 나갔거나(left) 추방되었을 때(kicked) 알림
    if (chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and
            new_status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED] and
            old_status not in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]): # 상태 변경 시에만 알림 (중복 방지)

        logger.warning(f"Bot was removed or left the chat: ID={chat.id}, Title='{chat.title}', Type={chat.type}, New Status={new_status}")

        admin_id = config.ADMIN_CHAT_ID
        if admin_id:
            try:
                admin_id_int = int(admin_id)
                message = (f"⚠️ <b>봇 퇴장 알림</b> ⚠️\n\n"
                           f"봇이 다음 그룹 채팅방에서 나갔거나 추방되었습니다:\n"
                           f" - 이름: <b>{html.escape(chat.title)}</b>\n"
                           f" - ID: <code>{chat.id}</code>\n"
                           f" - 타입: {chat.type}\n"
                           f" - 최종 상태: {new_status}")
                await context.bot.send_message(chat_id=admin_id_int, text=message, parse_mode=ParseMode.HTML)
                logger.info(f"Bot left/kicked notification sent to admin ({admin_id}) for chat {chat.id}.")
            except (ValueError, TypeError) as e:
                 logger.error(f"ADMIN_CHAT_ID ({admin_id}) is not a valid integer: {e}")
            except Forbidden:
                 logger.error(f"Bot is blocked by the admin ({admin_id}). Cannot send bot left notification.")
            except Exception as e:
                 logger.error(f"Failed to send bot left notification to admin ({admin_id}): {e}")
        else:
            logger.warning("ADMIN_CHAT_ID not set. Cannot send bot left notification.")

# ======================================

@check_ban
@require_auth
@require_admin # 관리자만 사용 가능하도록 설정 (필요에 따라 제거 가능)
async def deleteevent_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """이벤트 삭제 대화를 시작하고 삭제 방법 선택 버튼을 보여줍니다."""
    user = update.effective_user
    logger.info(f"User {user.first_name} (ID: {user.id}) initiated /deleteevent conversation.")
    await _clear_other_conversations(context, ['event_to_delete', 'search_results_for_delete']) # 관련 데이터만 정리

    keyboard = [
        [InlineKeyboardButton("📅 최근 일정에서 선택", callback_data="delete_event_recent")],
        [InlineKeyboardButton("🔎 키워드로 검색하여 선택", callback_data="delete_event_search")],
        [InlineKeyboardButton("🚫 취소", callback_data="delete_event_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🗑️ 어떤 방법으로 삭제할 일정을 찾으시겠습니까?",
        reply_markup=reply_markup
    )
    return DeleteEventStates.SELECT_METHOD

async def deleteevent_method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """삭제 방법 선택 콜백을 처리합니다 (최근/검색/취소)."""
    query = update.callback_query
    if not query: return ConversationHandler.END
    await query.answer()
    callback_data = query.data
    chat_id = query.message.chat_id

    if callback_data == "delete_event_recent":
        logger.info("User chose 'recent' method for deletion.")
        await query.edit_message_text("📅 최근 일정을 가져오는 중...")
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # 최근 이벤트 N개 가져오기 (예: 30일치 검색 후 10개 표시)
        try:
            today = date.today()
            start_dt = datetime.combine(today - timedelta(days=30), time.min) # 예: 지난 30일
            end_dt = datetime.combine(today + timedelta(days=7), time.max) # 예: 앞으로 7일
            success, events_or_error = await asyncio.to_thread(
                helpers.fetch_caldav_events, start_dt, end_dt,
                config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD
            )

            if success and isinstance(events_or_error, list):
                recent_events = events_or_error[:15] # 예: 최대 15개만 표시
                if not recent_events:
                    await query.edit_message_text("최근 기간 내에 삭제할 만한 일정이 없습니다.")
                    return ConversationHandler.END

                keyboard = []
                # 삭제할 이벤트 후보를 저장 (URL 또는 UID 필요 - helpers.fetch_caldav_events 수정 필요)
                # 임시로 이벤트 요약과 시작 시간 조합을 context에 저장하고, 선택 시 다시 찾아야 할 수도 있음
                # 여기서는 helpers.fetch_caldav_events가 각 이벤트의 'url' 또는 'uid' 와 'calendar_url' 을 반환한다고 가정
                # context.user_data['events_for_deletion'] = {f"del_{i}": {'url': event['url'], 'summary': event['summary']} for i, event in enumerate(recent_events)}

                # **** 임시: fetch_caldav_events가 상세 URL 반환하지 않는 경우 대비 ****
                # 삭제 시 UID와 Calendar URL이 필요할 수 있으므로, 검색 결과를 저장
                context.user_data['search_results_for_delete'] = events_or_error
                delete_options = {} # callback_data : 표시 텍스트

                for i, event in enumerate(recent_events):
                    # 콜백 데이터에는 인덱스만 저장 (길이 제한 고려)
                    callback_key = f"delete_event_idx_{i}"
                    # 표시 텍스트에는 날짜와 요약 포함
                    display_text = f"{event.get('start_str', '')[:10]} - {event.get('summary', 'N/A')[:20]}"
                    # keyboard.append([InlineKeyboardButton(display_text, callback_data=callback_key)])
                    delete_options[callback_key] = display_text

                # 키보드 생성 (페이지네이션 필요시 추가 구현)
                keyboard = [[InlineKeyboardButton(text, callback_data=key)] for key, text in delete_options.items()]
                keyboard.append([InlineKeyboardButton("🚫 취소", callback_data="delete_event_cancel")])
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text("삭제할 일정을 선택하세요:", reply_markup=reply_markup)
                return DeleteEventStates.SELECT_EVENT

            else: # 조회 실패
                 error_msg = events_or_error if isinstance(events_or_error, str) else "최근 일정 조회 실패"
                 await query.edit_message_text(f"❌ 오류: {error_msg}")
                 return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error fetching recent events for deletion: {e}", exc_info=True)
            await query.edit_message_text("❌ 최근 일정 조회 중 오류 발생.")
            return ConversationHandler.END

    elif callback_data == "delete_event_search":
        logger.info("User chose 'search' method for deletion.")
        await query.edit_message_text("🔎 삭제할 일정의 검색 키워드를 입력하세요:")
        return DeleteEventStates.WAITING_KEYWORD

    elif callback_data == "delete_event_cancel":
        logger.info("User cancelled /deleteevent.")
        await query.edit_message_text("일정 삭제가 취소되었습니다.")
        return ConversationHandler.END

    else: # 알 수 없는 콜백
        logger.warning(f"Unknown callback in deleteevent_method_selected: {callback_data}")
        await query.edit_message_text("알 수 없는 선택입니다.")
        return ConversationHandler.END

async def deleteevent_keyword_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """키워드를 받아 이벤트를 검색하고 선택 버튼을 보여줍니다."""
    if not update.message or not update.message.text:
        # await update.message.reply_text("검색 키워드를 입력해주세요.")
        return DeleteEventStates.WAITING_KEYWORD # 키워드 다시 입력 대기

    keyword = update.message.text.strip()
    if not keyword:
        await update.message.reply_text("검색 키워드를 입력해주세요.")
        return DeleteEventStates.WAITING_KEYWORD

    logger.info(f"User searching for event to delete with keyword: {keyword}")
    await update.message.reply_text(f"🔎 '{html.escape(keyword)}' 검색 중...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # 검색 기간 설정 (예: 앞으로 1년)
    start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=365)

    try:
        success, events_or_error = await asyncio.to_thread(
            helpers.search_caldav_events_by_keyword, # 키워드 검색 함수 사용
            config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD,
            keyword, start_dt, end_dt
        )

        if success and isinstance(events_or_error, list):
            found_events = events_or_error[:15] # 예: 최대 15개 결과 표시
            if not found_events:
                await update.message.reply_text(f"🤷 '{html.escape(keyword)}' 키워드를 포함하는 일정을 찾을 수 없습니다.")
                return ConversationHandler.END

            # 검색 결과 저장 및 선택 버튼 생성 (최근 일정과 유사)
            context.user_data['search_results_for_delete'] = events_or_error
            delete_options = {}
            for i, event in enumerate(found_events):
                callback_key = f"delete_event_idx_{i}"
                display_text = f"{event.get('start_str', '')[:10]} - {event.get('summary', 'N/A')[:20]}"
                delete_options[callback_key] = display_text

            keyboard = [[InlineKeyboardButton(text, callback_data=key)] for key, text in delete_options.items()]
            keyboard.append([InlineKeyboardButton("🚫 취소", callback_data="delete_event_cancel")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text("삭제할 일정을 선택하세요:", reply_markup=reply_markup)
            return DeleteEventStates.SELECT_EVENT

        else: # 검색 실패
            error_msg = events_or_error if isinstance(events_or_error, str) else "키워드 검색 실패"
            await update.message.reply_text(f"❌ 오류: {error_msg}")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error searching events for deletion with keyword '{keyword}': {e}", exc_info=True)
        await update.message.reply_text("❌ 일정 검색 중 오류 발생.")
        return ConversationHandler.END

async def deleteevent_event_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """삭제할 이벤트 선택 콜백을 처리하고 최종 확인을 요청합니다."""
    query = update.callback_query
    if not query: return ConversationHandler.END
    await query.answer()
    callback_data = query.data

    if callback_data == "delete_event_cancel":
        logger.info("User cancelled event selection for deletion.")
        await query.edit_message_text("일정 삭제가 취소되었습니다.")
        if 'search_results_for_delete' in context.user_data: del context.user_data['search_results_for_delete']
        return ConversationHandler.END

    if callback_data.startswith("delete_event_idx_"):
        try:
            selected_index = int(callback_data.split("_")[-1])
            search_results = context.user_data.get('search_results_for_delete')

            if not search_results or selected_index >= len(search_results):
                raise IndexError("Invalid index or search results not found.")

            event_to_delete_info = search_results[selected_index]

            # !!!!! 중요: 삭제를 위해 이벤트의 고유 식별자(URL 또는 UID+CalendarURL)를 저장해야 함 !!!!!
            # helpers.fetch_caldav_events 나 helpers.search_caldav_events_by_keyword가
            # 각 이벤트 딕셔너리에 'url' 또는 'uid' 와 'calendar_url' 정보를 포함하도록 수정 필요.
            # 여기서는 event_to_delete_info 에 'url' 키가 있다고 가정함.
            event_url = event_to_delete_info.get('url')
            if not event_url:
                 # URL이 없다면 UID와 calendar_url을 찾아야 함 (복잡도 증가)
                 logger.error("Event URL not found in selected event data for deletion.")
                 await query.edit_message_text("오류: 삭제할 이벤트 정보를 식별할 수 없습니다.")
                 if 'search_results_for_delete' in context.user_data: del context.user_data['search_results_for_delete']
                 return ConversationHandler.END

            context.user_data['event_to_delete_url'] = event_url # 삭제할 URL 저장
            summary = event_to_delete_info.get('summary', 'N/A')
            start_str = event_to_delete_info.get('start_str', 'N/A')

            logger.info(f"User selected event for deletion: Index={selected_index}, Summary='{summary}', URL='{event_url}'")

            # 최종 확인 메시지
            keyboard = [
                [InlineKeyboardButton("✅ 예, 삭제합니다", callback_data="delete_event_confirm_yes")],
                [InlineKeyboardButton("❌ 아니요, 취소", callback_data="delete_event_confirm_no")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🗑️ 다음 일정을 정말로 삭제하시겠습니까?\n\n"
                f"<b>{html.escape(summary)}</b>\n"
                f"({html.escape(start_str)})\n\n"
                f"🚨 이 작업은 되돌릴 수 없습니다!",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            return DeleteEventStates.CONFIRM_DELETION

        except (ValueError, IndexError, KeyError) as e:
            logger.error(f"Error processing event selection for deletion: {e}", exc_info=True)
            await query.edit_message_text("오류: 잘못된 선택이거나 이전 정보가 없습니다.")
            if 'search_results_for_delete' in context.user_data: del context.user_data['search_results_for_delete']
            return ConversationHandler.END
    else:
        logger.warning(f"Unknown callback in deleteevent_event_selected: {callback_data}")
        await query.edit_message_text("알 수 없는 선택입니다.")
        return ConversationHandler.END

async def deleteevent_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """최종 삭제 확인 콜백을 처리하고 결과를 알립니다."""
    query = update.callback_query
    if not query: return ConversationHandler.END
    await query.answer()
    callback_data = query.data
    chat_id = query.message.chat_id

    event_url_to_delete = context.user_data.get('event_to_delete_url')

    if callback_data == "delete_event_confirm_yes":
        if not event_url_to_delete:
            logger.error("event_to_delete_url not found in user_data for deletion confirmation.")
            await query.edit_message_text("오류: 삭제할 이벤트 정보가 없습니다.")
            # 데이터 정리
            if 'event_to_delete_url' in context.user_data: del context.user_data['event_to_delete_url']
            if 'search_results_for_delete' in context.user_data: del context.user_data['search_results_for_delete']
            return ConversationHandler.END

        logger.warning(f"Deletion confirmed for event URL: {event_url_to_delete}")
        await query.edit_message_text("🗑️ 일정 삭제 중...")
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        try:
            # helpers.delete_caldav_event 호출 (URL 사용)
            success, result_or_error = await asyncio.to_thread(
                helpers.delete_caldav_event,
                config.CALDAV_URL, config.CALDAV_USERNAME, config.CALDAV_PASSWORD,
                event_url_to_delete # URL 직접 전달
            )
            final_message = result_or_error # helpers 함수의 결과 메시지 사용

        except Exception as e:
            logger.error(f"Error calling delete_caldav_event for URL '{event_url_to_delete}': {e}", exc_info=True)
            final_message = "❌ 일정 삭제 중 오류가 발생했습니다."

        await query.edit_message_text(final_message)

    elif callback_data == "delete_event_confirm_no":
        logger.info("User cancelled final deletion confirmation.")
        await query.edit_message_text("일정 삭제가 취소되었습니다.")

    else:
        logger.warning(f"Unknown callback in deleteevent_confirm_callback: {callback_data}")
        await query.edit_message_text("알 수 없는 응답입니다.")

    # 대화 종료 및 데이터 정리
    if 'event_to_delete_url' in context.user_data: del context.user_data['event_to_delete_url']
    if 'search_results_for_delete' in context.user_data: del context.user_data['search_results_for_delete']
    return ConversationHandler.END

# ======================================

# --- End of File ---