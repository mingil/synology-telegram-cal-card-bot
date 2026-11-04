"""
날짜 및 시간 처리, 음력 변환 관련 유틸리티 함수
"""
import datetime
import zoneinfo
from typing import Optional
from korean_lunar_calendar import KoreanLunarCalendar
from core import config

def get_timezone() -> zoneinfo.ZoneInfo:
    """설정된 타임존 객체 반환"""
    try:
        return zoneinfo.ZoneInfo(config.TIMEZONE)
    except Exception:
        return zoneinfo.ZoneInfo("Asia/Seoul")  # fallback

def get_today() -> datetime.date:
    """도커 컨테이너의 UTC 시간 오류를 방어하기 위해 설정된 타임존 기준 오늘 날짜 반환"""
    return datetime.datetime.now(get_timezone()).date()

def get_lunar_date_string(solar_date: datetime.date) -> str:
    """양력 날짜를 받아서 'YYYY-MM-DD' 형태의 음력 문자열로 반환"""
    calendar = KoreanLunarCalendar()
    calendar.setSolarDate(solar_date.year, solar_date.month, solar_date.day)
    return calendar.LunarIsoFormat()

def parse_date_string(date_str: str) -> Optional[datetime.date]:
    """문자열을 날짜 객체로 변환 (YYYY-MM-DD)"""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None

def format_datetime_range(start, end, is_allday: bool) -> str:
    """시작/종료 시간을 보기 좋은 문자열로 변환 (CalDAV 타입 에러 방어 포함)"""
    # CalDAV에서 시간 없이 순수 date 객체로 데이터가 들어오는 경우 종일로 간주
    is_start_date = isinstance(start, datetime.date) and not isinstance(start, datetime.datetime)
    is_end_date = isinstance(end, datetime.date) and not isinstance(end, datetime.datetime)

    if is_allday or is_start_date:
        return f"{start.strftime('%Y-%m-%d')} (종일)"

    start_str = start.strftime("%Y-%m-%d %H:%M")

    # 같은 날짜인지 비교를 위해 date() 추출
    start_d = start.date() if isinstance(start, datetime.datetime) else start
    end_d = end.date() if isinstance(end, datetime.datetime) else end

    # end가 단순 date이거나, 같은 날이면 시간만 표시
    if is_end_date or start_d == end_d:
        end_str = end.strftime("%H:%M") if isinstance(end, datetime.datetime) else ""
    else:
        end_str = end.strftime("%Y-%m-%d %H:%M") if isinstance(end, datetime.datetime) else end.strftime("%Y-%m-%d")

    return f"{start_str} ~ {end_str}" if end_str else start_str
