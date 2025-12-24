# handlers/calendar.py
import logging
import html
import asyncio
import calendar
from datetime import datetime, date, time, timedelta
from enum import IntEnum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

# [수정] ChatAction, ParseMode는 telegram.constants에서 가져옴
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from core import config
from services import caldav_service
from utils import date_utils, formatters
from handlers.decorators import check_ban, require_auth
from handlers.common import clear_other_conversations

logger = logging.getLogger(__name__)


class DateInputStates(IntEnum):
    WAITING_DATE = 1


class SearchEventsStates(IntEnum):
    WAITING_KEYWORD = 1


class AddEventStates(IntEnum):
    SELECT_CALENDAR = 1
    WAITING_TITLE = 2
    WAITING_START = 3
    WAITING_END_OR_ALLDAY = 4


class DeleteEventStates(IntEnum):
    SELECT_METHOD = 1
    WAITING_KEYWORD = 2
    SELECT_EVENT = 3
    CONFIRM_DELETION = 4


# --- 내부 유틸리티 ---
async def _fetch_and_send_events(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    start_dt: datetime,
    end_dt: datetime,
    period_str: str,
):
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id, f"🗓️ {period_str} 일정 확인 중...")
    await context.bot.send_chat_action(chat_id, action=ChatAction.TYPING)

    success, result = await asyncio.to_thread(
        caldav_service.fetch_events, start_dt, end_dt
    )

    if not success:
        await msg.edit_text(f"❌ 오류 발생: {result}")
        return
    if not result:
        await msg.edit_text(
            f"✅ {period_str}에는 예정된 일정이 없습니다.", parse_mode=ParseMode.HTML
        )
        return

    response = f"🗓️ <b>{period_str}</b> 일정입니다.\n"
    events_by_date = {}
    for event in result:
        start_dt_obj = event.get("start_dt")
        date_key = str(start_dt_obj).split()[0]
        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(event)

    for d_key in sorted(events_by_date.keys()):
        response += f"\n<b>{d_key}</b>\n"
        for evt in events_by_date[d_key]:
            response += "  • " + formatters.format_event_to_html(evt) + "\n"

    if len(response) > 4000:
        response = response[:4000] + "...\n(내용이 너무 깁니다)"
    await msg.edit_text(response, parse_mode=ParseMode.HTML)


# --- 조회 핸들러 ---
@check_ban
@require_auth
async def show_today_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date_utils.get_today()
    await _fetch_and_send_events(
        update,
        context,
        datetime.combine(today, time.min),
        datetime.combine(today, time.max),
        f"오늘 ({today})",
    )


@check_ban
@require_auth
async def show_week_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date_utils.get_today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    await _fetch_and_send_events(
        update,
        context,
        datetime.combine(start, time.min),
        datetime.combine(end, time.max),
        f"이번 주 ({start.strftime('%m/%d')}~{end.strftime('%m/%d')})",
    )


@check_ban
@require_auth
async def show_month_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date_utils.get_today()
    _, last_day = calendar.monthrange(today.year, today.month)
    start = today.replace(day=1)
    end = today.replace(day=last_day)
    await _fetch_and_send_events(
        update,
        context,
        datetime.combine(start, time.min),
        datetime.combine(end, time.max),
        f"이번 달 ({today.strftime('%Y-%m')})",
    )


@check_ban
@require_auth
async def calendar_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if data == "show_today":
        await show_today_events(update, context)
    elif data == "show_week":
        await show_week_events(update, context)
    elif data == "show_month":
        await show_month_events(update, context)
    elif data == "add_event_prompt":
        await query.message.reply_text(
            "➕ 새 일정을 추가하려면 /addevent 명령어를 입력하세요."
        )


# --- 날짜 지정 조회 ---
@check_ban
@require_auth
async def date_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context)
    await update.message.reply_html(
        "📅 조회할 날짜를 <b>YYYY-MM-DD</b> 형식으로 입력하세요.\n취소: /cancel"
    )
    return DateInputStates.WAITING_DATE


async def date_input_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    target_date = date_utils.parse_date_string(text)
    if target_date:
        await _fetch_and_send_events(
            update,
            context,
            datetime.combine(target_date, time.min),
            datetime.combine(target_date, time.max),
            f"{target_date} ({target_date.strftime('%a')})",
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "⚠️ 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력해주세요."
        )
        return DateInputStates.WAITING_DATE


# --- 일정 검색 ---
@check_ban
@require_auth
async def search_events_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await clear_other_conversations(context)
    await update.message.reply_text(
        "🔎 검색할 일정 키워드를 입력해주세요.\n취소: /cancel"
    )
    return SearchEventsStates.WAITING_KEYWORD


async def search_events_keyword_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    keyword = update.message.text.strip()
    msg = await update.message.reply_text(f"🔎 '{keyword}' 검색 중...")
    await context.bot.send_chat_action(
        update.effective_chat.id, action=ChatAction.TYPING
    )

    start = datetime.now()
    end = start + timedelta(days=90)
    success, all_events = await asyncio.to_thread(
        caldav_service.fetch_events, start, end
    )

    if success:
        filtered = [e for e in all_events if keyword.lower() in e["summary"].lower()]
        if filtered:
            res_text = (
                f"🔎 <b>'{html.escape(keyword)}'</b> 검색 결과 ({len(filtered)}건):\n"
            )
            for evt in filtered[:15]:
                res_text += "• " + formatters.format_event_to_html(evt) + "\n"
            await msg.edit_text(res_text, parse_mode=ParseMode.HTML)
        else:
            await msg.edit_text("검색 결과가 없습니다.")
    else:
        await msg.edit_text(f"검색 실패: {all_events}")
    return ConversationHandler.END


# --- 일정 추가 ---
@check_ban
@require_auth
async def addevent_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context, ["new_event_details"])
    context.user_data["new_event_details"] = {}
    msg = await update.message.reply_text("📅 캘린더 목록을 가져오는 중...")
    success, calendars = await asyncio.to_thread(caldav_service.get_calendars)

    if not success or not calendars:
        await msg.edit_text("❌ 캘린더 목록을 가져오지 못했습니다.")
        return ConversationHandler.END

    keyboard = []
    context.user_data["_available_calendars"] = {c["name"]: c["url"] for c in calendars}
    for name in context.user_data["_available_calendars"]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📅 {name}", callback_data=f"addevent_cal_name_{name[:40]}"
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("🚫 취소", callback_data="addevent_cancel")])
    await msg.edit_text(
        "어떤 캘린더에 추가하시겠습니까?", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AddEventStates.SELECT_CALENDAR


async def addevent_calendar_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "addevent_cancel":
        await query.edit_message_text("취소되었습니다.")
        return ConversationHandler.END

    cal_name_prefix = query.data.replace("addevent_cal_name_", "")
    calendars = context.user_data.get("_available_calendars", {})
    selected_name = next((n for n in calendars if n.startswith(cal_name_prefix)), None)

    if not selected_name:
        await query.edit_message_text("❌ 오류 발생.")
        return ConversationHandler.END

    context.user_data["new_event_details"]["calendar_url"] = calendars[selected_name]
    await query.edit_message_text(
        f"✅ 선택: <b>{selected_name}</b>\n\n📝 일정 제목을 입력하세요.",
        parse_mode=ParseMode.HTML,
    )
    return AddEventStates.WAITING_TITLE


async def addevent_title_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data["new_event_details"]["summary"] = update.message.text.strip()
    await update.message.reply_text(
        "⏰ 시작 날짜(YYYY-MM-DD) 또는 일시(YYYY-MM-DD HH:MM)를 입력하세요."
    )
    return AddEventStates.WAITING_START


async def addevent_start_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    try:
        if len(text) <= 10:
            dt = datetime.strptime(text, "%Y-%m-%d").date()
            context.user_data["new_event_details"]["is_allday"] = True
        else:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
            context.user_data["new_event_details"]["is_allday"] = False
        context.user_data["new_event_details"]["dtstart"] = dt
        await update.message.reply_text("종료 일시를 입력하세요 (종료 없으면 '-' 입력)")
        return AddEventStates.WAITING_END_OR_ALLDAY
    except ValueError:
        await update.message.reply_text("형식 오류. 다시 입력해주세요.")
        return AddEventStates.WAITING_START


async def addevent_end_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    dt_end = None
    if text != "-":
        try:
            if len(text) <= 10:
                dt_end = datetime.strptime(text, "%Y-%m-%d").date()
            else:
                dt_end = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except:
            pass
    context.user_data["new_event_details"]["dtend"] = dt_end

    msg = await update.message.reply_text("⏳ 저장 중...")
    details = context.user_data["new_event_details"]
    success, res = await asyncio.to_thread(
        caldav_service.add_event, details["calendar_url"], details
    )

    await msg.edit_text(f"✅ {res}" if success else f"❌ {res}")
    return ConversationHandler.END


# 더미 핸들러들
async def deleteevent_start(update, context):
    return ConversationHandler.END


async def deleteevent_method_selected(update, context):
    return ConversationHandler.END


async def deleteevent_keyword_received(update, context):
    return ConversationHandler.END


async def deleteevent_event_selected(update, context):
    return ConversationHandler.END


async def deleteevent_confirm_callback(update, context):
    return ConversationHandler.END
