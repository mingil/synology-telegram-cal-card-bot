import html
from typing import Dict, Any, List
from utils import date_utils

def format_event_to_html(event: Dict[str, Any]) -> str:
    """일정 딕셔너리를 HTML 문자열로 변환 (안전한 이스케이프 처리)"""
    # summary가 비어있을 수 있으므로 안전하게 처리
    summary = html.escape(str(event.get('summary') or '제목 없음').strip())

    start = event.get('start')
    end = event.get('end')
    is_allday = event.get('is_allday', False)

    time_info = ""
    if start:
        # end가 없으면 start와 같게 처리하여 봇 에러 방어
        end = end or start
        time_info = html.escape(date_utils.format_datetime_range(start, end, is_allday))

    icon = "☀️" if is_allday else "⏰"

    return f"📅 <b>{summary}</b>\n{icon} {time_info}"

def format_contact_list_html(contacts: List[Dict[str, Any]]) -> str:
    """연락처 리스트 포맷팅 (바다코끼리 연산자 적용)"""
    if not contacts:
        return "검색 결과가 없습니다."

    lines = []
    for idx, contact in enumerate(contacts, start=1):
        name = html.escape(str(contact.get('name') or '이름 없음').strip())
        details = []

        # := (바다코끼리 연산자)를 사용하여 값이 있을 때만 if문 통과 및 리스트 추가
        if tels := contact.get('tel'):
            details.append("📞 " + ", ".join(html.escape(str(t)) for t in tels if t))

        if emails := contact.get('email'):
            details.append("📧 " + ", ".join(html.escape(str(e)) for e in emails if e))

        org = str(contact.get('org') or '').strip()
        title = str(contact.get('title') or '').strip()
        if org_title := " ".join(filter(None, [org, title])):
            details.append(f"🏢 {html.escape(org_title)}")

        if adrs := contact.get('adr'):
            for a in adrs:
                if a and str(a).strip():
                    details.append(f"🏠 {html.escape(str(a).strip())}")

        if note := contact.get('note'):
            if note_str := str(note).strip():
                details.append(f"📝 {html.escape(note_str)}")

        entry = f"<b>{idx}. {name}</b>"
        if details:
            entry += "\n" + "\n".join(details)
        lines.append(entry)

    return "\n\n".join(lines)
