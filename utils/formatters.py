# utils/formatters.py
import html
from typing import Dict, Any, List

def format_event_to_html(event: Dict[str, Any]) -> str:
    """일정 딕셔너리를 HTML 문자열로 변환"""
    summary = html.escape(event.get('summary', '제목 없음'))
    start_str = event.get('start_time_str', '')
    end_str = event.get('end_time_str', '')
    is_allday = event.get('is_allday', False)

    icon = "☀️" if is_allday else "⏰"
    time_info = f"{start_str}"
    
    if end_str and end_str != start_str:
        time_info += f" ~ {end_str}"

    return f"📅 <b>{summary}</b>\n{icon} {time_info}"

def format_contact_list_html(contacts: List[Dict[str, Any]]) -> str:
    """연락처 리스트를 상세한 HTML 문자열로 변환 (문제 2 해결)"""
    if not contacts:
        return "검색 결과가 없습니다."
        
    lines = []
    for idx, contact in enumerate(contacts):
        name = html.escape(contact.get('name', '이름 없음'))
        
        # 상세 정보 구성
        details = []
        
        # 전화번호
        tels = contact.get('tel', [])
        if tels:
            details.append(f"📞 " + ", ".join(html.escape(t) for t in tels))
            
        # 이메일
        emails = contact.get('email', [])
        if emails:
             details.append(f"📧 " + ", ".join(html.escape(e) for e in emails))
             
        # 회사/직함
        org = contact.get('org', '')
        title = contact.get('title', '')
        if org or title:
            comp_info = f"{org} {title}".strip()
            details.append(f"🏢 {html.escape(comp_info)}")
            
        # 주소
        adrs = contact.get('adr', [])
        if adrs:
            for a in adrs:
                if a: details.append(f"🏠 {html.escape(a)}")
                
        # 메모
        note = contact.get('note', '')
        if note:
            details.append(f"📝 {html.escape(note)}")

        # 합치기
        entry = f"<b>{idx + 1}. {name}</b>"
        if details:
            entry += "\n" + "\n".join(details)
            
        lines.append(entry)
        
    return "\n\n".join(lines)