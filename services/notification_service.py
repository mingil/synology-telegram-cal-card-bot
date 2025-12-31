import logging
import asyncio
from datetime import datetime, timedelta, date, time

from core import config, database
from utils import date_utils
from services import caldav_service, email_service

logger = logging.getLogger(__name__)


def check_lunar_anniversaries() -> list[str]:
    """
    오늘/내일/N일 뒤의 '양력 날짜'를 '음력'으로 변환한 뒤,
    캘린더의 해당 [음력 월/일] 위치(과거)에 등록된 일정이 있는지 확인합니다.
    (예: 양력 12/31 -> 음력 11/12 -> 캘린더 11/12 조회)
    """
    messages = []
    today = date.today()

    # 체크할 범위: 당일(0), 하루 전(1), 일주일 전(7), 한 달 전(30)
    check_offsets = [0, 1, 7, 30]

    for offset in check_offsets:
        # 1. 체크할 타겟 날짜 (예: 오늘이 11/30이라면, 30일 뒤인 12/31을 타겟으로 잡음)
        target_solar_date = today + timedelta(days=offset)

        # 2. 타겟 날짜를 음력으로 변환 (예: 12/31 -> "2025-11-12")
        lunar_iso = date_utils.get_lunar_date_string(target_solar_date)
        if not lunar_iso:
            continue

        try:
            # 음력 월/일 추출 (11, 12)
            _, l_month_str, l_day_str = lunar_iso.split("-")
            l_month, l_day = int(l_month_str), int(l_day_str)

            # 3. 캘린더에서 조회할 '가상의 양력 날짜(Placeholder)' 생성
            # 예: 캘린더의 11월 12일(양력) 칸을 조회
            search_date = date(target_solar_date.year, l_month, l_day)

        except ValueError:
            # 윤달이나 날짜 변환 불가 시 패스
            continue
        except Exception as e:
            logger.error(f"날짜 변환 중 오류: {e}")
            continue

        # 4. 해당 날짜에 등록된 일정 가져오기
        start_dt = datetime.combine(search_date, time.min)
        end_dt = datetime.combine(search_date, time.max)

        success, events = caldav_service.fetch_events(start_dt, end_dt)

        if not success or not events:
            continue

        # 5. 일정 제목에 '음력'이 있는지 확인
        for event in events:
            summary = event.get("summary", "")

            if "음력" in summary:
                # DB 중복 발송 체크 (UID + 타겟날짜 + 알림타입)
                uid = event.get("url", summary)
                noti_type = f"lunar_{offset}day"

                if not database.is_notification_sent(
                    uid, str(target_solar_date), noti_type
                ):
                    # 알림 문구 커스터마이징
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

                    msg = (
                        f"🌕 <b>[음력 알림]</b>\n"
                        f"{d_day_str} ({target_solar_date})\n"
                        f"<b>{summary}</b> {desc_str}\n"
                        f"(음력 {l_month}월 {l_day}일)"
                    )
                    messages.append(msg)

                    # 발송 기록 저장
                    database.mark_notification_sent(
                        uid, str(target_solar_date), noti_type
                    )

    return messages


async def run_daily_checks(bot_app):
    """매일 아침 7시에 실행되는 체크 로직"""
    logger.info("⏰ 일일 알림 체크 시작")

    # 1. 알림 메시지 생성 (음력 일정 체크)
    msgs = await asyncio.to_thread(check_lunar_anniversaries)

    if not msgs:
        return

    # 2. 메시지 발송 (텔레그램 + 이메일)
    for msg in msgs:
        # [텔레그램 발송]
        if config.TARGET_CHAT_ID:
            try:
                await bot_app.bot.send_message(
                    config.TARGET_CHAT_ID, msg, parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"텔레그램 전송 실패: {e}")

        # [이메일 발송]
        try:
            # 이메일 제목 생성 (예: [봇 알림] 한 달 뒤 12/31 일정 안내)
            # 메시지 내용에서 날짜 정보 등을 간단히 파악하기 위해 단순 제목 사용
            email_subject = "📅 [Calendar Bot] 놓치면 안 되는 일정이 있습니다!"

            # 이메일 발송 (비동기로 실행하여 봇 멈춤 방지)
            await asyncio.to_thread(email_service.send_email, email_subject, msg)

        except Exception as e:
            logger.error(f"이메일 발송 로직 에러: {e}")
