# handlers/common.py
import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from handlers.decorators import check_ban, require_auth

logger = logging.getLogger(__name__)

CONVERSATION_USER_DATA_KEYS = [
    'new_contact', 'contact_to_delete', 'password_attempts',
    'new_event_details', 'event_to_delete_url', 'search_results_for_delete',
    '_available_calendars'
]

def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📆 이번 달 일정", callback_data="show_month"),
         InlineKeyboardButton("🔎 일정 검색", callback_data="search_events_prompt")],
        [InlineKeyboardButton("➕ 일정 추가", callback_data="add_event_prompt"),
         InlineKeyboardButton("👤 연락처 검색", callback_data="find_contact_prompt")],
        [InlineKeyboardButton("📋 전체 명령어 보기", callback_data="show_all_commands")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def clear_other_conversations(context: ContextTypes.DEFAULT_TYPE, keep_keys: list = None) -> bool:
    if keep_keys is None: keep_keys = []
    if not context.user_data: return False

    keys_to_remove = [k for k in CONVERSATION_USER_DATA_KEYS if k not in keep_keys and k in context.user_data]
    
    if keys_to_remove:
        for key in keys_to_remove:
            del context.user_data[key]
        return True
    return False

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context, [])
    msg = '작업이 취소되었습니다. /start 로 메인 메뉴를 볼 수 있습니다.'
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg)
    elif update.message:
        await update.message.reply_text(msg)
        
    return ConversationHandler.END

# [문제 4 해결] 도움말 명령어 함수 추가
@check_ban
@require_auth
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """전체 명령어 목록 보여주기"""
    cmd_text = (
        "📋 <b>전체 명령어 매뉴얼</b>\n\n"
        "<b>[기본]</b>\n"
        "/start - 봇 시작 및 메인 메뉴\n"
        "/help - 이 도움말 보기\n"
        "/cancel - 현재 진행 중인 작업 취소\n\n"
        "<b>[캘린더]</b>\n"
        "/today - 오늘 일정 조회\n"
        "/week - 이번 주 일정 조회\n"
        "/month - 이번 달 일정 조회\n"
        "/date - 특정 날짜 일정 조회\n"
        "/search_events - 일정 키워드 검색\n"
        "/addevent - 새 일정 추가\n\n"
        "<b>[연락처]</b>\n"
        "/findcontact - 이름으로 연락처 찾기\n"
        "/searchcontact - 키워드(번호 등)로 찾기\n"
        "/addcontact - 새 연락처 추가\n\n"
        "<b>[기타]</b>\n"
        "/ask - AI에게 질문하기"
    )
    
    if update.callback_query:
        await update.callback_query.message.reply_html(cmd_text)
    else:
        await update.message.reply_html(cmd_text)

@check_ban
@require_auth
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message.text
    await update.message.reply_html(
        f"'{html.escape(msg)}'? 🤔\n명령어가 아닙니다.\n"
        f"AI 질문은 <code>/ask 질문</code>\n메뉴는 <b>/start</b> 를 눌러주세요."
    )