import html
import logging
import asyncio
import time as sys_time
from datetime import datetime, timedelta, date, time
from core import config, database
from utils import date_utils
from services import caldav_service, email_service

logger = logging.getLogger(__name__)

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

    target_dates_map: dict[date, int] = {}
    lunar_dates_map: dict[date, int] = {}
    lunar_mmdd_map: dict[tuple[int, int], tuple[int, int, int]] = {}

    for offset in check_offsets:
        target_solar = today + timedelta(days=offset)
        target_dates_map[target_solar] = offset

        if lunar_iso := date_utils.get_lunar_date_string(target_solar):
            try:
                l_year, l_month, l_day = map(int, lunar_iso.split("-"))
                lunar_mmdd_map[(l_month, l_day)] = (offset, l_month, l_day)
            except ValueError:
                pass
            if parsed_lunar := date_utils.parse_date_string(lunar_iso):
                lunar_dates_map[parsed_lunar] = offset

    # [핵심 버그 수정] 음력 날짜는 양력보다 약 1~2달 앞서므로,
    # 조회 시작일을 음력 최소 날짜까지 포함해야 음력 기념일이 누락되지 않음
    all_target_dates = list(target_dates_map.keys()) + list(lunar_dates_map.keys())
    min_search_date = min(all_target_dates) if all_target_dates else today - timedelta(days=65)
    max_search_date = max(all_target_dates) if all_target_dates else today + timedelta(days=max(check_offsets))

    start_dt = datetime.combine(min_search_date, time.min)
    end_dt = datetime.combine(max_search_date, time.max)

    success, events = False, []
    for attempt in range(3):
        success, events = caldav_service.fetch_events(start_dt, end_dt)
        if success:
            break
        logger.warning(f"⚠️ 캘린더 서버 응답 지연. 10초 후 재시도... ({attempt + 1}/3)")
        sys_time.sleep(10)

    if not success or not events:
        return []

    processed_keys = set()

    for event in events:
        summary = str(event.get("summary", "") or "").strip()
        start_val = event.get("start")
        if not start_val or not summary:
            continue

        event_date = start_val.date() if isinstance(start_val, datetime) else start_val
        if not isinstance(event_date, date):
            continue

        offset_solar = target_dates_map.get(event_date)
        offset_lunar = lunar_dates_map.get(event_date)
        lunar_month, lunar_day = event_date.month, event_date.day

        if offset_lunar is None and (event_date.month, event_date.day) in lunar_mmdd_map:
            offset_lunar, lunar_month, lunar_day = lunar_mmdd_map[(event_date.month, event_date.day)]

        if offset_solar is None and offset_lunar is None:
            continue

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
            uid = event.get("url") or summary
            dedup_key = (uid, matched_offset)
            if dedup_key in processed_keys:
                continue
            processed_keys.add(dedup_key)

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
                    lunar_info = f"\n(음력 {lunar_month}월 {lunar_day}일)"
                else:
                    header = "🔔 <b>[중요 일정 알림]</b>"
                    lunar_info = ""

                safe_summary = html.escape(summary)
                msg_body = (
                    f"{header}\n"
                    f"{d_day_str} ({target_solar_date})\n"
                    f"<b>{safe_summary}</b> {desc_str}{lunar_info}"
                ).strip()
                email_subject = f"📅 [{short_d_day}] {summary}"

                notifications.append({"subject": email_subject, "body": msg_body})
                database.mark_notification_sent(uid, str(target_solar_date), noti_type)

    return notifications


async def _safe_send_telegram(bot, chat_id, text):
    """텔레그램 메시지 발송 실패 시 봇 전체가 멈추는 것을 방지하는 헬퍼 함수"""
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ 텔레그램 병렬 전송 실패: {e}")


async def run_daily_checks(bot_app):
    logger.info("⏰ 일일 알림 체크 시작")
    noti_list = await asyncio.to_thread(check_anniversaries)

    if not noti_list:
        return

    # [최적화 핵심] 순차 발송 방식에서 -> 모든 작업을 모아 한 번에 병렬 전송(Gather)하는 방식으로 변경
    tasks = []
    for item in noti_list:
        if config.TARGET_CHAT_ID:
            tasks.append(
                _safe_send_telegram(bot_app.bot, config.TARGET_CHAT_ID, item["body"])
            )

        if config.SMTP_EMAIL and config.SMTP_PASSWORD:
            tasks.append(
                asyncio.to_thread(
                    email_service.send_email, item["subject"], item["body"]
                )
            )

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"❌ 알림 발송 중 에러: {res}")
        logger.info(f"✅ {len(noti_list)}건의 스케줄 알림 비동기 처리 완료")
