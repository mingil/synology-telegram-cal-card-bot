# handlers/contact.py
import logging
import asyncio
import html
from enum import IntEnum

from telegram import Update

# [수정] ChatAction, ParseMode 경로 수정
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from core import config
from services import carddav_service
from utils import formatters
from handlers.decorators import check_ban, require_auth
from handlers.common import clear_other_conversations

logger = logging.getLogger(__name__)


class FindContactStates(IntEnum):
    WAITING_NAME = 1


class SearchContactStates(IntEnum):
    WAITING_KEYWORD = 1


class AddContactStates(IntEnum):
    WAITING_NAME = 1
    WAITING_PHONE = 2
    WAITING_EMAIL = 3


class DeleteContactStates(IntEnum):
    WAITING_TARGET = 1
    CONFIRM_DELETION = 2


@check_ban
@require_auth
async def findcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context)
    await update.message.reply_text("👤 검색할 이름을 입력해주세요.\n취소: /cancel")
    return FindContactStates.WAITING_NAME


async def findcontact_name_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    name = update.message.text.strip()
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    success, result = await asyncio.to_thread(carddav_service.search_contacts, name)

    if success and isinstance(result, list):
        html_msg = formatters.format_contact_list_html(result)
        await update.message.reply_html(
            f"✨ <b>'{html.escape(name)}'</b> 검색 결과:\n\n{html_msg}"
        )
    else:
        await update.message.reply_text(f"❌ {result}")
    return ConversationHandler.END


@check_ban
@require_auth
async def searchcontact_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await clear_other_conversations(context)
    await update.message.reply_text("🔍 검색어를 입력하세요.")
    return SearchContactStates.WAITING_KEYWORD


async def searchcontact_keyword_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    keyword = update.message.text.strip()
    msg = await update.message.reply_text("🔍 검색 중...")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    success, result = await asyncio.to_thread(carddav_service.search_contacts, keyword)

    if success and isinstance(result, list):
        html_msg = formatters.format_contact_list_html(result[:10])
        await msg.edit_text(
            f"🔍 <b>'{keyword}'</b> 결과:\n\n{html_msg}", parse_mode=ParseMode.HTML
        )
    else:
        await msg.edit_text(f"결과 없음: {result}")
    return ConversationHandler.END


@check_ban
@require_auth
async def addcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context, ["new_contact"])
    context.user_data["new_contact"] = {}
    await update.message.reply_text("✏️ 이름 입력:")
    return AddContactStates.WAITING_NAME


async def addcontact_name_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data["new_contact"]["name"] = update.message.text.strip()
    await update.message.reply_text("📞 전화번호 입력 (건너뛰기: -):")
    return AddContactStates.WAITING_PHONE


async def addcontact_phone_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    ph = update.message.text.strip()
    context.user_data["new_contact"]["phone"] = None if ph == "-" else ph
    await update.message.reply_text("📧 이메일 입력 (건너뛰기: -):")
    return AddContactStates.WAITING_EMAIL


async def addcontact_email_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    em = update.message.text.strip()
    context.user_data["new_contact"]["email"] = None if em == "-" else em

    msg = await update.message.reply_text("⏳ 저장 중...")
    nc = context.user_data["new_contact"]
    success, res = await asyncio.to_thread(
        carddav_service.add_contact, nc["name"], nc["phone"], nc["email"]
    )
    await msg.edit_text(res)
    return ConversationHandler.END


# 더미 핸들러
async def deletecontact_start(update, context):
    return ConversationHandler.END


async def deletecontact_target_received(update, context):
    return ConversationHandler.END


async def delete_confirmation_callback(update, context):
    return ConversationHandler.END
