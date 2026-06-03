import logging
import asyncio
import time as sys_time
from datetime import datetime, timedelta, date, time
from core import config, database
from utils import date_utils
from services import caldav_service, email_service

logger = logging.getLogger(__name__)

# 👇 사용자님이 만드셨던 핵심 알림 키워드 모음!
IMPORTANT_KEYWORDS = [
    "생일", "생신", "결혼", "결기", "웨딩", "기념일",
    "돌잔치", "백일", "환갑", "칠순", "팔순", "구순",
    "제사", "기일", "추도", "벌초", "성묘",
    "결제", "만기", "납부", "세금", "공과금", "적금", "보험", "청약", "계약",
    "예약", "검진", "수술", "진료", "치과", "마감",
    "면접", "시험", "이사", "출장", "항공권", "비행기", "여행"
]

def check_anniversaries() -> list[dict]:
    notifications = []
    today = date_utils.get_today()
    check_offsets = [0, 1, 7, 30]

    target_dates_map = {}
    lunar_dates_map = {}

    for offset in check_offsets:
        target_solar = today + timedelta(days=offset)
        target_dates_map[target_solar] = offset

        if lunar_iso := date_utils.get_lunar_date_string(target_solar):
            if parsed_lunar := date_utils.parse_date_string(lunar_iso):
                lunar_dates_map[parsed_lunar] = offset

    max_offset = max(check_offsets)
    start_dt = datetime.combine(today, time.min)
    end_dt = datetime.combine(today + timedelta(days=max_offset), time.max)

    success, events = False, []
    for attempt in range(3):
        success, events = caldav_service.fetch_events(start_dt, end_dt)
        if success:
            break
        logger.warning(f"⚠️ 캘린더 서버 응답 지연. 10초 후 재시도... ({attempt + 1}/3)")
        sys_time.sleep(10)

    if not success or not events:
        return []

    processed_uids = set()

    for event in events:
        summary = event.get("summary", "")
        start_val = event.get("start")
        if not start_val: continue

        event_date = start_val.date() if isinstance(start_val, datetime) else start_val

        offset_solar = target_dates_map.get(event_date)
        offset_lunar = lunar_dates_map.get(event_date)

        if offset_solar is None and offset_lunar is None: continue

        is_lunar_keyword = "음력" in summary
        clean_summary = summary.replace(" ", "").lower()
        is_important_event = any(kw in clean_summary for kw in IMPORTANT_KEYWORDS)

        should_notify = False
        matched_offset = None

        if is_lunar_keyword and offset_lunar is not None:
            should_notify = True
            matched_offset = offset_lunar
        elif not is_lunar_keyword and offset_solar is not None and is_important_event:
            should_notify = True
            matched_offset = offset_solar

        if should_notify and matched_offset is not None:
            uid = event.get("url", summary)
            if uid in processed_uids: continue
            processed_uids.add(uid)

            target_solar_date = today + timedelta(days=matched_offset)
            noti_type = f"anniversary_{matched_offset}day"

            if not database.is_notification_sent(uid, str(target_solar_date), noti_type):
                labels = {0: "오늘", 1: "내일", 7: "일주일 뒤", 30: "한 달 뒤"}
                short_labels = {0: "오늘", 1: "내일", 7: "D-7", 30: "D-30"}

                d_day_str = labels.get(matched_offset, f"{matched_offset}일 뒤")
                short_d_day = short_labels.get(matched_offset, f"D-{matched_offset}")
                desc_str = "입니다! 🎉" if matched_offset == 0 else f"입니다! ({short_d_day})"

                if is_lunar_keyword:
                    header = "🌕 <b>[음력 일정 알림]</b>"
                    lunar_info = f"\n(음력 {event_date.month}월 {event_date.day}일)"
                else:
                    header = "🔔 <b>[중요 일정 알림]</b>"
                    lunar_info = ""

                msg_body = f"{header}\n{d_day_str} ({target_solar_date})\n<b>{summary}</b> {desc_str}{lunar_info}".strip()
                email_subject = f"📅 [{short_d_day}] {summary}"

                notifications.append({"subject": email_subject, "body": msg_body})
                database.mark_notification_sent(uid, str(target_solar_date), noti_type)

    return notifications

async def run_daily_checks(bot_app):
    logger.info("⏰ 일일 알림 체크 시작")
    noti_list = await asyncio.to_thread(check_anniversaries)

    if not noti_list: return

    email_tasks = []
    for item in noti_list:
        if config.TARGET_CHAT_ID:
            try:
                await bot_app.bot.send_message(config.TARGET_CHAT_ID, item["body"], parse_mode="HTML")
            except Exception as e:
                logger.error(f"❌ 텔레그램 전송 실패: {e}")

        # 복구된 정상적인 이메일 서비스 호출!
        email_tasks.append(asyncio.to_thread(email_service.send_email, item["subject"], item["body"]))

    if email_tasks:
        await asyncio.gather(*email_tasks, return_exceptions=True)
