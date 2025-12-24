# services/caldav_service.py
import logging
import caldav
from datetime import datetime, date
from typing import List, Dict, Any, Tuple, Union, Optional

from core import config
from utils import date_utils

logger = logging.getLogger(__name__)

def _get_client(url: str, username: str, password: str) -> caldav.DAVClient:
    """CalDAV 클라이언트 생성"""
    return caldav.DAVClient(
        url=url,
        username=username,
        password=password
    )

def fetch_events(start_dt: datetime, end_dt: datetime, 
                 url: str = config.CALDAV_URL, 
                 username: str = config.CALDAV_USERNAME, 
                 password: str = config.CALDAV_PASSWORD) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """
    지정된 기간의 일정을 조회합니다.
    반환값: (성공여부, 결과리스트 또는 에러메시지)
    """
    try:
        client = _get_client(url, username, password)
        principal = client.principal()
        calendars = principal.calendars()
        
        events_result = []
        
        if not calendars:
            return True, []

        for calendar in calendars:
            # caldav 라이브러리의 date_search 사용
            found = calendar.date_search(start=start_dt, end=end_dt, expand=True)
            
            for event in found:
                # 데이터 파싱
                vevent = event.instance.vevent
                summary = str(vevent.summary.value)
                
                dtstart = vevent.dtstart.value
                dtend = None
                if hasattr(vevent, 'dtend'):
                    dtend = vevent.dtend.value

                # 종일 일정 여부 확인
                is_allday = False
                if isinstance(dtstart, date) and not isinstance(dtstart, datetime):
                    is_allday = True
                
                # datetime 변환 (비교 및 출력을 위해)
                if is_allday:
                    start_str = dtstart.strftime('%Y-%m-%d')
                    end_str = dtend.strftime('%Y-%m-%d') if dtend else ""
                else:
                    start_str = dtstart.strftime('%H:%M')
                    end_str = dtend.strftime('%H:%M') if dtend else ""

                events_result.append({
                    'summary': summary,
                    'start_time_str': start_str,
                    'end_time_str': end_str,
                    'is_allday': is_allday,
                    'start_dt': dtstart, # 정렬용 원본 데이터
                    'url': str(event.url) # 삭제 시 필요
                })

        # 시간순 정렬
        events_result.sort(key=lambda x: (isinstance(x['start_dt'], date) and not isinstance(x['start_dt'], datetime), x['start_dt']))
        
        return True, events_result

    except Exception as e:
        logger.error(f"CalDAV 조회 오류: {e}", exc_info=True)
        return False, f"일정 조회 실패: {str(e)}"

def add_event(calendar_url: str, event_data: Dict[str, Any],
              base_url: str = config.CALDAV_URL,
              username: str = config.CALDAV_USERNAME,
              password: str = config.CALDAV_PASSWORD) -> Tuple[bool, str]:
    """새 일정을 추가합니다."""
    try:
        client = _get_client(base_url, username, password)
        # 특정 캘린더 객체 찾기 (URL 매칭이 어려우면 첫 번째 캘린더 사용 등 로직 조정 필요)
        # 여기서는 간단히 calendar_url로 캘린더 객체를 복원한다고 가정하거나
        # principal.calendar(cal_id) 등을 사용해야 함. 
        # *편의상* 가장 간단한 '첫번째 캘린더' 혹은 '기본 캘린더'에 추가하는 방식으로 구현합니다.
        
        principal = client.principal()
        calendars = principal.calendars()
        target_calendar = calendars[0] if calendars else None
        
        # 만약 calendar_url로 정확히 찾으려면 반복문으로 url 비교 필요
        if calendar_url:
            for cal in calendars:
                if str(cal.url) == calendar_url:
                    target_calendar = cal
                    break
        
        if not target_calendar:
            return False, "대상 캘린더를 찾을 수 없습니다."

        # 이벤트 생성
        target_calendar.save_event(
            dtstart=event_data['dtstart'],
            dtend=event_data['dtend'],
            summary=event_data['summary'],
            description=event_data.get('description', '')
        )
        return True, f"일정 '{event_data['summary']}' 추가 완료!"

    except Exception as e:
        logger.error(f"일정 추가 실패: {e}", exc_info=True)
        return False, f"오류 발생: {e}"

def delete_event(event_url: str,
                 base_url: str = config.CALDAV_URL,
                 username: str = config.CALDAV_USERNAME,
                 password: str = config.CALDAV_PASSWORD) -> Tuple[bool, str]:
    """일정 삭제 (URL 기반)"""
    try:
        client = _get_client(base_url, username, password)
        # event_url을 통해 이벤트 객체를 로드하고 삭제
        # caldav 라이브러리 버전에 따라 event_by_url 지원 여부 확인 필요
        # 여기서는 calendar 검색 후 url 매칭 방식 사용 (안전함)
        
        principal = client.principal()
        calendars = principal.calendars()
        
        for calendar in calendars:
            # 캘린더 내 이벤트 검색 (최적화 필요할 수 있음)
            # URL을 알고 있으므로 client.event_by_url(event_url) 시도
            try:
                event = client.event_by_url(event_url)
                event.delete()
                return True, "일정이 삭제되었습니다."
            except:
                continue

        return False, "해당 일정을 찾을 수 없습니다."

    except Exception as e:
        logger.error(f"삭제 오류: {e}")
        return False, str(e)

def get_calendars(url: str = config.CALDAV_URL, 
                  username: str = config.CALDAV_USERNAME, 
                  password: str = config.CALDAV_PASSWORD) -> Tuple[bool, List[Dict[str, str]]]:
    """사용 가능한 캘린더 목록 조회"""
    try:
        client = _get_client(url, username, password)
        calendars = client.principal().calendars()
        result = [{'name': c.name or "캘린더", 'url': str(c.url)} for c in calendars]
        return True, result
    except Exception as e:
        return False, []