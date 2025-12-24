# utils/date_utils.py
"""
날짜 및 시간 처리, 음력 변환 관련 유틸리티 함수
"""
import datetime
from typing import Optional, Union
from korean_lunar_calendar import KoreanLunarCalendar


def get_today() -> datetime.date:
    """오늘 날짜 반환"""
    return datetime.date.today()


def get_lunar_date_string(solar_date: datetime.date) -> str:
    """양력 날짜를 받아서 'YYYY-MM-DD' 형태의 음력 문자열로 반환"""
    calendar = KoreanLunarCalendar()
    calendar.setSolarDate(solar_date.year, solar_date.month, solar_date.day)
    return calendar.LunarIsoFormat()


def parse_date_string(date_str: str) -> Optional[datetime.date]:
    """문자열을 날짜 객체로 변환 (YYYY-MM-DD)"""
    try:
        # 공백 제거 및 기본 파싱
        clean_str = date_str.strip()
        return datetime.datetime.strptime(clean_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_datetime_range(
    start: datetime.datetime, end: datetime.datetime, is_allday: bool
) -> str:
    """시작/종료 시간을 보기 좋은 문자열로 변환"""
    if is_allday:
        return f"{start.strftime('%Y-%m-%d')} (종일)"

    start_str = start.strftime("%Y-%m-%d %H:%M")
    # 같은 날이면 종료 시간은 시간만 표시
    if start.date() == end.date():
        end_str = end.strftime("%H:%M")
    else:
        end_str = end.strftime("%Y-%m-%d %H:%M")

    return f"{start_str} ~ {end_str}"
