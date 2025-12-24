# services/carddav_service.py
import logging
import requests
import vobject
import uuid # [추가] UUID 생성을 위해
from typing import List, Dict, Any, Tuple, Union, Optional
from core import config

logger = logging.getLogger(__name__)

def _get_auth():
    return requests.auth.HTTPBasicAuth(config.CARDDAV_USERNAME, config.CARDDAV_PASSWORD)

def search_contacts(keyword: str) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """연락처 검색 (상세 정보 포함)"""
    try:
        headers = {'Content-Type': 'application/xml; charset=utf-8', 'Depth': '1'}
        # 검색 필터 (이름에 키워드가 포함된 경우)
        xml_query = f"""
        <c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
            <d:prop><d:getetag /><c:address-data /></d:prop>
            <c:filter>
                <c:prop-filter name="FN">
                    <c:text-match collation="i;unicode-casemap" match-type="contains">{keyword}</c:text-match>
                </c:prop-filter>
            </c:filter>
        </c:addressbook-query>
        """
        response = requests.request('REPORT', config.CARDDAV_URL, auth=_get_auth(), headers=headers, data=xml_query.encode('utf-8'))
        
        if response.status_code not in [200, 207]:
            return False, f"서버 응답 오류: {response.status_code}"

        contacts = []
        import re
        # vCard 데이터 블록 추출
        vcard_blocks = re.findall(r'BEGIN:VCARD.*?END:VCARD', response.text, re.DOTALL)
        
        for vcard_str in vcard_blocks:
            try:
                v = vobject.readOne(vcard_str)
                
                # [문제 2 해결] 상세 정보 추출 강화
                name = v.fn.value if hasattr(v, 'fn') else 'No Name'
                
                # 전화번호 (여러 개)
                tels = []
                if hasattr(v, 'tel_list'):
                    for t in v.tel_list:
                        t_type = f"({t.type_param})" if hasattr(t, 'type_param') else ""
                        tels.append(f"{t.value} {t_type}")
                
                # 이메일 (여러 개)
                emails = []
                if hasattr(v, 'email_list'):
                    for e in v.email_list:
                        emails.append(e.value)
                
                # 주소 (ADR)
                adrs = []
                if hasattr(v, 'adr_list'):
                    for a in v.adr_list:
                        # vObject의 ADR 값은 복잡한 객체이므로 문자열로 변환 필요
                        adrs.append(str(a.value).strip())

                # 회사 (ORG)
                org = ""
                if hasattr(v, 'org'):
                    # org.value는 리스트일 수 있음
                    val = v.org.value
                    if isinstance(val, list): org = " ".join(val)
                    else: org = str(val)

                # 직함 (TITLE)
                title = v.title.value if hasattr(v, 'title') else ""

                # 메모 (NOTE)
                note = v.note.value if hasattr(v, 'note') else ""

                contacts.append({
                    'name': name,
                    'tel': tels,
                    'email': emails,
                    'adr': adrs,
                    'org': org,
                    'title': title,
                    'note': note
                })
            except Exception as e:
                logger.error(f"vCard 파싱 중 오류: {e}")
                continue
            
        return True, contacts
    except Exception as e:
        logger.error(f"CardDAV 검색 오류: {e}")
        return False, str(e)

def add_contact(name: str, phone: Optional[str], email: Optional[str]) -> Tuple[bool, str]:
    """연락처 추가"""
    try:
        v = vobject.vCard()
        v.add('n'); v.n.value = vobject.vcard.Name(family=name, given='')
        v.add('fn'); v.fn.value = name
        
        if phone: 
            t = v.add('tel')
            t.value = phone
            t.type_param = 'CELL'
            
        if email: 
            e = v.add('email')
            e.value = email
            e.type_param = 'WORK'
        
        # [문제 3 해결] get_ident() -> uuid 사용
        filename = f"{str(uuid.uuid4())}.vcf"
        put_url = config.CARDDAV_URL.rstrip('/') + '/' + filename
        
        response = requests.put(
            put_url, 
            auth=_get_auth(), 
            headers={'Content-Type': 'text/vcard'}, 
            data=v.serialize().encode('utf-8')
        )
        
        if response.status_code in [201, 204, 200]: 
            return True, "✅ 연락처가 저장되었습니다!"
        return False, f"❌ 서버 저장 실패: {response.status_code}"
    except Exception as e:
        logger.error(f"연락처 추가 오류: {e}")
        return False, f"오류 발생: {str(e)}"