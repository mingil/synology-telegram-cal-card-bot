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
VCARD_PATTERN = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.DOTALL)
DIGITS_ONLY_PATTERN = re.compile(r"\D+")
NETWORK_TIMEOUT = 10.0

# [최적화 핵심] 매번 새로 연결하지 않고 Session을 재사용하여 통신 딜레이 제거
session = requests.Session()


def _get_session() -> requests.Session:
    if config.CARDDAV_USERNAME and config.CARDDAV_PASSWORD:
        session.auth = (config.CARDDAV_USERNAME, config.CARDDAV_PASSWORD)
    return session


def _parse_vcards(response_text: str) -> List[Dict[str, Any]]:
    contacts = []
    vcard_blocks = VCARD_PATTERN.findall(response_text)

    for vcard_str in vcard_blocks:
        try:
            v = vobject.readOne(vcard_str)
            name = getattr(v, "fn", getattr(v, "n", None))
            name_val = (
                str(name.value).strip()
                if name and getattr(name, "value", None)
                else "No Name"
            )

            tels = [
                f"{t.value} ({t.type_param})"
                if hasattr(t, "type_param")
                else str(t.value)
                for t in getattr(v, "tel_list", [])
                if getattr(t, "value", None)
            ]
            emails = [
                str(e.value).strip()
                for e in getattr(v, "email_list", [])
                if getattr(e, "value", None)
            ]
            adrs = [
                str(a.value).strip()
                for a in getattr(v, "adr_list", [])
                if getattr(a, "value", None)
            ]

            org_obj = getattr(v, "org", None)
            org_raw = getattr(org_obj, "value", "") if org_obj else ""
            org = (
                " ".join(str(x) for x in org_raw)
                if isinstance(org_raw, list)
                else str(org_raw)
            )

            title = str(getattr(getattr(v, "title", None), "value", "") or "").strip()
            note = str(getattr(getattr(v, "note", None), "value", "") or "").strip()

            contacts.append({
                "name": name_val,
                "tel": tels,
                "email": emails,
                "adr": adrs,
                "org": org.strip(),
                "title": title,
                "note": note,
            })
        except Exception:
            continue

    return contacts


def _matches_contact(
    contact: Dict[str, Any], keyword: str, name_only: bool = False
) -> bool:
    kw_lower = keyword.lower().strip()
    if not kw_lower:
        return False

    name_str = str(contact.get("name", "")).lower()
    if kw_lower in name_str:
        return True
    if name_only:
        return False

    # 일반 텍스트 필드 매칭 (전화번호, 이메일, 회사, 직함, 메모, 주소)
    fields = [
        " ".join(contact.get("tel", [])),
        " ".join(contact.get("email", [])),
        str(contact.get("org", "")),
        str(contact.get("title", "")),
        str(contact.get("note", "")),
        " ".join(contact.get("adr", [])),
    ]
    combined = " ".join(fields).lower()
    if kw_lower in combined:
        return True

    # 숫자(전화번호) 하이픈(-) 무시 매칭 (예: 01012345678 <-> 010-1234-5678)
    kw_digits = DIGITS_ONLY_PATTERN.sub("", kw_lower)
    if len(kw_digits) >= 3:
        for tel in contact.get("tel", []):
            tel_digits = DIGITS_ONLY_PATTERN.sub("", str(tel))
            if kw_digits in tel_digits:
                return True

    return False


def search_contacts(
    keyword: str, name_only: bool = False
) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """연락처 검색 (시놀로지 CardDAV 규격 완벽 호환: 이름 검색 및 번호/이메일/메모/회사 통합 상세 검색)"""
    if (
        not config.CARDDAV_URL
        or not config.CARDDAV_USERNAME
        or not config.CARDDAV_PASSWORD
    ):
        logger.error("❌ CardDAV 설정 누락")
        return False, "CardDAV 연락처 서버 설정이 누락되었습니다."

    keyword = (keyword or "").strip()
    if not keyword:
        return False, "검색어를 입력해주세요."

    try:
        sess = _get_session()
        headers = {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"}
        safe_keyword = html.escape(keyword)

        if name_only:
            xml_query = f"""<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
                <d:prop><d:getetag /><c:address-data /></d:prop>
                <c:filter>
                    <c:prop-filter name="FN">
                        <c:text-match collation="i;unicode-casemap" match-type="contains">{safe_keyword}</c:text-match>
                    </c:prop-filter>
                </c:filter>
            </c:addressbook-query>"""
        else:
            # 시놀로지 Contacts 서버는 다중 prop-filter(anyof) 시 500 에러를 반환하므로,
            # 단일 FN 존재 필터로 전체 주소록을 고속 조회한 뒤 파이썬에서 전화번호(하이픈 무시)/이메일/메모/회사 통합 매칭 수행
            xml_query = """<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
                <d:prop><d:getetag /><c:address-data /></d:prop>
                <c:filter>
                    <c:prop-filter name="FN"/>
                </c:filter>
            </c:addressbook-query>"""

        response = sess.request(
            "REPORT",
            config.CARDDAV_URL,
            headers=headers,
            data=xml_query.encode("utf-8"),
            timeout=NETWORK_TIMEOUT,
        )

        if response.status_code not in [200, 207]:
            return False, f"서버 응답 오류: {response.status_code}"

        contacts = _parse_vcards(response.text)
        if not name_only:
            contacts = [
                c
                for c in contacts
                if _matches_contact(c, keyword, name_only=False)
            ]

        return True, contacts
    except requests.Timeout:
        logger.error("❌ CardDAV 서버 연결 시간 초과")
        return False, "NAS 서버 응답이 지연되고 있습니다."
    except Exception as e:
        logger.error(f"❌ CardDAV 검색 오류: {e}")
        return False, str(e)


def add_contact(
    name: str, phone: Optional[str], email: Optional[str]
) -> Tuple[bool, str]:
    """연락처 추가 (Session 재사용)"""
    if (
        not config.CARDDAV_URL
        or not config.CARDDAV_USERNAME
        or not config.CARDDAV_PASSWORD
    ):
        return False, "❌ CardDAV 연락처 서버 설정이 누락되었습니다."

    try:
        v = vobject.vCard()
        v.add("n").value = vobject.vcard.Name(family=name, given="")
        v.add("fn").value = name

        if phone:
            t = v.add("tel")
            t.value = phone
            t.type_param = "CELL"

        if email:
            e = v.add("email")
            e.value = email
            e.type_param = "WORK"

        filename = f"{uuid.uuid4()}.vcf"
        put_url = f"{config.CARDDAV_URL.rstrip('/')}/{filename}"

        sess = _get_session()
        response = sess.put(
            put_url,
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            data=v.serialize().encode("utf-8"),
            timeout=NETWORK_TIMEOUT,
        )

        if response.status_code in [201, 204, 200]:
            return True, "✅ 연락처가 저장되었습니다!"
        return False, f"❌ 서버 저장 실패: {response.status_code}"
    except requests.Timeout:
        return False, "서버 연결 시간 초과로 저장하지 못했습니다."
    except Exception as e:
        logger.error(f"❌ 연락처 추가 오류: {e}")
        return False, f"오류 발생: {str(e)}"
