import functools
import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from core import config, database

logger = logging.getLogger(__name__)

def check_ban(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return await func(update, context, *args, **kwargs)

        # [핵심] DB 조회를 비동기로 처리하여 봇 전체의 병목 이벤트 해소
        is_banned = await asyncio.to_thread(database.is_user_banned, user.id)
        if is_banned:
            logger.warning(f"🚫 차단된 사용자 접근 시도: {user.first_name} (ID: {user.id})")
            if update.callback_query:
                await update.callback_query.answer("🚫 접근이 차단되었습니다.", show_alert=True)
            elif update.message:
                await update.message.reply_text("🚫 시스템에 의해 접근이 차단된 사용자입니다.")
            return ConversationHandler.END

        return await func(update, context, *args, **kwargs)
    return wrapper

def require_auth(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return await func(update, context, *args, **kwargs)

        is_trusted = user.id in config.TRUSTED_USER_IDS
        is_authenticated = context.user_data.get("authenticated", False)

        if not is_authenticated and not is_trusted:
            is_permitted = await asyncio.to_thread(database.is_user_permitted, user.id)
            if is_permitted:
                context.user_data["authenticated"] = True
                return await func(update, context, *args, **kwargs)

            logger.info(f"🔒 인증되지 않은 접근: {user.first_name} (ID: {user.id})")
            msg_text = "🔒 권한이 없습니다. /start 명령어로 인증을 진행해주세요."
            if update.callback_query:
                await update.callback_query.answer("🔒 인증 필요", show_alert=False)
                await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_text)
            elif update.message:
                await update.message.reply_text(msg_text)
            return ConversationHandler.END

        return await func(update, context, *args, **kwargs)
    return wrapper

def require_admin(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user and str(user.id) == str(config.ADMIN_CHAT_ID):
            return await func(update, context, *args, **kwargs)

        logger.warning(f"⚠️ 관리자 권한 없는 접근(ID: {user.id if user else 'None'}) -> '{func.__name__}' 실행 시도")
        return None
    return wrapper
