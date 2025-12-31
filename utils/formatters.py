# utils/formatters.py
import html
from typing import Dict, Any, List
from utils import date_utils

def format_event_to_html(event: Dict[str, Any]) -> str:
    """일정 딕셔너리를 HTML 문자열로 변환"""
    summary = html.escape(event.get('summary', '제목 없음'))
    
    start = event.get('start')
    end = event.get('end')
    is_allday = event.get('is_allday', False)
    
    # 날짜 문자열 생성 (date_utils 활용)
    time_info = ""
    if start:
        # end가 없으면 start와 같게 처리
        if not end: 
            end = start
        time_info = date_utils.format_datetime_range(start, end, is_allday)
    
    icon = "☀️" if is_allday else "⏰"
    
    return f"📅 <b>{summary}</b>\n{icon} {time_info}"

def format_contact_list_html(contacts: List[Dict[str, Any]]) -> str:
    """연락처 리스트 포맷팅 (기존 유지)"""
    if not contacts:
        return "검색 결과가 없습니다."
        
    lines = []
    for idx, contact in enumerate(contacts):
        name = html.escape(contact.get('name', '이름 없음'))
        details = []
        
        tels = contact.get('tel', [])
        if tels: details.append(f"📞 " + ", ".join(html.escape(t) for t in tels))
            
        emails = contact.get('email', [])
        if emails: details.append(f"📧 " + ", ".join(html.escape(e) for e in emails))
             
        org = contact.get('org', '')
        title = contact.get('title', '')
        if org or title: details.append(f"🏢 {html.escape(f'{org} {title}'.strip())}")
            
        adrs = contact.get('adr', [])
        for a in adrs:
            if a: details.append(f"🏠 {html.escape(a)}")
                
        note = contact.get('note', '')
        if note: details.append(f"📝 {html.escape(note)}")

        entry = f"<b>{idx + 1}. {name}</b>"
        if details: entry += "\n" + "\n".join(details)
        lines.append(entry)
        
    return "\n\n".join(lines)