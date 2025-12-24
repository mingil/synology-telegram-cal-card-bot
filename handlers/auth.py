# handlers/auth.py
import asyncio
import logging
from enum import IntEnum
from telegram import Update

# [수정] ParseMode는 telegram.constants에서 가져와야 합니다.
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

# [변경] Core 모듈 사용
from core import config, database

from handlers.decorators import check_ban, require_auth, require_admin
from handlers.common import get_main_inline_keyboard

logger = logging.getLogger(__name__)


# 상태 정의
class AuthStates(IntEnum):
    WAITING_PASSWORD = 1


class UnbanStates(IntEnum):
    WAITING_TARGET_ID = 1


@check_ban
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> object:
    """봇 시작 및 인증 진입점"""
    user = update.effective_user
    if not user:
        return ConversationHandler.END

    reply_markup = get_main_inline_keyboard()

    # 1. DB 허용 확인 (비동기 래핑 권장)
    if await asyncio.to_thread(database.is_user_permitted, user.id):
        context.user_data["authenticated"] = True
        msg = f"✅ 환영합니다, <b>{user.mention_html()}</b>님! (인증됨)"
        await update.message.reply_html(msg, reply_markup=reply_markup)
        return ConversationHandler.END

    # 2. 신뢰된 사용자(config) 확인
    if user.id in config.TRUSTED_USER_IDS:
        context.user_data["authenticated"] = True
        await asyncio.to_thread(database.add_permitted_user, user.id)
        msg = f"✅ 신뢰된 사용자 자동 인증! <b>{user.mention_html()}</b>님!"
        await update.message.reply_html(msg, reply_markup=reply_markup)
        return ConversationHandler.END

    # 3. 현재 세션 확인
    if context.user_data.get("authenticated"):
        msg = f"👋 안녕하세요, <b>{user.mention_html()}</b>님! (세션 유효)"
        await update.message.reply_html(msg, reply_markup=reply_markup)
        return ConversationHandler.END

    # 4. 미인증 -> 비밀번호 요청
    # 관리자에게 알림
    if config.ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=f"🔔 <b>새 사용자 접근</b>\n{user.mention_html()} (ID: <code>{user.id}</code>)",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    context.user_data["password_attempts"] = 0
    await update.message.reply_text("🔒 봇 사용을 위해 비밀번호를 입력해주세요:")
    return AuthStates.WAITING_PASSWORD


async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """비밀번호 검증"""
    user = update.effective_user
    password = update.message.text
    max_attempts = config.MAX_PASSWORD_ATTEMPTS

    if password == config.BOT_PASSWORD:
        context.user_data["authenticated"] = True
        context.user_data.pop("password_attempts", None)

        # DB에 허용 유저로 등록
        await asyncio.to_thread(database.add_permitted_user, user.id)

        # 관리자 알림
        if config.ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=config.ADMIN_CHAT_ID,
                    text=f"✅ <b>인증 성공</b>\n{user.mention_html()} (ID: {user.id})",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        await update.message.reply_html(
            f"✅ 인증 완료! 안녕하세요 <b>{user.mention_html()}</b>님!",
            reply_markup=get_main_inline_keyboard(),
        )
        return ConversationHandler.END

    # 실패 처리
    attempts = context.user_data.get("password_attempts", 0) + 1
    context.user_data["password_attempts"] = attempts

    if attempts >= max_attempts:
        # 차단 로직
        await asyncio.to_thread(database.ban_user, user.id)
        await update.message.reply_text("🚫 비밀번호 입력 횟수 초과로 차단되었습니다.")

        if config.ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=f"🚫 <b>차단 알림</b>\n{user.mention_html()} (ID: {user.id}) - 비번 틀림",
                parse_mode=ParseMode.HTML,
            )
        return ConversationHandler.END

    await update.message.reply_text(
        f"❌ 비밀번호가 틀렸습니다. ({attempts}/{max_attempts})"
    )
    return AuthStates.WAITING_PASSWORD


# --- 관리자 기능 ---


@check_ban
@require_auth
@require_admin
async def banlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """차단 목록 조회"""
    banned = await asyncio.to_thread(database.get_banned_users)
    msg = (
        f"🚫 <b>차단 목록</b> ({len(banned)}명)\n\n<pre>"
        + "\n".join(map(str, banned))
        + "</pre>"
        if banned
        else "✅ 차단된 사용자가 없습니다."
    )
    await update.message.reply_html(msg)


@check_ban
@require_auth
@require_admin
async def permitlist_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """허용 목록 조회"""
    permitted = await asyncio.to_thread(database.get_permitted_users)
    msg = (
        f"✅ <b>허용 목록</b> ({len(permitted)}명)\n\n<pre>"
        + "\n".join(map(str, permitted))
        + "</pre>"
        if permitted
        else "ℹ️ 허용 목록이 비었습니다."
    )
    await update.message.reply_html(msg)


@check_ban
@require_auth
@require_admin
async def unban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """차단 해제 시작"""
    await update.message.reply_html(
        "🚫 <b>차단 해제</b>\n해제할 <b>ID(숫자)</b>를 입력하세요.\n취소: /cancel"
    )
    return UnbanStates.WAITING_TARGET_ID


@check_ban
@require_auth
@require_admin
async def unban_target_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """차단 해제 처리"""
    target = update.message.text.strip()
    if not target.isdigit():
        await update.message.reply_text("⚠️ 숫자로 된 ID를 입력해주세요.")
        return UnbanStates.WAITING_TARGET_ID

    uid = int(target)
    if await asyncio.to_thread(database.unban_user_db, uid):
        await update.message.reply_html(f"✅ ID <code>{uid}</code> 차단 해제 완료.")
    else:
        await update.message.reply_text(f"⚠️ 실패했거나 목록에 없는 ID입니다.")
    return ConversationHandler.END
