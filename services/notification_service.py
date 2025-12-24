# services/notification_service.py
import logging
import asyncio
from datetime import datetime, timedelta, date

from core import config, database
from utils import date_utils
from services import caldav_service

logger = logging.getLogger(__name__)


def check_lunar_anniversaries() -> list[str]:
    """
    오늘/내일/N일 뒤가 음력 기념일인지 확인하고 알림 메시지 리스트 반환
    """
    messages = []
    today = date.today()

    # 체크할 범위: 오늘(0), 내일(1), 7일 뒤, 15일 뒤 등
    check_offsets = [0, 1, 3, 7]

    # 1. 캘린더에서 '음력' 키워드가 포함된 일정 조회 (앞으로 60일치 넉넉히)
    search_start = datetime.combine(today, datetime.min.time())
    search_end = search_start + timedelta(days=60)

    success, events = caldav_service.fetch_events(search_start, search_end)
    if not success or not isinstance(events, list):
        return []

    # 2. 각 날짜별로 음력 변환 후 매칭
    for offset in check_offsets:
        target_date = today + timedelta(days=offset)
        target_lunar = date_utils.get_lunar_date_string(
            target_date
        )  # "2025-01-01" 형태

        # YYYY-MM-DD 에서 MM-DD만 추출 (매년 반복이므로)
        target_lunar_mmdd = target_lunar[5:]

        for event in events:
            summary = event.get("summary", "")
            if "음력" not in summary:
                continue

            # 일정 제목 예시: "어머니 생신 (음력 01-15)"
            # 정규식으로 MM-DD 추출 로직 필요.
            # 여기서는 간단히 제목에 target_lunar_mmdd가 포함되어 있는지 확인
            # (더 정교한 파싱 로직은 utils/date_utils.py에 parse_lunar_from_title 등을 만들어 쓰면 좋음)

            if target_lunar_mmdd in summary:
                # DB 중복 발송 체크
                uid = event.get("url", summary)  # URL을 UID로 사용
                noti_type = f"lunar_{offset}day"

                if not database.is_notification_sent(uid, str(target_date), noti_type):
                    d_day_str = (
                        "오늘"
                        if offset == 0
                        else "내일" if offset == 1 else f"{offset}일 뒤"
                    )
                    msg = (
                        f"🌕 <b>[음력 알림]</b>\n"
                        f"{d_day_str} ({target_date})은\n"
                        f"<b>{summary}</b> 입니다!\n"
                        f"(음력 {target_lunar})"
                    )
                    messages.append(msg)
                    # 발송 기록 저장
                    database.mark_notification_sent(uid, str(target_date), noti_type)

    return messages


async def run_daily_checks(bot_app):
    """매일 실행되는 체크 로직 (bot.py JobQueue에서 호출)"""
    logger.info("⏰ 일일 알림 체크 시작")

    if not config.TARGET_CHAT_ID:
        return

    # 1. 음력 알림 체크
    msgs = await asyncio.to_thread(check_lunar_anniversaries)
    for msg in msgs:
        try:
            await bot_app.bot.send_message(
                config.TARGET_CHAT_ID, msg, parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"알림 전송 실패: {e}")

    # 2. (추가 가능) 일반 일정 미리 알림 로직 등...
