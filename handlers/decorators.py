# handlers/decorators.py
import functools
import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

# [변경] Core 모듈 사용
from core import config, database

logger = logging.getLogger(__name__)


def check_ban(func):
    """사용자가 차단되었는지 확인하는 데코레이터"""

    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ):
        user = update.effective_user
        if not user:
            return await func(update, context, *args, **kwargs)

        # [변경] database 모듈 사용
        if database.is_user_banned(user.id):
            logger.warning(
                f"차단된 사용자 접근 시도: {user.first_name} (ID: {user.id})"
            )
            if update.callback_query:
                await update.callback_query.answer(
                    "🚫 접근이 차단되었습니다.", show_alert=True
                )
            elif update.message:
                await update.message.reply_text("🚫 접근이 차단된 사용자입니다.")
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)

    return wrapper


def require_auth(func):
    """사용자가 인증되었는지 확인하는 데코레이터"""

    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ):
        user = update.effective_user
        if not user:
            return await func(update, context, *args, **kwargs)

        # [변경] config 및 database 모듈 사용
        is_trusted = user.id in config.TRUSTED_USER_IDS
        is_authenticated = context.user_data.get("authenticated", False)

        if not is_authenticated and not is_trusted:
            if database.is_user_permitted(user.id):
                context.user_data["authenticated"] = True
                return await func(update, context, *args, **kwargs)

            logger.info(f"인증되지 않은 접근: {user.first_name} (ID: {user.id})")
            msg_text = "🔒 먼저 /start 명령어를 통해 인증해주세요."
            if update.callback_query:
                await update.callback_query.answer("🔒 인증 필요", show_alert=False)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=msg_text
                )
            elif update.message:
                await update.message.reply_text(msg_text)
            return ConversationHandler.END

        return await func(update, context, *args, **kwargs)

    return wrapper


def require_admin(func):
    """관리자만 함수를 실행할 수 있도록 제한하는 데코레이터"""

    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ):
        user = update.effective_user
        if not user:
            return None

        user_id_str = str(user.id)
        admin_id_str = str(config.ADMIN_CHAT_ID)

        if user_id_str == admin_id_str:
            return await func(update, context, *args, **kwargs)
        else:
            logger.warning(
                f"관리자 권한 없음(ID: {user_id_str}) -> '{func.__name__}' 실행 시도."
            )
            return None

    return wrapper
