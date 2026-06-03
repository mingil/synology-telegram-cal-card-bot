import caldav
from datetime import datetime, date
import logging
import zoneinfo
from core import config

logger = logging.getLogger(__name__)
NETWORK_TIMEOUT = 10.0

def get_calendar_client():
    if not all([config.CALDAV_URL, config.CALDAV_USER, config.CALDAV_PASSWORD]):
        logger.error("❌ CalDAV 설정 누락")
        return None

    try:
        # timeout 인자 주입으로 NAS 연결 불량 시 봇 무한 대기 차단
        return caldav.DAVClient(
            url=config.CALDAV_URL,
            username=config.CALDAV_USER,
            password=config.CALDAV_PASSWORD,
            timeout=NETWORK_TIMEOUT
        )
    except Exception as e:
        logger.error(f"❌ CalDAV 클라이언트 연결 실패: {e}")
        return None

def get_calendars():
    if client := get_calendar_client():
        try:
            calendars = client.principal().calendars()
            # 특정 캘린더가 지정되었다면 그것만 필터링하여 탐색 속도 향상
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
        calendar.save_event(
            dtstart=event_details.get("dtstart"),
            dtend=event_details.get("dtend"),
            summary=event_details.get("summary", "제목 없음")
        )
        return True, "✅ 일정이 추가되었습니다."
    except Exception as e:
        logger.error(f"❌ 일정 추가 실패: {e}")
        return False, f"추가 실패: {str(e)}"

def _make_naive(dt):
    """[핵심] 안전하게 한국 시간으로 변경 후 타임존 정보를 삭제하는 헬퍼 함수"""
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        try:
            tz = zoneinfo.ZoneInfo(config.TIMEZONE)
            return dt.astimezone(tz).replace(tzinfo=None)
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
                found = calendar.search(start=start_date, end=end_date, event=True, expand=True)
            except Exception:
                continue

            for event in found:
                try:
                    vevent = getattr(getattr(event, 'instance', None), 'vevent', None) or \
                             getattr(getattr(event, 'vobject_instance', None), 'vevent', None)
                    if not vevent or not hasattr(vevent, 'dtstart'):
                        continue

                    summary = getattr(vevent.summary, 'value', '제목 없음')
                    dtstart = vevent.dtstart.value
                    dtend = getattr(vevent.dtend, 'value', None) if hasattr(vevent, 'dtend') else None

                    # 종일 일정(date) -> datetime 자동 치환 로직 간소화
                    is_allday = not isinstance(dtstart, datetime)
                    if is_allday:
                        dtstart = datetime.combine(dtstart, datetime.min.time())
                        if dtend and not isinstance(dtend, datetime):
                            dtend = datetime.combine(dtend, datetime.min.time())

                    all_events.append({
                        'summary': str(summary),
                        'start': _make_naive(dtstart),
                        'end': _make_naive(dtend) if dtend else _make_naive(dtstart),
                        'is_allday': is_allday,
                        'calendar': calendar.name,
                        'url': str(getattr(event, 'url', ''))
                    })
                except Exception:
                    continue

        all_events.sort(key=lambda x: x['start'])
        return True, all_events
    except Exception as e:
        logger.error(f"❌ 전체 일정 조회 실패: {e}")
        return False, f"조회 오류: {str(e)}"
