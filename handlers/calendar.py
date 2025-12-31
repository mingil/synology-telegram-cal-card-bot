# handlers/calendar.py
import logging
import html
import asyncio
import calendar
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


class DateInputStates(IntEnum):
    WAITING_DATE = 1


class SearchEventsStates(IntEnum):
    WAITING_KEYWORD = 1


class AddEventStates(IntEnum):
    SELECT_CALENDAR = 1
    WAITING_TITLE = 2
    WAITING_START = 3
    WAITING_END_OR_ALLDAY = 4


# --- 내부 유틸리티 ---
async def _fetch_and_send_events(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    start_dt: datetime,
    end_dt: datetime,
    period_str: str,
):
    chat_id = update.effective_chat.id
    # 메시지 전송 시도
    msg = await context.bot.send_message(chat_id, f"🗓️ {period_str} 일정 확인 중...")
    await context.bot.send_chat_action(chat_id, action=ChatAction.TYPING)

    # 서비스 호출
    result_tuple = await asyncio.to_thread(
        caldav_service.fetch_events, start_dt, end_dt
    )
    success = result_tuple[0]
    result = result_tuple[1]

    # 1. 조회 실패 처리
    if not success:
        await msg.edit_text(f"❌ 조회 오류 발생:\n{result}")
        return

    # 2. 결과 없음 처리
    if not result:
        await msg.edit_text(
            f"✅ {period_str}에는 예정된 일정이 없습니다.", parse_mode=ParseMode.HTML
        )
        return

    # 3. 결과 포맷팅
    response = f"🗓️ <b>{period_str}</b> 일정 ({len(result)}건)\n"
    events_by_date = {}

    for event in result:
        # [핵심 수정] 키 이름 호환성 확보 ('start' 또는 'start_dt' 모두 확인)
        start_obj = event.get("start") or event.get("start_dt")

        if not start_obj:
            logger.warning(f"⚠️ 날짜 정보 없음: {event}")
            continue

        # datetime 객체를 문자열 키(YYYY-MM-DD)로 변환
        if isinstance(start_obj, datetime):
            date_key = start_obj.strftime("%Y-%m-%d")
        elif isinstance(start_obj, date):
            date_key = start_obj.strftime("%Y-%m-%d")
        else:
            date_key = str(start_obj).split()[0]  # 최후의 수단

        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(event)

    # 날짜순 정렬하여 텍스트 생성
    for d_key in sorted(events_by_date.keys()):
        # 날짜 헤더
        response += f"\n📅 <b>{d_key}</b>\n"
        for evt in events_by_date[d_key]:
            try:
                # 포맷터 호출 (HTML 생성)
                event_content = formatters.format_event_to_html(evt)
                response += f" • {event_content}\n"
            except Exception as e:
                logger.error(f"포맷팅 에러: {e}")
                response += f" • (표시 오류: {html.escape(evt.get('summary', '?'))})\n"

    # 4. 메시지 길이 제한 처리 (텔레그램은 4096자 제한)
    if len(response) > 4000:
        response = response[:4000] + "\n...(내용이 너무 길어 생략됨)"

    # 5. 최종 메시지 전송 (에러 핸들링 포함)
    try:
        await msg.edit_text(response, parse_mode=ParseMode.HTML)
    except error.BadRequest as e:
        logger.error(f"❌ 텔레그램 메시지 전송 실패 (포맷 오류 가능성): {e}")
        # HTML 파싱 에러일 경우, HTML 태그를 제거하고 일반 텍스트로 재시도
        safe_text = (
            response.replace("<b>", "")
            .replace("</b>", "")
            .replace("<code>", "")
            .replace("</code>", "")
        )
        await msg.edit_text(f"⚠️ 포맷 오류로 일반 텍스트로 표시합니다.\n\n{safe_text}")
    except Exception as e:
        logger.error(f"❌ 알 수 없는 전송 오류: {e}")
        await msg.edit_text(f"❌ 결과 전송 중 오류가 발생했습니다.")


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
    # [디버깅] 검색 범위 로그 출력
    logger.info(f"이번 달 검색 요청: {start} ~ {end}")

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

    start = datetime.now()
    end = start + timedelta(days=90)

    result_tuple = await asyncio.to_thread(caldav_service.fetch_events, start, end)
    success = result_tuple[0]
    all_events = result_tuple[1]

    if success:
        filtered = [e for e in all_events if keyword.lower() in e["summary"].lower()]
        if filtered:
            # 5. 검색 결과 표시 부분도 안전하게 수정
            res_text = (
                f"🔎 <b>'{html.escape(keyword)}'</b> 검색 결과 ({len(filtered)}건):\n"
            )
            for evt in filtered[:15]:
                try:
                    res_text += f" • {formatters.format_event_to_html(evt)}\n"
                except:
                    continue
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

    res = await asyncio.to_thread(caldav_service.get_calendars)
    calendars = res if isinstance(res, list) else []

    if not calendars:
        await msg.edit_text("❌ 캘린더 목록을 가져오지 못했습니다.")
        return ConversationHandler.END

    keyboard = []
    available_cals = {}

    for c in calendars:
        try:
            c_name = getattr(c, "name", str(c))
            c_url = str(getattr(c, "url", ""))
            available_cals[c_name] = c_url
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📅 {c_name}", callback_data=f"addevent_cal_name_{c_name[:40]}"
                    )
                ]
            )
        except Exception:
            continue

    context.user_data["_available_calendars"] = available_cals
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

    res_tuple = await asyncio.to_thread(
        caldav_service.add_event, details["calendar_url"], details
    )
    success, res_msg = res_tuple

    await msg.edit_text(f"✅ {res_msg}" if success else f"❌ {res_msg}")
    return ConversationHandler.END


# 더미 핸들러 (삭제 등)
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
