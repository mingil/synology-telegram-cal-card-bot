# services/caldav_service.py
import caldav
from datetime import datetime, date, timedelta
import logging
from core import config

# 로깅 레벨 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def get_calendar_client():
    """CalDAV 클라이언트 연결 및 반환"""
    try:
        if not all([config.CALDAV_URL, config.CALDAV_USER, config.CALDAV_PASSWORD]):
            logger.error("❌ CalDAV 설정 누락")
            return None

        client = caldav.DAVClient(
            url=config.CALDAV_URL,
            username=config.CALDAV_USER,
            password=config.CALDAV_PASSWORD
        )
        return client
    except Exception as e:
        logger.error(f"❌ CalDAV 클라이언트 연결 실패: {e}")
        return None

def get_calendars():
    """모든 캘린더 목록 반환"""
    client = get_calendar_client()
    if not client:
        return []
    
    try:
        principal = client.principal()
        return principal.calendars()
    except Exception as e:
        logger.error(f"❌ 캘린더 목록 조회 실패: {e}")
        return []

def add_event(calendar_url, event_details):
    """일정 추가"""
    client = get_calendar_client()
    if not client:
        return False, "서버 연결 실패"

    try:
        calendar = client.calendar(url=calendar_url)
        
        dtstart = event_details.get("dtstart")
        dtend = event_details.get("dtend")
        summary = event_details.get("summary", "제목 없음")
        
        calendar.save_event(
            dtstart=dtstart,
            dtend=dtend,
            summary=summary
        )
        return True, "일정이 추가되었습니다."
    except Exception as e:
        logger.error(f"일정 추가 실패: {e}")
        return False, f"추가 실패: {str(e)}"

def fetch_events(start_date: datetime, end_date: datetime):
    """
    특정 기간 내의 모든 일정 조회
    [수정] 타임존(offset) 충돌 방지를 위해 모든 시간을 Naive로 변환
    """
    client = get_calendar_client()
    if not client:
        return False, "서버 연결 실패"

    try:
        principal = client.principal()
        calendars = principal.calendars()
        
        all_events = []
        
        # 검색 범위도 Naive로 확실하게 통일
        if start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
        if end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)

        logger.info(f"🔍 검색 시작: {start_date} ~ {end_date}")
        
        for calendar in calendars:
            try:
                # 캘린더 검색
                found = calendar.search(
                    start=start_date, 
                    end=end_date, 
                    event=True, 
                    expand=True
                )
            except Exception as e:
                # 검색 실패 시 로그만 남기고 다음 캘린더로
                continue
            
            for event in found:
                try:
                    # 1. 데이터 파싱 시도
                    if hasattr(event, 'instance') and hasattr(event.instance, 'vevent'):
                        vevent = event.instance.vevent
                    elif hasattr(event, 'vobject_instance') and hasattr(event.vobject_instance, 'vevent'):
                        vevent = event.vobject_instance.vevent
                    else:
                        continue # 구조가 복잡하면 패스

                    # 2. 제목 가져오기
                    summary = getattr(vevent.summary, 'value', '제목 없음')
                    
                    # 3. 시작 시간 가져오기 및 변환 (가장 중요)
                    if hasattr(vevent, 'dtstart'):
                        dtstart = vevent.dtstart.value
                    else:
                        continue

                    # 4. 종료 시간 가져오기
                    dtend = None
                    if hasattr(vevent, 'dtend'):
                        dtend = vevent.dtend.value

                    is_allday = False
                    
                    # [핵심 수정] 
                    # datetime이 아닌 date 객체(종일 일정)라면 datetime으로 변환
                    if not isinstance(dtstart, datetime):
                        is_allday = True
                        dtstart = datetime.combine(dtstart, datetime.min.time())
                        if dtend and not isinstance(dtend, datetime):
                            dtend = datetime.combine(dtend, datetime.min.time())

                    # [핵심 수정] 
                    # 타임존 정보가 있다면 무조건 제거(Naive로 변환)하여 충돌 방지
                    if dtstart.tzinfo is not None:
                        dtstart = dtstart.replace(tzinfo=None)
                    
                    if dtend and isinstance(dtend, datetime) and dtend.tzinfo is not None:
                        dtend = dtend.replace(tzinfo=None)
                    
                    # 리스트에 추가
                    event_data = {
                        'summary': summary,
                        'start': dtstart,  # 이제 무조건 Naive datetime
                        'end': dtend,
                        'is_allday': is_allday,
                        'calendar': calendar.name,
                        'url': str(event.url) if hasattr(event, 'url') else ""
                    }
                    all_events.append(event_data)
                    
                except Exception:
                    continue

        # 이제 모든 start 시간이 Naive 상태이므로 정렬 시 에러가 나지 않음
        all_events.sort(key=lambda x: x['start'])
        
        logger.info(f"✅ 최종 추출된 일정: {len(all_events)}개")
        return True, all_events

    except Exception as e:
        logger.error(f"❌ 전체 일정 조회 프로세스 실패: {e}")
        return False, f"조회 오류: {str(e)}"