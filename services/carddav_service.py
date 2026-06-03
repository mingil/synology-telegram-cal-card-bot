import logging
import requests
import vobject
import uuid
import re
import html
from typing import List, Dict, Any, Tuple, Union, Optional
from core import config

logger = logging.getLogger(__name__)

# 정규식 사전 컴파일 (검색 속도 극대화) 및 타임아웃
VCARD_PATTERN = re.compile(r'BEGIN:VCARD.*?END:VCARD', re.DOTALL)
NETWORK_TIMEOUT = 10.0

def _get_auth():
    return requests.auth.HTTPBasicAuth(config.CARDDAV_USERNAME, config.CARDDAV_PASSWORD)

def search_contacts(keyword: str) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """연락처 검색 (XML Injection 방어 및 Timeout 적용)"""
    try:
        headers = {'Content-Type': 'application/xml; charset=utf-8', 'Depth': '1'}
        safe_keyword = html.escape(keyword)  # [보안] XML 깨짐 방지
        xml_query = f"""
        <c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
            <d:prop><d:getetag /><c:address-data /></d:prop>
            <c:filter>
                <c:prop-filter name="FN">
                    <c:text-match collation="i;unicode-casemap" match-type="contains">{safe_keyword}</c:text-match>
                </c:prop-filter>
            </c:filter>
        </c:addressbook-query>
        """
        # [핵심] timeout=10.0 지정으로 NAS 절전모드 시 봇 멈춤 방어
        response = requests.request(
            'REPORT', config.CARDDAV_URL, auth=_get_auth(),
            headers=headers, data=xml_query.encode('utf-8'), timeout=NETWORK_TIMEOUT
        )

        if response.status_code not in [200, 207]:
            return False, f"서버 응답 오류: {response.status_code}"

        contacts = []
        vcard_blocks = VCARD_PATTERN.findall(response.text)

        for vcard_str in vcard_blocks:
            try:
                v = vobject.readOne(vcard_str)
                name = getattr(v, 'fn', getattr(v, 'n', None))
                name_val = name.value if name else 'No Name'

                # 리스트 컴프리헨션으로 데이터 파싱 코드 간결화 및 속도 향상
                tels = [f"{t.value} ({t.type_param})" if hasattr(t, 'type_param') else str(t.value) for t in getattr(v, 'tel_list', [])]
                emails = [str(e.value) for e in getattr(v, 'email_list', [])]
                adrs = [str(a.value).strip() for a in getattr(v, 'adr_list', [])]

                org_val = getattr(v, 'org', None)
                org = " ".join(org_val.value) if isinstance(getattr(org_val, 'value', None), list) else str(getattr(org_val, 'value', ''))

                title = getattr(getattr(v, 'title', None), 'value', "")
                note = getattr(getattr(v, 'note', None), 'value', "")

                contacts.append({
                    'name': name_val, 'tel': tels, 'email': emails,
                    'adr': adrs, 'org': org.strip(), 'title': title, 'note': note
                })
            except Exception as e:
                logger.debug(f"vCard 파싱 중 오류 (건너뜀): {e}")
                continue

        return True, contacts
    except requests.Timeout:
        logger.error("❌ CardDAV 서버 연결 시간 초과")
        return False, "NAS 서버 응답이 지연되고 있습니다."
    except Exception as e:
        logger.error(f"❌ CardDAV 검색 오류: {e}")
        return False, str(e)

def add_contact(name: str, phone: Optional[str], email: Optional[str]) -> Tuple[bool, str]:
    """연락처 추가 (Timeout 적용)"""
    try:
        v = vobject.vCard()
        v.add('n').value = vobject.vcard.Name(family=name, given='')
        v.add('fn').value = name

        if phone:
            t = v.add('tel')
            t.value = phone
            t.type_param = 'CELL'

        if email:
            e = v.add('email')
            e.value = email
            e.type_param = 'WORK'

        filename = f"{uuid.uuid4()}.vcf"
        put_url = f"{config.CARDDAV_URL.rstrip('/')}/{filename}"

        # [핵심] timeout=10.0 지정
        response = requests.put(
            put_url, auth=_get_auth(), headers={'Content-Type': 'text/vcard'},
            data=v.serialize().encode('utf-8'), timeout=NETWORK_TIMEOUT
        )

        if response.status_code in [201, 204, 200]:
            return True, "✅ 연락처가 저장되었습니다!"
        return False, f"❌ 서버 저장 실패: {response.status_code}"
    except requests.Timeout:
        return False, "서버 연결 시간 초과로 저장하지 못했습니다."
    except Exception as e:
        logger.error(f"❌ 연락처 추가 오류: {e}")
        return False, f"오류 발생: {str(e)}"
