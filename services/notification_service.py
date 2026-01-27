# services/notification_service.py
import logging
import asyncio
from datetime import datetime, timedelta, date, time

from core import config, database
from utils import date_utils
from services import caldav_service, email_service

logger = logging.getLogger(__name__)


def check_anniversaries() -> list[str]:
    """
    오늘/내일/N일 뒤의 날짜를 기준으로 기념일을 확인합니다.
    1. [음력 변환 날짜] (과거 연도의 음력 날짜) 조회 -> 음력 기념일 탐색
    2. [양력 실제 날짜] 조회 -> 양력 기념일 탐색

    '음력', '생일', '생신', '결혼 기념일' 키워드가 포함된 일정을 찾아 알림을 생성합니다.
    """
    messages = []
    today = date.today()

    # 체크할 범위: 당일(0), 하루 전(1), 일주일 전(7), 한 달 전(30)
    check_offsets = [0, 1, 7, 30]

    for offset in check_offsets:
        # 1. 타겟 양력 날짜 (예: 2026-01-02)
        target_solar_date = today + timedelta(days=offset)

        # 날짜 후보군 생성 (검색할 날짜들)
        search_dates = set()

        # [후보 1] 실제 양력 날짜
        search_dates.add(target_solar_date)

        # [후보 2] 음력 변환 날짜
        lunar_iso = date_utils.get_lunar_date_string(target_solar_date)
        l_month, l_day = 0, 0

        if lunar_iso:
            try:
                l_year_str, l_month_str, l_day_str = lunar_iso.split("-")
                l_year, l_month, l_day = (
                    int(l_year_str),
                    int(l_month_str),
                    int(l_day_str),
                )
                # 음력 기준 날짜 추가
                search_dates.add(date(l_year, l_month, l_day))
            except Exception as e:
                logger.error(f"음력 날짜 변환 오류: {e}")

        found_events = []

        # 2. 날짜 후보군 모두 검색
        for s_date in search_dates:
            start_dt = datetime.combine(s_date, time.min)
            end_dt = datetime.combine(s_date, time.max)

            success, events = caldav_service.fetch_events(start_dt, end_dt)
            if success and events:
                found_events.extend(events)

        if not found_events:
            continue

        # 3. 일정 필터링 및 알림 생성
        processed_uids = set()

        for event in found_events:
            summary = event.get("summary", "")

            # [핵심 수정] 타임존 중복 방지를 위한 '시작 날짜' 엄격 검사
            # 검색된 일정이 '타겟 날짜(search_dates)' 중 하나에 정확히 시작하는지 확인
            # (시간차로 인해 다음날까지 걸쳐있는 일정이 검색되는 것을 방지)
            event_start = event.get("start")

            if event_start:
                # datetime이면 date로 변환
                if isinstance(event_start, datetime):
                    event_start_date = event_start.date()
                elif isinstance(event_start, date):
                    event_start_date = event_start
                else:
                    continue  # 날짜 정보 없으면 스킵

                # 만약 일정이 시작하는 날짜가 우리가 검색하려던 날짜 목록에 없다면?
                # -> 이건 단순히 시간이 걸쳐서 검색된 '가짜'입니다. 무시합니다.
                if event_start_date not in search_dates:
                    continue

            # 키워드 체크
            is_lunar = "음력" in summary
            is_birthday = "생일" in summary or "생신" in summary
            is_wedding = "결혼 기념일" in summary or "결혼기념일" in summary

            # 위 키워드 중 하나라도 포함되면 알림 대상
            if is_lunar or is_birthday or is_wedding:
                uid = event.get("url", summary)

                # 중복 방지
                if uid in processed_uids:
                    continue
                processed_uids.add(uid)

                # DB 기록 확인
                noti_type = f"anniversary_{offset}day"
                if not database.is_notification_sent(
                    uid, str(target_solar_date), noti_type
                ):
                    # D-Day 문구 생성
                    if offset == 0:
                        d_day_str = "오늘"
                        desc_str = "입니다! 🎉"
                    elif offset == 1:
                        d_day_str = "내일"
                        desc_str = "입니다! (D-1)"
                    elif offset == 7:
                        d_day_str = "일주일 뒤"
                        desc_str = "입니다! (D-7)"
                    elif offset == 30:
                        d_day_str = "한 달 뒤"
                        desc_str = "입니다! (D-30)"
                    else:
                        d_day_str = f"{offset}일 뒤"
                        desc_str = f"입니다! (D-{offset})"

                    # 알림 제목(Header) 구분
                    if is_lunar:
                        header = "🌕 <b>[음력 알림]</b>"
                    else:
                        header = "🎉 <b>[기념일 알림]</b>"

                    # 메시지 작성
                    lunar_info = f"(음력 {l_month}월 {l_day}일)" if l_month else ""

                    msg = (
                        f"{header}\n"
                        f"{d_day_str} ({target_solar_date})\n"
                        f"<b>{summary}</b> {desc_str}\n"
                        f"{lunar_info}"
                    ).strip()

                    messages.append(msg)

                    # DB에 발송 기록 저장
                    database.mark_notification_sent(
                        uid, str(target_solar_date), noti_type
                    )

    return messages


async def run_daily_checks(bot_app):
    """매일 아침 7시에 실행되는 체크 로직"""
    logger.info("⏰ 일일 알림 체크 시작")

    msgs = await asyncio.to_thread(check_anniversaries)

    if not msgs:
        return

    for msg in msgs:
        # 텔레그램 발송
        if config.TARGET_CHAT_ID:
            try:
                await bot_app.bot.send_message(
                    config.TARGET_CHAT_ID, msg, parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"텔레그램 전송 실패: {e}")

        # 이메일 발송
        try:
            email_subject = "📅 [Calendar Bot] 놓치면 안 되는 일정이 있습니다!"
            await asyncio.to_thread(email_service.send_email, email_subject, msg)
        except Exception as e:
            logger.error(f"이메일 발송 로직 에러: {e}")
