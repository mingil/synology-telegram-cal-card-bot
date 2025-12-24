# handlers/auth.py
import asyncio
import logging
from enum import IntEnum
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import config, database
from handlers.decorators import check_ban, require_auth, require_admin
from handlers.common import get_main_inline_keyboard, cancel_conversation

logger = logging.getLogger(__name__)

# --- 상태 정의 (대화형 처리를 위한 단계) ---
class AuthStates(IntEnum):
    WAITING_PASSWORD = 1

# 관리자 기능용 상태 (하나로 통합 관리)
class AdminStates(IntEnum):
    WAITING_BAN_INPUT = 1
    WAITING_UNBAN_INPUT = 2
    WAITING_PERMIT_INPUT = 3
    WAITING_REVOKE_INPUT = 4

# =========================================================================
#  1. 일반 인증 (기존 유지)
# =========================================================================

@check_ban
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> object:
    user = update.effective_user
    if not user: return ConversationHandler.END

    reply_markup = get_main_inline_keyboard()
    
    # 1. DB 허용 확인
    if await asyncio.to_thread(database.is_user_permitted, user.id):
        context.user_data['authenticated'] = True
        msg = f"✅ 환영합니다, <b>{user.mention_html()}</b>님! (인증됨)"
        await update.message.reply_html(msg, reply_markup=reply_markup)
        return ConversationHandler.END

    # 2. 신뢰된 사용자(config) 확인
    if user.id in config.TRUSTED_USER_IDS:
        context.user_data['authenticated'] = True
        await asyncio.to_thread(database.add_permitted_user, user.id)
        msg = f"✅ 신뢰된 사용자 자동 인증! <b>{user.mention_html()}</b>님!"
        await update.message.reply_html(msg, reply_markup=reply_markup)
        return ConversationHandler.END

    # 3. 현재 세션 확인
    if context.user_data.get('authenticated'):
        msg = f"👋 안녕하세요, <b>{user.mention_html()}</b>님! (세션 유효)"
        await update.message.reply_html(msg, reply_markup=reply_markup)
        return ConversationHandler.END

    # 4. 미인증 -> 비밀번호 요청
    if config.ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=f"🔔 <b>새 사용자 접근</b>\n{user.mention_html()} (ID: <code>{user.id}</code>)",
                parse_mode=ParseMode.HTML
            )
        except Exception: pass

    context.user_data['password_attempts'] = 0
    await update.message.reply_text("🔒 봇 사용을 위해 비밀번호를 입력해주세요:")
    return AuthStates.WAITING_PASSWORD

async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    password = update.message.text
    max_attempts = config.MAX_PASSWORD_ATTEMPTS

    if password == config.BOT_PASSWORD:
        context.user_data['authenticated'] = True
        context.user_data.pop('password_attempts', None)
        await asyncio.to_thread(database.add_permitted_user, user.id)
        
        if config.ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=config.ADMIN_CHAT_ID,
                    text=f"✅ <b>인증 성공</b>\n{user.mention_html()} (ID: {user.id})",
                    parse_mode=ParseMode.HTML
                )
            except Exception: pass

        await update.message.reply_html(
            f"✅ 인증 완료! 안녕하세요 <b>{user.mention_html()}</b>님!",
            reply_markup=get_main_inline_keyboard()
        )
        return ConversationHandler.END
    
    attempts = context.user_data.get('password_attempts', 0) + 1
    context.user_data['password_attempts'] = attempts
    
    if attempts >= max_attempts:
        await asyncio.to_thread(database.ban_user, user.id)
        await update.message.reply_text("🚫 비밀번호 입력 횟수 초과로 차단되었습니다.")
        if config.ADMIN_CHAT_ID:
             await context.bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=f"🚫 <b>차단 알림</b>\n{user.mention_html()} (ID: {user.id}) - 비번 틀림",
                parse_mode=ParseMode.HTML
            )
        return ConversationHandler.END
        
    await update.message.reply_text(f"❌ 비밀번호가 틀렸습니다. ({attempts}/{max_attempts})")
    return AuthStates.WAITING_PASSWORD

# =========================================================================
#  2. 관리자 조회 기능 (단순 명령어)
# =========================================================================

@check_ban
@require_auth
@require_admin
async def banlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    banned = await asyncio.to_thread(database.get_banned_users)
    msg = f"🛡️ <b>차단 목록</b> ({len(banned)}명)\n\n<pre>" + "\n".join(map(str, banned)) + "</pre>" if banned else "✅ 차단된 사용자가 없습니다."
    await update.message.reply_html(msg)

@check_ban
@require_auth
@require_admin
async def permitlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    permitted = await asyncio.to_thread(database.get_permitted_users)
    msg = f"✅ <b>허용 목록</b> ({len(permitted)}명)\n\n<pre>" + "\n".join(map(str, permitted)) + "</pre>" if permitted else "ℹ️ 허용 목록이 비었습니다."
    await update.message.reply_html(msg)

# =========================================================================
#  3. 관리자 액션 기능 (대화형으로 변경됨)
# =========================================================================

# --- A. 차단 (Ban) ---
@check_ban
@require_auth
@require_admin
async def ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_html("⛔ <b>사용자 차단</b>\n차단할 <b>ID(숫자)</b>를 입력해주세요.\n\n취소하려면 /cancel")
    return AdminStates.WAITING_BAN_INPUT

async def ban_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ 숫자로 된 ID만 입력 가능합니다. 다시 입력해주세요.")
        return AdminStates.WAITING_BAN_INPUT
    
    target_id = int(text)
    await asyncio.to_thread(database.ban_user, target_id)
    await asyncio.to_thread(database.revoke_permission, target_id)
    await update.message.reply_html(f"🚫 사용자 <code>{target_id}</code> 차단 및 권한 박탈 완료.")
    return ConversationHandler.END

# --- B. 차단 해제 (Unban) ---
@check_ban
@require_auth
@require_admin
async def unban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_html("🕊️ <b>차단 해제</b>\n해제할 <b>ID(숫자)</b>를 입력해주세요.\n\n취소하려면 /cancel")
    return AdminStates.WAITING_UNBAN_INPUT

async def unban_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ 숫자로 된 ID만 입력 가능합니다.")
        return AdminStates.WAITING_UNBAN_INPUT
    
    target_id = int(text)
    if await asyncio.to_thread(database.unban_user_db, target_id):
        await update.message.reply_html(f"✅ 사용자 <code>{target_id}</code> 차단 해제 완료.")
    else:
        await update.message.reply_text("⚠️ 차단 목록에 없는 ID입니다.")
    return ConversationHandler.END

# --- C. 권한 부여 (Permit) ---
@check_ban
@require_auth
@require_admin
async def permit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_html("✅ <b>권한 부여 (허용 목록 추가)</b>\n추가할 <b>ID(숫자)</b>를 입력해주세요.\n\n취소하려면 /cancel")
    return AdminStates.WAITING_PERMIT_INPUT

async def permit_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ 숫자로 된 ID만 입력 가능합니다.")
        return AdminStates.WAITING_PERMIT_INPUT
    
    target_id = int(text)
    await asyncio.to_thread(database.add_permitted_user, target_id)
    await asyncio.to_thread(database.unban_user_db, target_id) # 차단되어 있다면 해제
    await update.message.reply_html(f"✅ 사용자 <code>{target_id}</code> 권한 부여 완료.")
    return ConversationHandler.END

# --- D. 권한 취소 (Revoke) ---
@check_ban
@require_auth
@require_admin
async def revoke_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_html("🛑 <b>권한 취소 (허용 목록 제거)</b>\n제거할 <b>ID(숫자)</b>를 입력해주세요.\n\n취소하려면 /cancel")
    return AdminStates.WAITING_REVOKE_INPUT

async def revoke_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ 숫자로 된 ID만 입력 가능합니다.")
        return AdminStates.WAITING_REVOKE_INPUT
    
    target_id = int(text)
    if await asyncio.to_thread(database.revoke_permission, target_id):
        await update.message.reply_html(f"🛑 사용자 <code>{target_id}</code> 권한 취소 완료.")
    else:
        await update.message.reply_text("⚠️ 허용 목록에 없는 ID입니다.")
    return ConversationHandler.END