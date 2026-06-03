import logging
import asyncio
import html
from enum import IntEnum

from telegram import Update
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from services import carddav_service
from utils import formatters
from handlers.decorators import check_ban, require_auth
from handlers.common import clear_other_conversations

logger = logging.getLogger(__name__)

class FindContactStates(IntEnum): WAITING_NAME = 1
class SearchContactStates(IntEnum): WAITING_KEYWORD = 1
class AddContactStates(IntEnum): WAITING_NAME = 1; WAITING_PHONE = 2; WAITING_EMAIL = 3

@check_ban
@require_auth
async def findcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context)
    await update.message.reply_text("👤 검색할 이름을 입력해주세요.\n취소: /cancel")
    return FindContactStates.WAITING_NAME

async def findcontact_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    msg = await update.message.reply_text(f"🔍 '{html.escape(name)}' 검색 중...")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    success, result = await asyncio.to_thread(carddav_service.search_contacts, name)

    if success and isinstance(result, list):
        html_msg = formatters.format_contact_list_html(result[:15]) # 메시지 길이 제한 방어
        if len(result) > 15:
            html_msg += "\n\n<i>...(결과가 많아 상위 15개만 표시합니다)</i>"
        await msg.edit_text(f"✨ <b>'{html.escape(name)}'</b> 검색 결과:\n\n{html_msg}", parse_mode=ParseMode.HTML)
    else:
        await msg.edit_text(f"❌ {result}")
    return ConversationHandler.END

@check_ban
@require_auth
async def searchcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context)
    await update.message.reply_text("🔍 전화번호, 이메일, 메모 등 검색어를 입력하세요.\n취소: /cancel")
    return SearchContactStates.WAITING_KEYWORD

async def searchcontact_keyword_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyword = update.message.text.strip()
    msg = await update.message.reply_text("🔍 검색 중...")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    success, result = await asyncio.to_thread(carddav_service.search_contacts, keyword)

    if success and isinstance(result, list):
        html_msg = formatters.format_contact_list_html(result[:15]) # 길면 잘라서 방어
        if len(result) > 15:
            html_msg += "\n\n<i>...(결과가 많아 상위 15개만 표시합니다)</i>"
        await msg.edit_text(f"🔍 <b>'{html.escape(keyword)}'</b> 결과:\n\n{html_msg}", parse_mode=ParseMode.HTML)
    else:
        await msg.edit_text(f"결과 없음: {result}")
    return ConversationHandler.END

@check_ban
@require_auth
async def addcontact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context, ["new_contact"])
    context.user_data["new_contact"] = {}
    await update.message.reply_text("✏️ 이름 입력:\n취소: /cancel")
    return AddContactStates.WAITING_NAME

async def addcontact_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_contact"]["name"] = update.message.text.strip()
    await update.message.reply_text("📞 전화번호 입력 (건너뛰기: -):")
    return AddContactStates.WAITING_PHONE

async def addcontact_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ph = update.message.text.strip()
    context.user_data["new_contact"]["phone"] = None if ph == "-" else ph
    await update.message.reply_text("📧 이메일 입력 (건너뛰기: -):")
    return AddContactStates.WAITING_EMAIL

async def addcontact_email_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    em = update.message.text.strip()
    # [핵심] 팝(pop)을 써서 데이터를 꺼내는 즉시 메모리에서 삭제
    nc = context.user_data.pop("new_contact", {})
    nc["email"] = None if em == "-" else em

    msg = await update.message.reply_text("⏳ 연락처 저장 중...")
    success, res = await asyncio.to_thread(carddav_service.add_contact, nc.get("name"), nc.get("phone"), nc.get("email"))
    await msg.edit_text(res)
    return ConversationHandler.END
