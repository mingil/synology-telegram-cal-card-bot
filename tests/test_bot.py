import os
import sys
import datetime
from unittest.mock import patch

import pytest

# 프로젝트 루트를 Python 경로에 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import config, database
from utils import date_utils, formatters
from services import carddav_service, notification_service
import handlers.auth as h_auth
import handlers.ai as h_ai
import handlers.calendar as h_cal
import handlers.contact as h_contact


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """실제 운영 DB(data/notifications.db)를 건드리지 않도록 임시 DB로 격리"""
    test_db_file = str(tmp_path / "test_notifications.db")
    monkeypatch.setattr(config, "DB_FILE", test_db_file)
    database.init_db()
    return test_db_file


def test_database_user_and_notification_ops(temp_db):
    # 1. 차단/해제 테스트
    assert not database.is_user_banned(11111)
    database.ban_user(11111)
    assert database.is_user_banned(11111)
    assert 11111 in database.get_banned_users()
    assert database.unban_user_db(11111)
    assert not database.is_user_banned(11111)

    # 2. 허용/취소 테스트
    assert not database.is_user_permitted(22222)
    database.add_permitted_user(22222)
    assert database.is_user_permitted(22222)
    assert 22222 in database.get_permitted_users()
    assert database.revoke_permission(22222)
    assert not database.is_user_permitted(22222)

    # 3. 알림 발송 기록 중복 방지 테스트
    uid = "https://nas/cal/event-1.ics"
    target_date = "2026-11-03"
    noti_type = "anniversary_0day"
    assert not database.is_notification_sent(uid, target_date, noti_type)
    database.mark_notification_sent(uid, target_date, noti_type)
    assert database.is_notification_sent(uid, target_date, noti_type)


def test_date_utils_and_formatters():
    today = date_utils.get_today()
    assert isinstance(today, datetime.date)

    parsed = date_utils.parse_date_string("2026-11-03")
    assert parsed == datetime.date(2026, 11, 3)
    assert date_utils.parse_date_string("invalid-date") is None

    lunar_str = date_utils.get_lunar_date_string(datetime.date(2026, 11, 3))
    assert len(lunar_str) == 10 and lunar_str.count("-") == 2

    # HTML 특수문자 이스케이프 검증
    evt_html = formatters.format_event_to_html({
        "summary": "A & B <중요> 미팅",
        "start": datetime.datetime(2026, 11, 3, 14, 0),
        "end": datetime.datetime(2026, 11, 3, 15, 30),
        "is_allday": False,
    })
    assert "A &amp; B &lt;중요&gt; 미팅" in evt_html
    assert "2026-11-03 14:00 ~ 15:30" in evt_html


def test_carddav_parsing_and_deep_search():
    sample_vcard_xml = """
    <d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
      <d:response>
        <c:address-data>BEGIN:VCARD
VERSION:3.0
FN:홍길동
N:홍길동;;;;
TEL;TYPE=CELL:010-1234-5678
EMAIL;TYPE=WORK:hong@synology.local
ORG:시놀로지코리아
TITLE:수석엔지니어
NOTE:VIP 거래처 담당자
END:VCARD</c:address-data>
      </d:response>
    </d:multistatus>
    """
    contacts = carddav_service._parse_vcards(sample_vcard_xml)
    assert len(contacts) == 1
    c = contacts[0]
    assert c["name"] == "홍길동"
    assert any("010-1234-5678" in t for t in c["tel"])
    assert "hong@synology.local" in c["email"]
    assert c["org"] == "시놀로지코리아"
    assert c["note"] == "VIP 거래처 담당자"

    # 이름 전용 검색 vs 통합 상세 검색(하이픈 없는 전화번호, 메모, 회사명) 검증
    assert carddav_service._matches_contact(c, "홍길동", name_only=True)
    assert not carddav_service._matches_contact(c, "거래처", name_only=True)
    assert carddav_service._matches_contact(c, "거래처", name_only=False)
    assert carddav_service._matches_contact(c, "01012345678", name_only=False)
    assert carddav_service._matches_contact(c, "hong@synology", name_only=False)


def test_notification_service_lunar_and_solar_detection(temp_db):
    today = date_utils.get_today()
    tomorrow = today + datetime.timedelta(days=1)
    next_week = today + datetime.timedelta(days=7)

    # 내일(양력)에 해당하는 음력 날짜 계산
    tomorrow_lunar_iso = date_utils.get_lunar_date_string(tomorrow)
    tomorrow_lunar_date = date_utils.parse_date_string(tomorrow_lunar_iso)

    captured_range = {}

    def fake_fetch_events(start_dt, end_dt):
        captured_range["start_dt"] = start_dt
        captured_range["end_dt"] = end_dt
        return True, [
            {
                "summary": "음력 어머니 생신",
                "start": datetime.datetime.combine(tomorrow_lunar_date, datetime.time.min),
                "end": datetime.datetime.combine(tomorrow_lunar_date, datetime.time.min),
                "is_allday": True,
                "calendar": "가족",
                "url": "https://nas/cal/lunar-bday.ics",
            },
            {
                "summary": "결혼기념일 <10주년>",
                "start": datetime.datetime.combine(next_week, datetime.time.min),
                "end": datetime.datetime.combine(next_week, datetime.time.min),
                "is_allday": True,
                "calendar": "가족",
                "url": "https://nas/cal/wedding.ics",
            },
        ]

    with patch("services.caldav_service.fetch_events", side_effect=fake_fetch_events):
        notis = notification_service.check_anniversaries()

    # 1. 조회 시작 범위가 음력 날짜(양력보다 약 1~2달 앞선 날짜)를 반드시 포함해야 함
    assert captured_range["start_dt"].date() <= tomorrow_lunar_date
    assert captured_range["end_dt"].date() >= next_week

    # 2. 음력 알림 + 양력 알림 총 2건 모두 정상 생성되어야 함
    assert len(notis) == 2
    bodies = "\n".join(n["body"] for n in notis)
    assert "음력 어머니 생신" in bodies
    assert "결혼기념일 &lt;10주년&gt;" in bodies

    # 3. 발송 전(기록 전)에 재실행하면 같은 알림이 다시 나와야 함 → 발송 실패 시 유실 방지
    with patch("services.caldav_service.fetch_events", side_effect=fake_fetch_events):
        notis_retry = notification_service.check_anniversaries()
    assert len(notis_retry) == 2

    # 4. 발송 성공으로 기록한 뒤 재실행하면 DB 중복 방지 로직으로 0건이어야 함
    for n in notis:
        database.mark_notification_sent(*n["mark"])
    with patch("services.caldav_service.fetch_events", side_effect=fake_fetch_events):
        notis_second = notification_service.check_anniversaries()
    assert len(notis_second) == 0


def test_conversation_states_are_strictly_unique():
    """통합 ConversationHandler에서 상태 값 충돌이 절대 발생하지 않는지 검증"""
    all_state_enums = [
        h_auth.AuthStates,
        h_auth.AdminStates,
        h_ai.AskAIStates,
        h_cal.DateInputStates,
        h_cal.SearchEventsStates,
        h_cal.AddEventStates,
        h_contact.FindContactStates,
        h_contact.SearchContactStates,
        h_contact.AddContactStates,
    ]
    seen_values = set()
    for enum_cls in all_state_enums:
        for member in enum_cls:
            assert int(member) not in seen_values, f"Duplicate state value found: {member} ({int(member)})"
            seen_values.add(int(member))
