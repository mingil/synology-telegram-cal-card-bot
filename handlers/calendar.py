import logging
import html
import asyncio
import calendar as py_calendar
from datetime import datetime, date, time, timedelta
from enum import IntEnum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from services import caldav_service
from utils import date_utils, formatters
from handlers.decorators import check_ban, require_auth
from handlers.common import clear_other_conversations

logger = logging.getLogger(__name__)

class DateInputStates(IntEnum): WAITING_DATE = 1
class SearchEventsStates(IntEnum): WAITING_KEYWORD = 1
class AddEventStates(IntEnum): SELECT_CALENDAR = 1; WAITING_TITLE = 2; WAITING_START = 3; WAITING_END_OR_ALLDAY = 4

async def _fetch_and_send_events(update: Update, context: ContextTypes.DEFAULT_TYPE, start_dt: datetime, end_dt: datetime, period_str: str):
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id, f"🗓️ {period_str} 일정 확인 중...")
    await context.bot.send_chat_action(chat_id, action=ChatAction.TYPING)

    success, result = await asyncio.to_thread(caldav_service.fetch_events, start_dt, end_dt)

    if not success:
        return await msg.edit_text(f"❌ 조회 오류 발생:\n{html.escape(str(result))}", parse_mode=ParseMode.HTML)
    if not result:
        return await msg.edit_text(f"✅ <b>{period_str}</b>에는 예정된 일정이 없습니다.", parse_mode=ParseMode.HTML)

    response = f"🗓️ <b>{period_str}</b> 일정 ({len(result)}건)\n"
    events_by_date = {}

    for event in result:
        start_obj = event.get("start") or event.get("start_dt")
        if not start_obj: continue

        date_key = start_obj.strftime("%Y-%m-%d") if isinstance(start_obj, (datetime, date)) else str(start_obj).split()[0]
        events_by_date.setdefault(date_key, []).append(event)

    for d_key in sorted(events_by_date.keys()):
        response += f"\n📅 <b>{d_key}</b>\n"
        for evt in events_by_date[d_key]:
            try:
                response += f" • {formatters.format_event_to_html(evt)}\n"
            except Exception:
                response += f" • (표시 오류: {html.escape(evt.get('summary', '?'))})\n"

    # [핵심] 텔레그램 메시지 제한 초과 시 봇 다운 방지
    if len(response) > 4000:
        response = response[:3950] + "\n\n...(내용이 너무 길어 생략됨)"

    try:
        await msg.edit_text(response, parse_mode=ParseMode.HTML)
    except error.BadRequest:
        safe_text = response.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        await msg.edit_text(f"⚠️ 텍스트 포맷 오류로 일반 텍스트로 표시합니다.\n\n{safe_text}")

# --- 조회 핸들러 ---
@check_ban
@require_auth
async def show_today_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date_utils.get_today()
    await _fetch_and_send_events(update, context, datetime.combine(today, time.min), datetime.combine(today, time.max), f"오늘 ({today})")

@check_ban
@require_auth
async def show_week_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date_utils.get_today()
    start = today - timedelta(days=today.weekday())
    await _fetch_and_send_events(update, context, datetime.combine(start, time.min), datetime.combine(start + timedelta(days=6), time.max), f"이번 주 ({start.strftime('%m/%d')}~{(start + timedelta(days=6)).strftime('%m/%d')})")

@check_ban
@require_auth
async def show_month_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date_utils.get_today()
    start = today.replace(day=1)
    end = today.replace(day=py_calendar.monthrange(today.year, today.month)[1])
    await _fetch_and_send_events(update, context, datetime.combine(start, time.min), datetime.combine(end, time.max), f"이번 달 ({today.strftime('%Y-%m')})")

@check_ban
@require_auth
async def calendar_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # 콜백 지연 에러 방지 Ping

    actions = {
        "show_today": show_today_events,
        "show_week": show_week_events,
        "show_month": show_month_events
    }
    if action := actions.get(query.data):
        await action(update, context)
    elif query.data == "add_event_prompt":
        await query.message.reply_text("➕ 새 일정을 추가하려면 /addevent 명령어를 입력하세요.")

# --- 날짜 지정 조회 ---
@check_ban
@require_auth
async def date_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context)
    await update.message.reply_html("📅 조회할 날짜를 <b>YYYY-MM-DD</b> 형식으로 입력하세요.\n취소: /cancel")
    return DateInputStates.WAITING_DATE

async def date_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if target_date := date_utils.parse_date_string(update.message.text.strip()):
        await _fetch_and_send_events(update, context, datetime.combine(target_date, time.min), datetime.combine(target_date, time.max), f"{target_date} ({target_date.strftime('%a')})")
        return ConversationHandler.END
    await update.message.reply_text("⚠️ 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 다시 입력해주세요.")
    return DateInputStates.WAITING_DATE  # 실패해도 취소되지 않고 다시 입력받음 (UX 개선)

# --- 일정 검색 ---
@check_ban
@require_auth
async def search_events_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context)
    await update.message.reply_text("🔎 검색할 일정 키워드를 입력해주세요.\n취소: /cancel")
    return SearchEventsStates.WAITING_KEYWORD

async def search_events_keyword_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyword = update.message.text.strip()
    msg = await update.message.reply_text(f"🔎 '{html.escape(keyword)}' 검색 중...")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    start = datetime.now() - timedelta(days=365)
    success, all_events = await asyncio.to_thread(caldav_service.fetch_events, start, start + timedelta(days=730))

    if success:
        filtered = [e for e in all_events if keyword.lower() in e["summary"].lower()]
        if filtered:
            res_text = f"🔎 <b>'{html.escape(keyword)}'</b> 검색 결과 ({len(filtered)}건):\n"
            for evt in filtered[:15]:
                try: res_text += f" • {formatters.format_event_to_html(evt)}\n"
                except: continue

            if len(filtered) > 15:
                res_text += "\n...(결과가 많아 상위 15개만 표시합니다)"

            try:
                await msg.edit_text(res_text, parse_mode=ParseMode.HTML)
            except error.BadRequest:
                await msg.edit_text(res_text.replace("<b>", "").replace("</b>", ""))
        else:
            await msg.edit_text("검색 결과가 없습니다.")
    else:
        await msg.edit_text("검색 실패.")
    return ConversationHandler.END

# --- 일정 추가 ---
@check_ban
@require_auth
async def addevent_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context, ["new_event_details"])
    context.user_data["new_event_details"] = {}
    msg = await update.message.reply_text("📅 캘린더 목록을 가져오는 중...")

    calendars = await asyncio.to_thread(caldav_service.get_calendars)
    if not calendars:
        await msg.edit_text("❌ 캘린더 목록을 가져오지 못했습니다.")
        return ConversationHandler.END

    keyboard = []
    context.user_data["_available_calendars"] = {}

    for c in calendars:
        try:
            c_name, c_url = getattr(c, "name", str(c)), str(getattr(c, "url", ""))
            context.user_data["_available_calendars"][c_name] = c_url
            keyboard.append([InlineKeyboardButton(f"📅 {c_name}", callback_data=f"addevent_cal_name_{c_name[:40]}")])
        except Exception: continue

    keyboard.append([InlineKeyboardButton("🚫 취소", callback_data="addevent_cancel")])
    await msg.edit_text("어떤 캘린더에 추가하시겠습니까?", reply_markup=InlineKeyboardMarkup(keyboard))
    return AddEventStates.SELECT_CALENDAR

async def addevent_calendar_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "addevent_cancel":
        await query.edit_message_text("🚫 취소되었습니다.")
        context.user_data.pop("new_event_details", None)
        context.user_data.pop("_available_calendars", None)
        return ConversationHandler.END

    cal_name_prefix = query.data.replace("addevent_cal_name_", "")
    calendars = context.user_data.get("_available_calendars", {})
    selected_name = next((n for n in calendars if n.startswith(cal_name_prefix)), None)

    if not selected_name:
        await query.edit_message_text("❌ 시간 초과 또는 오류 발생.")
        return ConversationHandler.END

    context.user_data["new_event_details"]["calendar_url"] = calendars[selected_name]
    await query.edit_message_text(f"✅ 선택: <b>{html.escape(selected_name)}</b>\n\n📝 추가할 일정 제목을 입력하세요.", parse_mode=ParseMode.HTML)
    return AddEventStates.WAITING_TITLE

async def addevent_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_event_details"]["summary"] = update.message.text.strip()
    await update.message.reply_text("⏰ 시작 날짜(YYYY-MM-DD) 또는 일시(YYYY-MM-DD HH:MM)를 입력하세요.")
    return AddEventStates.WAITING_START

async def addevent_start_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        is_allday = len(text) <= 10
        dt = datetime.strptime(text, "%Y-%m-%d").date() if is_allday else datetime.strptime(text, "%Y-%m-%d %H:%M")
        context.user_data["new_event_details"].update({"dtstart": dt, "is_allday": is_allday})
        await update.message.reply_text("종료 일시를 입력하세요 (종료 없으면 '-' 입력)")
        return AddEventStates.WAITING_END_OR_ALLDAY
    except ValueError:
        await update.message.reply_text("⚠️ 형식 오류. YYYY-MM-DD 또는 YYYY-MM-DD HH:MM 형식으로 다시 입력해주세요.")
        return AddEventStates.WAITING_START  # 유저가 다시 시도할 수 있도록 상태 유지

async def addevent_end_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    dt_end = None
    if text != "-":
        try:
            dt_end = datetime.strptime(text, "%Y-%m-%d").date() if len(text) <= 10 else datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text("⚠️ 형식 오류. 다시 입력해주세요 (종료 없으면 '-' 입력)")
            return AddEventStates.WAITING_END_OR_ALLDAY

    # pop을 사용하여 딕셔너리 추출과 동시에 메모리에서 즉각 삭제
    details = context.user_data.pop("new_event_details", {})
    context.user_data.pop("_available_calendars", None)

    if not details:
        await update.message.reply_text("❌ 세션이 만료되었습니다. 다시 시도해주세요.")
        return ConversationHandler.END

    details["dtend"] = dt_end
    msg = await update.message.reply_text("⏳ NAS 캘린더에 저장 중...")

    success, res_msg = await asyncio.to_thread(caldav_service.add_event, details["calendar_url"], details)
    await msg.edit_text(f"✅ {res_msg}" if success else f"❌ {res_msg}")

    return ConversationHandler.END
