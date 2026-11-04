import caldav
from datetime import datetime, date, timedelta
import logging
import zoneinfo
from core import config

logger = logging.getLogger(__name__)
NETWORK_TIMEOUT = 10.0

# [최적화] 매 일정마다 무거운 타임존 객체를 생성하지 않도록 전역 변수로 분리 (CPU 부하 감소)
try:
    KST_TZ = zoneinfo.ZoneInfo(config.TIMEZONE)
except Exception:
    KST_TZ = zoneinfo.ZoneInfo("Asia/Seoul")


def get_calendar_client():
    if not all([config.CALDAV_URL, config.CALDAV_USER, config.CALDAV_PASSWORD]):
        logger.error("❌ CalDAV 설정 누락")
        return None

    try:
        return caldav.DAVClient(
            url=config.CALDAV_URL,
            username=config.CALDAV_USER,
            password=config.CALDAV_PASSWORD,
            timeout=NETWORK_TIMEOUT,
        )
    except Exception as e:
        logger.error(f"❌ CalDAV 클라이언트 연결 실패: {e}")
        return None


def get_calendars():
    if client := get_calendar_client():
        try:
            calendars = client.principal().calendars()
            if config.CALENDAR_NAME:
                filtered = [c for c in calendars if c.name == config.CALENDAR_NAME]
                return filtered if filtered else calendars
            return calendars
        except Exception as e:
            logger.error(f"❌ 캘린더 목록 조회 실패: {e}")
    return []


def add_event(calendar_url: str, event_details: dict) -> tuple[bool, str]:
    if not (client := get_calendar_client()):
        return False, "서버 연결 실패"

    try:
        calendar = client.calendar(url=calendar_url)
        dtstart = event_details.get("dtstart")
        dtend = event_details.get("dtend")
        summary = event_details.get("summary", "제목 없음")

        # iCalendar(RFC 5545) 규격에 맞게 시작/종료 일시 타입 및 기본값 보정
        if isinstance(dtstart, datetime):
            if dtend is None:
                dtend = dtstart + timedelta(hours=1)
            elif isinstance(dtend, date) and not isinstance(dtend, datetime):
                dtend = datetime.combine(dtend, dtstart.time())
            if dtend <= dtstart:
                dtend = dtstart + timedelta(hours=1)
        elif isinstance(dtstart, date):
            if dtend is None:
                dtend = dtstart + timedelta(days=1)
            elif isinstance(dtend, datetime):
                dtend = dtend.date()
            if dtend <= dtstart:
                dtend = dtstart + timedelta(days=1)

        calendar.save_event(
            dtstart=dtstart,
            dtend=dtend,
            summary=summary,
        )
        return True, "일정이 추가되었습니다."
    except Exception as e:
        logger.error(f"❌ 일정 추가 실패: {e}")
        return False, f"추가 실패: {str(e)}"


def _make_naive(dt):
    """안전하게 한국 시간으로 변경 후 타임존 정보를 삭제하는 헬퍼 함수"""
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        try:
            return dt.astimezone(KST_TZ).replace(tzinfo=None)
        except Exception:
            return dt.replace(tzinfo=None)
    return dt


def fetch_events(start_date: datetime, end_date: datetime):
    calendars = get_calendars()
    if not calendars:
        return False, "서버 연결 실패 또는 캘린더 없음"

    try:
        all_events = []
        start_date = _make_naive(start_date)
        end_date = _make_naive(end_date)

        logger.info(f"🔍 캘린더 검색 시작: {start_date} ~ {end_date}")

        for calendar in calendars:
            try:
                found = calendar.search(
                    start=start_date, end=end_date, event=True, expand=True
                )
            except Exception:
                continue

            for event in found:
                try:
                    vevent = getattr(
                        getattr(event, "vobject_instance", None), "vevent", None
                    ) or getattr(getattr(event, "instance", None), "vevent", None)
                    if not vevent or not hasattr(vevent, "dtstart"):
                        continue

                    summary = getattr(vevent.summary, "value", "제목 없음")
                    dtstart = vevent.dtstart.value
                    dtend = (
                        getattr(vevent.dtend, "value", None)
                        if hasattr(vevent, "dtend")
                        else None
                    )

                    is_allday = not isinstance(dtstart, datetime)
                    if is_allday:
                        dtstart = datetime.combine(dtstart, datetime.min.time())
                        if dtend and not isinstance(dtend, datetime):
                            dtend = datetime.combine(dtend, datetime.min.time())

                    naive_start = _make_naive(dtstart)
                    naive_end = _make_naive(dtend) if dtend else naive_start

                    # 전날 종일 일정의 종료 시각(오늘 00:00:00)이 검색 시작 시각에 걸려 잘못 포함되는 현상 차단
                    if is_allday and naive_end > naive_start and naive_end <= start_date:
                        continue
                    if not is_allday and naive_end < start_date:
                        continue
                    if naive_start > end_date:
                        continue

                    all_events.append({
                        "summary": str(summary),
                        "start": naive_start,
                        "end": naive_end,
                        "is_allday": is_allday,
                        "calendar": calendar.name,
                        "url": str(getattr(event, "url", "")),
                    })
                except Exception:
                    continue

        all_events.sort(key=lambda x: x["start"])
        return True, all_events
    except Exception as e:
        logger.error(f"❌ 전체 일정 조회 실패: {e}")
        return False, f"조회 오류: {str(e)}"
