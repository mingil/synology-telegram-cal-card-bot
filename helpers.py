# helpers.py
"""
CalDAV, CardDAV 등 외부 서비스 연동 관련 헬퍼 함수 모듈
"""
import asyncio
import calendar
import config
import logging
import html
import pytz
import re # <--- 이 줄 추가
import os

from datetime import datetime, date, time, timedelta
import logging
import uuid
from korean_lunar_calendar import KoreanLunarCalendar
from typing import List, Dict, Any, Tuple, Optional, Union # !!!!! Union 추가 !!!!!
import traceback # 상세 오류 로깅 위해 추가

import caldav
import vobject
from caldav.davclient import DAVClient
from caldav.lib.error import NotFoundError, DAVError, AuthorizationError, PutError # <--- PutError 추가
import requests # <--- requests 라이브러리 임포트 추가!
from requests.auth import HTTPBasicAuth # <--- 인증 위해 추가!
from icalendar import Calendar as iCalCalendar, Event as iCalEvent # <--- 추가

# 설정값은 함수 인자로 받거나, 필요시 config import (여기서는 인자로 받는 방식 위주)

logger = logging.getLogger(__name__)

# --- CalDAV 이벤트 조회 헬퍼 (VCALENDAR 처리 수정 버전) ---
# --- CalDAV 이벤트 조회 헬퍼 (VCALENDAR 처리 및 URL 포함 수정 버전) ---
def fetch_caldav_events(start_dt: datetime, end_dt: datetime, url: str, username: str, password: str) -> tuple[bool, Union[List[Dict[str, Any]], str]]:
    """
    주어진 기간과 정보로 CalDAV 이벤트를 가져와 상세 정보 딕셔너리 리스트 반환.
    결과 딕셔너리에 각 이벤트의 'url' 포함.
    """
    # 라이브러리 존재 여부 확인
    if not caldav or not vobject:
        return False, "CalDAV 관련 라이브러리(caldav, vobject)가 설치되지 않았습니다."

    logger.info(f"Fetching events from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
    if not url or not username or not password:
        return False, "CalDAV 접속 정보 누락"

    events_details = []
    try:
        with DAVClient(url=url, username=username, password=password) as client:
            principal = client.principal()
            calendars = principal.calendars()
            if not calendars:
                return False, "접속 가능한 캘린더 없음"

            for calendar_obj in calendars: # calendar 변수명 변경 (내장 모듈과 충돌 방지)
                logger.debug(f"Searching calendar: {getattr(calendar_obj, 'name', 'N/A')}")
                try:
                    events_raw = calendar_obj.search(start=start_dt, end=end_dt, event=True, expand=True)

                    for event_obj in events_raw: # event_obj는 DAVObject
                        # ======[ 이벤트 URL 가져오기 ]======
                        event_full_url = str(getattr(event_obj, 'url', None))
                        if not event_full_url:
                             logger.warning(f"Could not get URL for an event object in calendar '{getattr(calendar_obj, 'name', 'N/A')}'. Skipping.")
                             continue # URL 없으면 처리 불가
                        # ====================================

                        try:
                            vcal_generator = vobject.readComponents(event_obj.data)
                            component = next(vcal_generator)

                            vevents_to_process = []
                            if hasattr(component, 'name'):
                                comp_name_upper = component.name.upper()
                                if comp_name_upper == 'VEVENT':
                                    vevents_to_process.append(component)
                                elif comp_name_upper == 'VCALENDAR':
                                     # ... (VCALENDAR 내부 VEVENT 찾는 로직은 기존과 동일) ...
                                     if hasattr(component, 'components'):
                                          for sub_comp in component.components():
                                               if hasattr(sub_comp, 'name') and sub_comp.name.upper() == 'VEVENT':
                                                   vevents_to_process.append(sub_comp)
                                     elif hasattr(component, 'vevent_list'): # Fallback
                                         vevents_to_process.extend(component.vevent_list)
                            # ... (나머지 컴포넌트 타입 처리 로직) ...

                            if not vevents_to_process: continue

                            for vevent in vevents_to_process:
                                summary = getattr(vevent, 'summary', None)
                                summary = summary.value.strip() if summary else "제목 없음"

                                # ... (dtstart, dtend, is_allday 등 파싱 로직 유지) ...
                                dtstart_prop = getattr(vevent, 'dtstart', None)
                                dtend_prop = getattr(vevent, 'dtend', None)
                                dtstart_val = getattr(dtstart_prop, 'value', None) if dtstart_prop else None
                                dtend_val = getattr(dtend_prop, 'value', None) if dtend_prop else None
                                is_allday = False; start_str = "N/A"; end_str = ""
                                start_time_str = ""; end_time_str = ""
                                start_date_obj_for_sort = None

                                if dtstart_val:
                                    start_date_obj_for_sort = dtstart_val
                                    if isinstance(dtstart_val, datetime):
                                        is_allday = False
                                        start_date_str_part = dtstart_val.strftime('%Y-%m-%d')
                                        start_time_str = dtstart_val.strftime('%H:%M')
                                        start_str = f"{start_date_str_part} {start_time_str}"
                                    elif isinstance(dtstart_val, date):
                                        is_allday = True
                                        start_date_str_part = dtstart_val.strftime('%Y-%m-%d')
                                        start_str = start_date_str_part
                                    else: continue # 잘못된 타입이면 다음 vevent

                                    # 종료 시간/날짜 처리 (기존 로직 유지)
                                    if dtend_val:
                                        if isinstance(dtend_val, datetime):
                                             end_date_str_part = dtend_val.strftime('%Y-%m-%d')
                                             end_time_str = dtend_val.strftime('%H:%M')
                                             start_date_compare = dtstart_val.date() if isinstance(dtstart_val, datetime) else dtstart_val
                                             end_date_compare = dtend_val.date()
                                             if is_allday and dtend_val.time() == time.min: end_date_compare -= timedelta(days=1)
                                             if isinstance(start_date_compare, date) and end_date_compare == start_date_compare:
                                                  if not is_allday and start_time_str != end_time_str: end_str = f" ~ {end_time_str}"
                                             else:
                                                  if not is_allday: end_str = f" ~ {end_date_str_part} {end_time_str}"
                                                  else: end_str = f" ~ {end_date_compare.strftime('%Y-%m-%d')}"
                                        elif isinstance(dtend_val, date):
                                             actual_end_date = dtend_val - timedelta(days=1)
                                             start_date_compare = dtstart_val
                                             if isinstance(start_date_compare, date) and actual_end_date > start_date_compare: end_str = f" ~ {actual_end_date.strftime('%Y-%m-%d')}"
                                # ... (종료 처리 끝) ...

                                if start_str != "N/A":
                                    event_uid = getattr(vevent.uid, 'value', None) if hasattr(vevent, 'uid') else None
                                    event_key = f"{event_uid}_{start_str}" # 중복 체크용 키

                                    # 중복 체크 (url 비교는 불필요, uid와 start_str로 충분)
                                    is_duplicate = False
                                    if event_uid:
                                        for existing_event in events_details:
                                            if existing_event.get('_key') == event_key: # 임시 키 사용
                                                is_duplicate = True
                                                break

                                    if not is_duplicate:
                                        event_data_to_add = {
                                            "summary": summary,
                                            "start_str": start_str,
                                            "end_str": end_str,
                                            "start_time_str": start_time_str,
                                            "end_time_str": end_time_str,
                                            "is_allday": is_allday,
                                            "start_date_obj": start_date_obj_for_sort, # 정렬용
                                            "_key": event_key, # 중복 체크용
                                            "url": event_full_url # <<<--- 이벤트 URL 추가!
                                        }
                                        events_details.append(event_data_to_add)
                                    else:
                                         logger.debug(f"Skipping duplicate event instance: Key={event_key}")

                        except StopIteration: logger.warning(f"No component found in VCALENDAR data from: {event_full_url}")
                        except vobject.base.ParseError as parse_err: logger.error(f"VObject ParseError for {event_full_url}: {parse_err}", exc_info=False)
                        except Exception as outer_err: logger.error(f"Error processing VCALENDAR data from '{event_full_url}': {outer_err}", exc_info=True)

                except NotFoundError: logger.debug(f"No events found in calendar '{getattr(calendar_obj, 'name', 'N/A')}' for the given range.")
                except Exception as search_err: logger.error(f"Error searching calendar '{getattr(calendar_obj, 'name', 'N/A')}': {search_err}", exc_info=True)

        # 최종 결과를 시작 날짜/시간 순으로 정렬
        events_details.sort(key=lambda x: (
            x.get('start_date_obj').date() if isinstance(x.get('start_date_obj'), datetime) else x.get('start_date_obj', date.min),
            x.get('start_date_obj').time() if isinstance(x.get('start_date_obj'), datetime) else time.min
        ))

        # 정렬 후 불필요한 임시 키 제거 (url은 남김!)
        for event in events_details:
            event.pop('start_date_obj', None)
            event.pop('_key', None) # _uid 대신 _key 사용했으므로 _key 제거

        return True, events_details
    except (ConnectionRefusedError, caldav.lib.error.AuthorizationError, Exception, caldav.lib.error.DAVError) as dav_err:
         logger.error(f"CalDAV connection/auth/server error: {dav_err}", exc_info=True)
         error_msg = f"CalDAV 서버 오류 ({type(dav_err).__name__})"
         if isinstance(dav_err, ConnectionRefusedError): error_msg = "CalDAV 서버 연결 거부됨"
         elif isinstance(dav_err, (caldav.lib.error.AuthorizationError, Exception)): error_msg = "CalDAV 인증/권한 오류"
         return False, error_msg
    except Exception as conn_err:
        logger.error(f"CalDAV connection or processing error: {conn_err}", exc_info=True)
        return False, f"CalDAV 처리 중 오류 발생: {type(conn_err).__name__}"
# --- fetch_caldav_events 함수 끝 ---

# --- CardDAV 연락처 목록 조회 헬퍼 ---
def list_all_contacts(url, username, password):
    """지정된 CardDAV URL에서 모든 연락처 이름을 가져옵니다."""
    if not url or not username or not password: return False, "CardDAV 접속 정보 누락"
    all_contact_names = []
    try:
        with DAVClient(url=url, username=username, password=password) as client:
            logger.info(f"Attempting CardDAV access (list): {url}")
            addressbook = caldav.objects.Calendar(client=client, url=url)
            logger.info(f"Got CardDAV object. Name: {getattr(addressbook, 'name', 'N/A')}")

            contacts_to_fetch = []
            if hasattr(addressbook, 'objects_by_sync_token'): contacts_to_fetch = addressbook.objects_by_sync_token()
            elif hasattr(addressbook, 'contacts'): contacts_to_fetch = addressbook.contacts()
            else: return False, "주소록 객체에서 연락처 목록 가져오기 실패"

            logger.info(f"Found {len(contacts_to_fetch)} potential contacts. Parsing names...")
            parsed_count = 0
            for contact_dav in contacts_to_fetch:
                try:
                    contact_dav.load()
                    vcard = vobject.readOne(contact_dav.data)
                    name = getattr(vcard.fn, 'value', None)
                    if name: all_contact_names.append(name); parsed_count += 1
                except Exception as contact_err: logger.warning(f"Error processing contact {getattr(contact_dav, 'url', 'N/A')}: {contact_err}")

            logger.info(f"Parsed {parsed_count} names.")
            if not all_contact_names: return False, "연락처를 찾았지만 이름 정보 없음"
            unique_names = sorted(list(set(all_contact_names)))
            logger.info(f"Returning {len(unique_names)} unique names.")
            return True, unique_names
    except Exception as e:
        logger.exception(f"Error listing contacts: {e}")
        return False, f"연락처 목록 조회 중 오류: {e}"

# --- CardDAV 연락처 삭제 헬퍼 ---
# --- CardDAV 연락처 삭제 헬퍼 (수정: Principal 방식 + requests 사용) ---
def delete_carddav_contact(url: str, username: str, password: str, name_or_id_to_delete: str) -> tuple[bool, str]:
    """이름 또는 ID로 연락처를 찾아 삭제합니다 (Principal 방식 + requests)."""
    if not url or not username or not password: return False, "CardDAV 접속 정보 누락"
    if not name_or_id_to_delete: return False, "삭제할 이름/ID 필요"
    logger.warning(f"Attempting DELETE contact (principal + requests): {name_or_id_to_delete}")

    deleted = False
    contact_name_found = None
    target_url_to_delete = None

    try:
        # DAVClient는 Principal을 얻기 위해 기본 URL로 연결하는 것이 더 안정적일 수 있음
        with DAVClient(url=url, username=username, password=password) as client:
            # 1. ID(URL)로 대상 URL 확인
            if name_or_id_to_delete.startswith("http") or "/" in name_or_id_to_delete:
                 target_url_to_delete = name_or_id_to_delete
                 contact_name_found = name_or_id_to_delete
                 logger.debug(f"Target URL specified directly: {target_url_to_delete}")

            # 2. 이름으로 대상 URL 찾기
            if target_url_to_delete is None:
                logger.debug(f"Attempting to find contact URL by name using principal: {name_or_id_to_delete}")
                try:
                    principal = client.principal()
                    addressbooks = principal.addressbooks()
                    if not addressbooks:
                        logger.warning("No address books found via principal.")
                        # 여기서 False 반환 대신 아래 최종 결과에서 처리하도록 변경
                    else:
                        logger.info(f"Found {len(addressbooks)} address book(s). Searching...")
                        target_name_processed = name_or_id_to_delete.strip().lower()
                        found_in_any_book = False # 주소록 순회 중 찾았는지 여부

                        for addressbook in addressbooks:
                            logger.debug(f"Searching in address book: {addressbook.url}")
                            try:
                                contacts_to_fetch = []
                                if hasattr(addressbook, 'contacts'): contacts_to_fetch = addressbook.contacts()
                                elif hasattr(addressbook, 'objects_by_sync_token'): contacts_to_fetch = addressbook.objects_by_sync_token()

                                for contact_dav in contacts_to_fetch:
                                    try:
                                        contact_dav.load(); vcard = vobject.readOne(contact_dav.data)
                                        current_name = getattr(vcard.fn, 'value', None)
                                        if current_name:
                                            if current_name.strip().lower() == target_name_processed:
                                                contact_name_found = current_name
                                                target_url_to_delete = str(contact_dav.url)
                                                logger.info(f"Found matching contact by name: '{current_name}' (URL: {target_url_to_delete})")
                                                found_in_any_book = True # 찾았음 표시
                                                break # 내부 루프 종료
                                    except Exception as e: logger.warning(f"Error processing contact {contact_dav.url}: {e}")
                                if found_in_any_book: break # 주소록 순회 종료

                            except Exception as book_err:
                                logger.error(f"Error accessing contacts in address book {addressbook.url}: {book_err}")
                                continue # 다음 주소록으로

                except Exception as principal_err:
                     logger.error(f"Error getting address books from principal: {principal_err}", exc_info=True)
                     # 오류 발생 시 target_url_to_delete는 None 유지

        # 3. 찾은 URL로 실제 삭제 요청 (requests.delete 사용)
        if target_url_to_delete:
            logger.info(f"Sending DELETE request to: {target_url_to_delete}")
            try:
                response = requests.delete(
                    target_url_to_delete,
                    auth=HTTPBasicAuth(username, password),
                    verify=True
                )
                if 200 <= response.status_code < 300:
                    deleted = True
                    logger.info(f"Successfully deleted contact via requests. Status: {response.status_code}")
                else:
                    logger.error(f"Failed to delete via requests. Status: {response.status_code} {response.reason}")
                    # 실패 메시지는 아래 최종 결과에서 처리
            except requests.exceptions.RequestException as req_err:
                logger.error(f"CardDAV DELETE Request failed: {req_err}", exc_info=True)
                # 실패 메시지는 아래 최종 결과에서 처리
            except Exception as e:
                 logger.error(f"Unexpected error during DELETE request: {e}", exc_info=True)
                 # 실패 메시지는 아래 최종 결과에서 처리
        else:
            logger.warning(f"Contact URL to delete not found for '{name_or_id_to_delete}'")

        # 최종 결과 반환
        if deleted:
            return True, f"✅ 연락처 '{contact_name_found}' 삭제 완료."
        else:
            return False, f"🤷 삭제할 연락처 '{name_or_id_to_delete}'을(를) 찾을 수 없거나 삭제에 실패했습니다."

    # !!!!! 여기가 중요: 최상위 try 에 대한 except 블록들 !!!!!
    except ConnectionError as conn_err: # <--- line 227 근처 추정 (requests 예외 포함)
        logger.error(f"CardDAV Connection Error for deletion: {conn_err}", exc_info=True)
        return False, f"CardDAV 서버 연결 오류: {conn_err}"
    except Exception as e: # <--- 그 다음 다른 예외 처리 (try와 같은 레벨)
        logger.exception(f"Unexpected error in delete_carddav_contact: {e}")
        return False, f"연락처 삭제 중 예기치 않은 오류: {e}"
    # !!!!! 수정 끝 !!!!!
# --- delete_carddav_contact 함수 끝 ---

# --- CardDAV 연락처 상세 조회 헬퍼 (오류 수정 및 필드 추출 강화 버전) ---
def find_contact_details(url: str, username: str, password: str, name_to_find: str) -> tuple[bool, Union[List[Dict[str, Any]], str]]:
    """
    이름으로 연락처를 검색하여 상세 정보 딕셔너리 리스트 또는 상태 메시지 반환
    (vCard 처리 및 오류 수정 버전)
    """
    if not url or not username or not password: return False, "CardDAV 접속 정보 누락"
    if not name_to_find: return False, "검색할 이름 필요"

    found_contacts_details = []
    # !!!!! 수정된 로그 라인 !!!!!
    logger.info(f"--- Starting detailed search for '{name_to_find}'. URL: {url} ---")

    try:
        with DAVClient(url=url, username=username, password=password) as client:
            try:
                addressbook = caldav.objects.Calendar(client=client, url=url)
                logger.info(f"Accessed address book: {getattr(addressbook, 'name', 'N/A')}")
            except Exception as load_err:
                logger.exception(f"Failed to load address book object at {url}")
                return False, f"주소록({url}) 접근 실패: {load_err}"

            contacts_to_fetch = []
            try:
                if hasattr(addressbook, 'objects_by_sync_token'):
                    contacts_to_fetch = addressbook.objects_by_sync_token()
                    logger.debug(f"Fetched contacts using objects_by_sync_token. Count: {len(contacts_to_fetch)}")
                elif hasattr(addressbook, 'contacts'):
                    contacts_to_fetch = addressbook.contacts()
                    logger.debug(f"Fetched contacts using .contacts(). Count: {len(contacts_to_fetch)}")
                else:
                    logger.warning("Address book object has no method to fetch contacts.")
            except Exception as fetch_err:
                 logger.exception("Error fetching contact list from address book")
                 return False, f"주소록에서 연락처 목록 가져오기 실패: {fetch_err}"

            search_term_lower = name_to_find.lower()
            processed_count = 0
            found_count = 0
            logger.info(f"Processing {len(contacts_to_fetch)} potential contacts...")

            for i, contact_dav in enumerate(contacts_to_fetch):
                processed_count += 1
                logger.debug(f"  Processing contact {i+1}/{len(contacts_to_fetch)}: {contact_dav.url}")
                try:
                    contact_dav.load()
                    vcard = vobject.readOne(contact_dav.data)

                    contact_name = getattr(vcard.fn, 'value', '').strip()
                    if not contact_name:
                        logger.warning(f"  Skipping contact {contact_dav.url} due to missing FN property.")
                        continue

                    if search_term_lower in contact_name.lower():
                        logger.info(f"  ---> Found matching name: '{contact_name}'")
                        found_count += 1
                        details = {
                            "name": contact_name, "n_details": {}, "nickname": None,
                            "tel": [], "email": [], "adr": None, "org": [],
                            "title": None, "url": [], "note": None, "impp": [],
                            "birthday": None
                        }

                        # N (이름 구성요소) - 안전하게 처리
                        if hasattr(vcard, 'n'):
                            n_obj = vcard.n
                            n_value = getattr(n_obj, 'value', None)
                            if n_value and hasattr(n_value, 'family'): # NameValue 객체인지 간단히 확인
                                try:
                                    details["n_details"] = {
                                        "family": getattr(n_value, 'family', ''),
                                        "given": getattr(n_value, 'given', ''),
                                        "additional": getattr(n_value, 'additional', ''),
                                        "prefix": getattr(n_value, 'prefix', ''),
                                        "suffix": getattr(n_value, 'suffix', '')
                                    }
                                except AttributeError as name_attr_err:
                                     logger.warning(f"    Error accessing parts of N property for '{contact_name}': {name_attr_err}")
                            elif isinstance(n_value, str):
                                details["n_details"] = {"family": n_value}
                                logger.warning(f"    N property value is a string for '{contact_name}': {n_value}")
                            else:
                                logger.warning(f"    Could not parse N property structure for '{contact_name}'. Value: {n_value}")
                            logger.debug(f"    N details: {details['n_details']}")

                        # NICKNAME
                        if hasattr(vcard, 'nickname'):
                           details["nickname"] = getattr(vcard.nickname, 'value', '').strip()
                           logger.debug(f"    Nickname: {details['nickname']}")

                        # TEL
                        tel_list = []
                        if hasattr(vcard, 'tel_list'):
                            tel_list = vcard.tel_list
                        elif hasattr(vcard, 'tel'):
                            tel_list = [vcard.tel]
                        for tel in tel_list:
                            tel_value = getattr(tel, 'value', '').strip()
                            if tel_value: details["tel"].append(tel_value)
                        logger.debug(f"    TEL: {details['tel']}")

                        # EMAIL
                        email_list = []
                        if hasattr(vcard, 'email_list'):
                            email_list = vcard.email_list
                        elif hasattr(vcard, 'email'):
                             email_list = [vcard.email]
                        for email in email_list:
                            email_value = getattr(email, 'value', '').strip()
                            if email_value: details["email"].append(email_value)
                        logger.debug(f"    EMAIL: {details['email']}")

                        # ADR
                        if hasattr(vcard, 'adr'):
                            try:
                                adr_obj = vcard.adr
                                adr_value = getattr(adr_obj, 'value', None)
                                if adr_value:
                                    pobox = getattr(adr_value, 'box', '') or ''
                                    ext = getattr(adr_value, 'extended', '') or ''
                                    street = getattr(adr_value, 'street', '') or ''
                                    locality = getattr(adr_value, 'locality', '') or ''
                                    region = getattr(adr_value, 'region', '') or ''
                                    postalcode = getattr(adr_value, 'code', '') or ''
                                    country = getattr(adr_value, 'country', '') or ''
                                    address_parts = [p.strip() for p in [pobox, ext, street, locality, region, postalcode, country] if p and p.strip()]
                                    if address_parts:
                                        details["adr"] = " ".join(address_parts)
                                        logger.debug(f"    ADR: {details['adr']}")
                                else:
                                     logger.warning(f"    ADR property value is empty or invalid for '{contact_name}'.")
                            except Exception as adr_err:
                                logger.warning(f"    Error parsing ADR for '{contact_name}': {adr_err}")

                        # ORG
                        if hasattr(vcard, 'org'):
                            org_values = getattr(vcard.org, 'value', [])
                            parsed_orgs = []
                            if isinstance(org_values, list):
                                parsed_orgs = [str(org).strip() for org in org_values if str(org).strip()]
                            elif isinstance(org_values, str):
                                if org_values.strip(): parsed_orgs = [org_values.strip()]
                            details["org"] = parsed_orgs
                            logger.debug(f"    ORG: {details['org']}")

                        # TITLE
                        if hasattr(vcard, 'title'):
                            details["title"] = getattr(vcard.title, 'value', '').strip()
                            logger.debug(f"    TITLE: {details['title']}")

                        # URL
                        urls_found = []
                        for key, prop_list in vcard.contents.items():
                             is_url_prop = key.lower() == 'url' or (key.lower().startswith('x-') and 'url' in key.lower())
                             if is_url_prop:
                                for prop in prop_list:
                                    url_value = getattr(prop, 'value', '').strip()
                                    if url_value: urls_found.append(url_value)
                        if urls_found: details["url"] = list(set(urls_found))
                        logger.debug(f"    URL: {details['url']}")

                        # NOTE
                        if hasattr(vcard, 'note'):
                            details["note"] = getattr(vcard.note, 'value', '').strip()
                            logger.debug(f"    NOTE: {details['note'][:50]}...")

                        # IMPP
                        impp_list = []
                        if hasattr(vcard, 'impp_list'):
                            impp_list = vcard.impp_list
                        elif hasattr(vcard, 'impp'):
                            impp_list = [vcard.impp]
                        for impp in impp_list:
                             impp_value = getattr(impp, 'value', '').strip()
                             if impp_value: details["impp"].append(impp_value)
                        logger.debug(f"    IMPP: {details['impp']}")

                        # BDAY
                        if hasattr(vcard, 'bday'):
                            try:
                                bday_value = vcard.bday.value
                                if isinstance(bday_value, (date, datetime)):
                                    details["birthday"] = bday_value.strftime('%Y-%m-%d')
                                elif isinstance(bday_value, str):
                                    # 날짜 형식 문자열인지 확인 후 포맷 시도
                                    cleaned_bday = bday_value.replace('-', '').strip()
                                    if len(cleaned_bday) == 8 and cleaned_bday.isdigit():
                                        try:
                                            dt = datetime.strptime(cleaned_bday, '%Y%m%d')
                                            details["birthday"] = dt.strftime('%Y-%m-%d')
                                        except ValueError:
                                            details["birthday"] = bday_value # 파싱 실패 시 원본
                                    else:
                                         details["birthday"] = bday_value # 이상한 문자열이면 그대로
                                else:
                                    details["birthday"] = str(bday_value)
                                logger.debug(f"    BDAY: {details['birthday']}")
                            except Exception as bday_err:
                                logger.warning(f"    Error parsing BDAY for '{contact_name}': {bday_err}")

                        found_contacts_details.append(details)

                except vobject.base.ParseError as parse_err:
                     logger.warning(f"  vCard parsing error for {contact_dav.url}: {parse_err}")
                except Exception as contact_err:
                     logger.error(f"  Error processing contact {contact_dav.url}:", exc_info=True)

            logger.info(f"--- Detailed search finished. Processed {processed_count} contacts. Found {found_count} matching names. Appending {len(found_contacts_details)} detail sets. ---")

            if not found_contacts_details:
                return True, f"🤷 '{html.escape(name_to_find)}' 이름과 일치하는 연락처를 찾을 수 없습니다."
            else:
                return True, found_contacts_details

    except ConnectionError as conn_err:
        logger.exception("CardDAV Connection Error for find_contact_details")
        return False, f"CardDAV 서버 연결 오류: {conn_err}"
    except Exception as e:
        logger.exception(f"Unexpected error during find_contact_details for '{name_to_find}'")
        return False, f"연락처 검색 중 예기치 않은 오류: {e}"

# ... (파일의 나머지 부분은 그대로 유지) ...


# --- CardDAV 새 연락처 추가 헬퍼 (requests 직접 사용 버전) ---
def add_new_contact(url: str, username: str, password: str, name: str, phone: Optional[str] = None, email: Optional[str] = None) -> tuple[bool, str]:
    """주어진 정보로 새 연락처를 생성하여 CardDAV 서버에 추가합니다 (requests 사용)."""
    if not url or not username or not password: return False, "CardDAV 접속 정보 누락"
    if not name: return False, "연락처 이름 필수"
    logger.info(f"Attempting to add contact (using requests): Name='{name}'")

    # 1. vCard 객체 생성
    try:
        vcard = vobject.vCard()
        vcard.add('fn').value = name
        if phone: vcard.add('tel').value = phone; vcard.tel.type_param = 'CELL'
        if email: vcard.add('email').value = email; vcard.email.type_param = 'INTERNET'
        vcard.add('uid').value = str(uuid.uuid4())
        vcard_data = vcard.serialize()
        logger.debug(f"Generated vCard data snippet:\n{vcard_data[:200]}...")
    except Exception as vcard_err:
        logger.error(f"Error creating vCard object: {vcard_err}", exc_info=True)
        return False, "vCard 객체 생성 중 오류 발생"

    # 2. CardDAV 서버에 저장 (requests.put 사용)
    try:
        vcf_filename = f"{vcard.uid.value}.vcf"
        target_url = f"{url.rstrip('/')}/{vcf_filename}"
        logger.info(f"Attempting PUT request to: {target_url}")

        # requests.put() 사용하여 직접 요청 보내기
        response = requests.put(
            target_url,
            data=vcard_data.encode('utf-8'), # 요청 본문
            headers={'Content-Type': 'text/vcard; charset=utf-8', 'If-None-Match': '*'}, # 헤더 (덮어쓰기 방지 추가)
            auth=HTTPBasicAuth(username, password), # 기본 인증
            verify=True # SSL 검증 (필요시 False 또는 인증서 경로 지정)
        )

        # 응답 상태 코드 확인
        if response.status_code in [201, 204]: # 201 Created or 204 No Content
            logger.info(f"Successfully added contact '{name}' (UID: {vcard.uid.value}) via requests")
            return True, f"✅ 연락처 '{name}' 추가 성공!"
        else:
            logger.error(f"Failed to add contact via requests. Status: {response.status_code} {response.reason}")
            logger.error(f"Response body: {response.text}")
            return False, f"서버에 연락처 추가 실패 (오류 코드: {response.status_code})"

    except requests.exceptions.RequestException as req_err:
        logger.error(f"CardDAV PUT Request failed: {req_err}", exc_info=True)
        return False, f"CardDAV 서버 요청 실패: {req_err}"
    except Exception as e:
        logger.exception(f"Error adding contact via requests: {e}")
        return False, f"연락처 추가 중 예기치 않은 오류: {e}"
# --- add_new_contact 함수 끝 ---

# --- CardDAV 연락처 검색 헬퍼 (수정: URL 직접 사용 + 디버깅 로그 추가) ---
def search_carddav_contacts(url: str, username: str, password: str, keyword: str) -> tuple[bool, Union[List[Dict[str, str]], str]]:
    """
    키워드로 연락처를 검색하여 부분 일치하는 연락처 목록(이름과 ID/URL)을 반환합니다.
    (특정 주소록 URL 직접 사용) - 디버깅 로그 추가 버전
    """
    if not url or not username or not password: return False, "CardDAV 접속 정보 누락"
    if not keyword: return False, "검색 키워드 필요"
    # !!!!! 로그 추가 1 !!!!!
    logger.info(f"====== [SEARCH DEBUG] 함수 시작: 키워드='{keyword}', URL='{url}' ======")

    found_contacts = []
    keyword_lower = keyword.lower()

    try:
        # !!!!! 로그 추가 2 !!!!!
        logger.info("====== [SEARCH DEBUG] DAVClient 연결 시도...")
        with DAVClient(url=url, username=username, password=password) as client:
            # !!!!! 로그 추가 3 !!!!!
            logger.info("====== [SEARCH DEBUG] DAVClient 연결 성공. 주소록 객체 로드 시도...")
            try:
                addressbook = caldav.objects.Calendar(client=client, url=url)
                # !!!!! 로그 추가 4 !!!!!
                logger.info(f"====== [SEARCH DEBUG] 주소록 객체 로드 성공: {getattr(addressbook, 'name', 'N/A')}")
            except Exception as load_err:
                logger.exception("====== [SEARCH DEBUG] 주소록 객체 로드 실패!")
                return False, f"주소록({url}) 접근 실패: {load_err}"

            contacts_to_fetch = []
            try:
                # !!!!! 로그 추가 5 !!!!!
                logger.info("====== [SEARCH DEBUG] 주소록에서 연락처 목록 가져오기 시도...")
                if hasattr(addressbook, 'objects_by_sync_token'):
                    contacts_to_fetch = addressbook.objects_by_sync_token()
                    logger.info(f"====== [SEARCH DEBUG] objects_by_sync_token 사용: {len(contacts_to_fetch)}개 가져옴")
                elif hasattr(addressbook, 'contacts'):
                    contacts_to_fetch = addressbook.contacts()
                    logger.info(f"====== [SEARCH DEBUG] .contacts() 사용: {len(contacts_to_fetch)}개 가져옴")
                else:
                    logger.warning("====== [SEARCH DEBUG] 연락처 목록 가져오기 메서드 없음!")
            except Exception as fetch_err:
                logger.exception("====== [SEARCH DEBUG] 연락처 목록 가져오기 실패!")
                return False, f"주소록에서 연락처 목록 가져오기 실패: {fetch_err}"

            # !!!!! 로그 추가 6 !!!!!
            logger.info(f"====== [SEARCH DEBUG] 총 {len(contacts_to_fetch)}개 연락처 처리 시작...")
            processed_count = 0
            for i, contact_dav in enumerate(contacts_to_fetch):
                processed_count += 1
                logger.debug(f"====== [SEARCH DEBUG]   {i+1}번째 연락처 처리 중: {contact_dav.url}")
                try:
                    contact_dav.load()
                    vcard = vobject.readOne(contact_dav.data)
                    name = getattr(vcard.fn, 'value', '').strip()
                    emails = [getattr(e, 'value', '') for e in getattr(vcard, 'email_list', [])]
                    tels = [getattr(t, 'value', '') for t in getattr(vcard, 'tel_list', [])]

                    # (검색 로직은 그대로...)
                    match = False
                    if keyword_lower in name.lower(): match = True
                    if not match:
                        for e in emails:
                            if keyword_lower in e.lower(): match = True; break
                    if not match:
                        for t in tels:
                            if keyword_lower in t.replace('-', ''): match = True; break

                    if match:
                        contact_id = str(contact_dav.url)
                        logger.info(f"====== [SEARCH DEBUG]   ---> 검색 결과 찾음!: {name} ({contact_id})") # 매칭 시 INFO 레벨
                        if not any(c['id'] == contact_id for c in found_contacts):
                            found_contacts.append({'name': name, 'id': contact_id})

                except vobject.base.ParseError as parse_err:
                    logger.warning(f"====== [SEARCH DEBUG]   vCard 파싱 오류: {contact_dav.url} - {parse_err}")
                except Exception as e:
                     logger.exception(f"====== [SEARCH DEBUG]   개별 연락처 처리 오류: {contact_dav.url}") # 오류 시 스택 트레이스 포함

            # !!!!! 로그 추가 7 !!!!!
            logger.info(f"====== [SEARCH DEBUG] 연락처 처리 완료: 총 {processed_count}개 처리, {len(found_contacts)}개 찾음")

        # 최종 결과 반환
        if not found_contacts:
            # !!!!! 로그 추가 8 !!!!!
            logger.info(f"====== [SEARCH DEBUG] 검색 결과 없음 반환.")
            return True, f"🤷 키워드 '{html.escape(keyword)}' 와(과) 일치하는 연락처를 찾을 수 없습니다."
        else:
            # !!!!! 로그 추가 9 !!!!!
            logger.info(f"====== [SEARCH DEBUG] {len(found_contacts)}개 검색 결과 반환.")
            found_contacts.sort(key=lambda x: x['name'])
            return True, found_contacts

    except ConnectionError as conn_err:
        logger.exception("====== [SEARCH DEBUG] CardDAV 연결 오류 발생!")
        return False, f"CardDAV 서버 연결 오류: {conn_err}"
    except Exception as e:
        logger.exception("====== [SEARCH DEBUG] 예기치 않은 오류 발생!")
        return False, f"연락처 검색 중 예기치 않은 오류: {e}"
# --- search_carddav_contacts 함수 끝 ---

# --- 음력 날짜 추출 및 변환 헬퍼 (수정됨: 윤달 처리 추가) ---

def parse_lunar_date_from_summary(summary: str) -> Optional[Tuple[int, int, bool]]:
    """
    이벤트 제목에서 '(음력 [윤]X월 Y일)' 형태의 음력 날짜(윤달 포함)를 파싱합니다.
    반환값: (월, 일, 윤달여부(bool)) 또는 None
    """
    # 정규표현식 수정: '윤' 글자를 선택적으로 캡처 (group 1)
    # 예: (음력 4월 8일), (음력 윤4월 8일), (음 4/8), (음 윤4.8) 등 처리 시도
    pattern = r"\(음력?\s*(윤)?\s?(\d{1,2})[월/\.]\s?(\d{1,2})일?\)"
    match = re.search(pattern, summary)
    if match:
        try:
            is_leap = bool(match.group(1)) # '윤'이 있으면 True, 없으면 False
            month = int(match.group(2))
            day = int(match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31: # 간단한 유효성 검사
                logger.debug(f"Parsed lunar date from '{summary}': Month={month}, Day={day}, Leap={is_leap}")
                return month, day, is_leap
            else:
                logger.warning(f"Invalid month/day parsed from '{summary}': Month={month}, Day={day}")
        except (ValueError, IndexError):
            logger.warning(f"Error parsing lunar date groups from '{summary}'")
    # logger.debug(f"No lunar date pattern found in '{summary}'") # 패턴 못 찾을 때 로그 (선택적)
    return None

def get_solar_date_for_lunar(target_year: int, lunar_month: int, lunar_day: int, is_leap: bool) -> Optional[date]:
    """
    주어진 연도의 음력 날짜(윤달 포함)에 해당하는 양력 날짜를 반환합니다.
    (속성 이름 수정: solarYear, solarMonth, solarDay 사용)
    """
    try:
        calendar = KoreanLunarCalendar()
        calendar.setLunarDate(target_year, lunar_month, lunar_day, is_leap)
        # --- 속성 이름 수정 (카멜 케이스 사용) ---
        solar_date = date(calendar.solarYear, calendar.solarMonth, calendar.solarDay)
        # ---------------------------------------
        logger.debug(f"Converted Lunar {target_year}-{lunar_month}-{lunar_day} (Leap={is_leap}) to Solar {solar_date}")
        return solar_date
    except ValueError as e:
        # 해당 연도에 해당 음력/윤달 날짜가 없는 경우 발생 가능 (정상적인 경우일 수 있음)
        logger.warning(f"Could not convert lunar date {target_year}-{lunar_month}-{lunar_day} (Leap={is_leap}). Reason: {e}. This might be normal.")
    except AttributeError as ae:
        # 혹시 다른 속성 이름 오류가 있을 경우 대비
        logger.error(f"AttributeError during lunar conversion ({target_year}-{lunar_month}-{lunar_day}, Leap={is_leap}): {ae}. Library version might be incompatible?", exc_info=True)
    except Exception as e:
        logger.error(f"Error converting lunar to solar ({target_year}-{lunar_month}-{lunar_day}, Leap={is_leap}): {e}", exc_info=True)
    return None

# --- CalDAV 이벤트 키워드 검색 함수 (URL 포함 수정 버전) ---
def search_caldav_events_by_keyword(
    url: str,
    username: str,
    password: str,
    keyword: str,
    start_dt: datetime,
    end_dt: datetime
) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """
    주어진 기간 내에서 특정 키워드를 포함하는 CalDAV 이벤트를 검색합니다.
    결과 딕셔너리에 각 이벤트의 'url' 포함. (들여쓰기 수정됨)
    """
    try: import html
    except ImportError: return False, "Internal error: html module missing."

    found_events_details: List[Dict[str, Any]] = []
    keyword_lower = keyword.lower()
    logger.info(f"--- Starting CalDAV keyword search for '{keyword}' from {start_dt.date()} to {end_dt.date()} ---")

    if not caldav or not vobject: return False, "CalDAV 관련 라이브러리 미설치"
    if not url or not username or not password: return False, "CalDAV 접속 정보 누락"
    if not keyword: return False, "검색 키워드 필요"

    try:
        client = caldav.DAVClient(url=url, username=username, password=password)
        principal = client.principal()
        calendars = principal.calendars()
        logger.info(f"Found {len(calendars)} calendars for principal.")
        if not calendars: return False, "접근 가능한 캘린더 없음"

        total_processed_events = 0
        for calendar_obj in calendars:
            calendar_name = getattr(calendar_obj, 'name', 'N/A') # 로그용 이름 가져오기
            logger.debug(f"Searching calendar: {calendar_name}")
            try:
                # 서버 필터링 없이 모든 이벤트 인스턴스 가져오기
                results = calendar_obj.search(start=start_dt, end=end_dt, event=True, expand=True)
                logger.debug(f"Fetched {len(results)} potential event instances from '{calendar_name}' for client-side filtering.")

                for event_obj in results: # event_obj는 DAVObject
                    total_processed_events += 1
                    # ======[ 이벤트 URL 가져오기 ]======
                    event_full_url = str(getattr(event_obj, 'url', None))
                    if not event_full_url:
                        logger.warning(f"Could not get URL for an event object in calendar '{calendar_name}'. Skipping.")
                        continue
                    # ====================================
                    try:
                        # VCALENDAR/VEVENT 파싱
                        vcal_generator = vobject.readComponents(event_obj.data)
                        component = next(vcal_generator)
                        vevents_to_process = []
                        if hasattr(component, 'name'):
                            comp_name_upper = component.name.upper()
                            if comp_name_upper == 'VEVENT':
                                vevents_to_process.append(component)
                            elif comp_name_upper == 'VCALENDAR':
                                if hasattr(component, 'components'):
                                    for sub_comp in component.components():
                                        if hasattr(sub_comp, 'name') and sub_comp.name.upper() == 'VEVENT':
                                            vevents_to_process.append(sub_comp)
                                elif hasattr(component, 'vevent_list'): # Fallback
                                    vevents_to_process.extend(component.vevent_list)
                        else:
                            logger.warning(f"Keyword Search: Parsed component has no 'name' attribute: {event_full_url}")
                            continue

                        if not vevents_to_process: continue

                        # 파싱된 VEVENT 처리
                        for vevent in vevents_to_process:
                            summary = getattr(vevent, 'summary', None)
                            summary_text = summary.value.strip() if summary else ""

                            # 클라이언트 측 키워드 필터링
                            if keyword_lower not in summary_text.lower():
                                continue

                            # 날짜/시간 파싱 로직
                            dtstart_prop = getattr(vevent, 'dtstart', None)
                            dtend_prop = getattr(vevent, 'dtend', None)
                            dtstart_val = getattr(dtstart_prop, 'value', None) if dtstart_prop else None
                            dtend_val = getattr(dtend_prop, 'value', None) if dtend_prop else None

                            is_allday = False
                            start_str = "N/A"
                            start_date_str_part = ""
                            end_str = ""
                            start_time_str = ""
                            end_time_str = ""
                            start_date_obj_for_sort = None

                            if dtstart_val:
                                start_date_obj_for_sort = dtstart_val # 정렬용
                                if isinstance(dtstart_val, datetime):
                                    is_allday = False
                                    start_date_str_part = dtstart_val.strftime('%Y-%m-%d')
                                    start_time_str = dtstart_val.strftime('%H:%M')
                                    start_str = f"{start_date_str_part} {start_time_str}"
                                elif isinstance(dtstart_val, date):
                                    is_allday = True
                                    start_date_str_part = dtstart_val.strftime('%Y-%m-%d')
                                    start_str = start_date_str_part
                                else:
                                    logger.warning(f"Keyword Search: Unexpected dtstart_val type: {type(dtstart_val)} for event '{summary_text}'")
                                    continue # 다음 VEVENT 처리

                                # 종료 시간/날짜 처리
                                if dtend_val:
                                    if isinstance(dtend_val, datetime):
                                        end_date_str_part = dtend_val.strftime('%Y-%m-%d')
                                        end_time_str = dtend_val.strftime('%H:%M')
                                        start_date_compare = dtstart_val.date() if isinstance(dtstart_val, datetime) else dtstart_val
                                        end_date_compare = dtend_val.date()
                                        if is_allday and dtend_val.time() == time.min:
                                            end_date_compare -= timedelta(days=1)
                                        if isinstance(start_date_compare, date) and end_date_compare == start_date_compare:
                                            if not is_allday and start_time_str != end_time_str:
                                                end_str = f" ~ {end_time_str}"
                                        else:
                                            if not is_allday:
                                                end_str = f" ~ {end_date_str_part} {end_time_str}"
                                            else:
                                                end_str = f" ~ {end_date_compare.strftime('%Y-%m-%d')}"
                                    # ======[ 수정된 부분: elif 및 그 안의 if 들여쓰기 확인 ]======
                                    elif isinstance(dtend_val, date):
                                        actual_end_date = dtend_val - timedelta(days=1)
                                        start_date_compare = dtstart_val # 이미 date 또는 datetime
                                        # 아래 if 문의 들여쓰기가 elif 블록 내부에 있도록 수정
                                        if isinstance(start_date_compare, date) and actual_end_date > start_date_compare:
                                            end_str = f" ~ {actual_end_date.strftime('%Y-%m-%d')}"
                                    # ========================================================
                                    else:
                                        logger.warning(f"Keyword Search: Unexpected dtend_val type ({type(dtend_val)}) for event '{summary_text}'")

                            # 유효한 이벤트 데이터인지 확인 후 리스트에 추가
                            if start_str != "N/A":
                                event_uid = getattr(vevent.uid, 'value', None) if hasattr(vevent, 'uid') else None
                                event_key = f"{event_uid}_{start_str}" # 중복 체크용 키
                                is_duplicate = False
                                # 중복 체크
                                if event_uid:
                                    for existing_event in found_events_details:
                                        if existing_event.get('_key') == event_key:
                                            is_duplicate = True
                                            break

                                if not is_duplicate:
                                    event_details = {
                                        'summary': summary_text, 'start_str': start_str, 'end_str': end_str,
                                        'start_time_str': start_time_str, 'end_time_str': end_time_str,
                                        'is_allday': is_allday, 'start_date_obj': start_date_obj_for_sort, # 정렬용
                                        '_key': event_key, # 중복 체크용
                                        'url': event_full_url # <<<--- 이벤트 URL 포함
                                    }
                                    found_events_details.append(event_details)
                                    logger.debug(f"Keyword Search: Added event '{summary_text}' starting at {start_str}")

                    # VObject 파싱 또는 처리 중 예외
                    except StopIteration: logger.warning(f"Keyword Search: No component found from: {event_full_url}")
                    except vobject.base.ParseError as parse_err: logger.error(f"Keyword Search: VObject ParseError for {event_full_url}: {parse_err}", exc_info=False)
                    except Exception as inner_err: logger.error(f"Keyword Search: Error processing event instance {event_full_url}: {inner_err}", exc_info=True)

            # 캘린더 검색 중 예외
            except NotFoundError: logger.debug(f"No events found in calendar '{calendar_name}' (before keyword filtering).")
            except Exception as search_err: logger.error(f"Error searching calendar '{calendar_name}' (before keyword filtering): {search_err}", exc_info=True)

        logger.info(f"Keyword Search: Processed {total_processed_events} total instances. Found {len(found_events_details)} events matching '{keyword}'.")

        # 최종 결과 정렬
        found_events_details.sort(key=lambda x: (
            x.get('start_date_obj').date() if isinstance(x.get('start_date_obj'), datetime) else x.get('start_date_obj', date.min),
            x.get('start_date_obj').time() if isinstance(x.get('start_date_obj'), datetime) else time.min
        ))

        # 불필요한 임시 키 제거 (url은 남김!)
        for event in found_events_details:
            event.pop('start_date_obj', None)
            event.pop('_key', None)

        # 결과 반환
        if not found_events_details:
            return True, f"'{html.escape(keyword)}' 키워드를 포함하는 일정을 {start_dt.strftime('%Y-%m-%d')}부터 {end_dt.strftime('%Y-%m-%d')}까지 찾을 수 없습니다."
        else:
            return True, found_events_details

    # CalDAV 연결/인증/서버 오류 처리
    except (ConnectionRefusedError, AuthorizationError, AuthenticationError, DAVError) as dav_err:
        logger.error(f"Keyword Search: CalDAV connection/auth/server error: {dav_err}", exc_info=True)
        error_msg = f"CalDAV 서버 오류 ({type(dav_err).__name__})"
        if isinstance(dav_err, ConnectionRefusedError): error_msg = "CalDAV 서버 연결 거부됨"
        elif isinstance(dav_err, (AuthorizationError, AuthenticationError)): error_msg = "CalDAV 인증/권한 오류"
        return False, error_msg
    # 기타 예외 처리
    except Exception as e:
        logger.error(f"Keyword Search: CalDAV keyword search failed: {e}", exc_info=True)
        return False, f"캘린더 키워드 검색 중 오류가 발생했습니다: {type(e).__name__}"
# --- search_caldav_events_by_keyword 함수 끝 ---

# helpers.py - add_caldav_event 함수 전체 (icalendar 라이브러리 사용 버전)

# helpers.py - add_caldav_event 함수 전체 (최소 정보 버전)

# helpers.py 파일 내 (다른 import 구문은 그대로 유지)
import uuid
from datetime import datetime, date, time, timedelta # timedelta 추가
from typing import Dict, Any, Tuple, Optional, Union
import traceback
import html
import pytz # 시간대 처리를 위해 pytz 추가

import caldav
from caldav.davclient import DAVClient
from caldav.lib.error import NotFoundError, DAVError, AuthorizationError, PutError
try:
    from icalendar import Calendar as iCalCalendar, Event as iCalEvent, vCalAddress, vText
except ImportError:
    iCalCalendar, iCalEvent, vCalAddress, vText = None, None, None, None # 임포트 실패 시 None 할당

logger = logging.getLogger(__name__)


# --- CalDAV 새 이벤트 추가 헬퍼 (수정됨: add_event 사용) ---
def add_caldav_event(
    url: str,          # 기본 CalDAV 접속 URL
    username: str,     # CalDAV 사용자 이름
    password: str,     # CalDAV 비밀번호
    calendar_url: str, # 이벤트를 추가할 특정 캘린더의 URL
    event_details: Dict[str, Any]
) -> Tuple[bool, str]:
    """주어진 정보로 새 이벤트를 생성하여 CalDAV 서버에 추가합니다 (add_event 메서드 사용)."""

    # --- 라이브러리 및 입력값 확인 ---
    if not caldav or not iCalCalendar: return False, "오류: 필수 라이브러리 미설치"
    if not url or not username or not password: return False, "오류: CalDAV 접속 정보 누락"
    if not calendar_url: return False, "오류: 대상 캘린더 정보 누락"
    if not event_details.get('summary'): return False, "오류: 이벤트 제목(summary) 필수"
    if not event_details.get('dtstart'): return False, "오류: 이벤트 시작 시간(dtstart) 필수"

    summary = event_details['summary']
    dtstart = event_details['dtstart']
    dtend = event_details.get('dtend')
    is_allday = isinstance(dtstart, date) and not isinstance(dtstart, datetime)

    logger.info(f"[add_event Test] Attempting to add event to calendar: {calendar_url}")
    logger.info(f"[add_event Test] Event details: {event_details}")

    try:
        # 1. iCalendar 이벤트 객체 생성 (이전과 동일)
        event = iCalEvent()
        event.add('summary', summary)

        if is_allday: event.add('dtstart', dtstart)
        elif isinstance(dtstart, datetime):
            if dtstart.tzinfo is None: dtstart_aware = pytz.utc.localize(dtstart)
            else: dtstart_aware = dtstart.astimezone(pytz.utc)
            event.add('dtstart', dtstart_aware)
        else: return False, "오류: 잘못된 시작 시간 형식"

        if is_allday:
            dtend_for_ical = dtstart + timedelta(days=1)
            if isinstance(dtend, date) and dtend > dtstart: dtend_for_ical = dtend + timedelta(days=1)
            event.add('dtend', dtend_for_ical)
        elif isinstance(dtend, datetime):
             if dtend.tzinfo is None: dtend_aware = pytz.utc.localize(dtend)
             else: dtend_aware = dtend.astimezone(pytz.utc)
             if dtstart_aware and dtend_aware > dtstart_aware: event.add('dtend', dtend_aware)
             else: logger.warning(f"End time <= start time. Skipping DTEND.")

        event.add('uid', str(uuid.uuid4()))
        event.add('dtstamp', datetime.now(tz=pytz.utc))

        cal = iCalCalendar()
        cal.add('prodid', '-//My Telegram Bot v1.2//EN')
        cal.add('version', '2.0')
        cal.add_component(event)

        # icalendar 객체를 문자열로 변환
        ical_string_data = cal.to_ical().decode('utf-8')
        logger.debug(f"[add_event Test] Generated iCalendar string data:\n{ical_string_data}")

        # 3. CalDAV 서버에 저장 (add_event 사용)
        logger.debug(f"Connecting to CalDAV server: {url}")
        with DAVClient(url=url, username=username, password=password) as client:
            logger.debug("DAVClient connection successful. Getting calendar object...")
            try:
                target_calendar = caldav.objects.Calendar(client=client, url=calendar_url)
                calendar_name_for_log = getattr(target_calendar, 'name', '[Name unavailable]')
                logger.debug(f"Target calendar object obtained: Name='{calendar_name_for_log}', URL='{target_calendar.url}'")

                # ======[ add_event 메서드 사용 ]======
                logger.info(f"[add_event Test] Attempting to add event using add_event to calendar: {calendar_name_for_log}")
                # add_event 메서드는 iCalendar 문자열을 인자로 받음
                new_event_obj = target_calendar.add_event(ical=ical_string_data)
                # add_event는 일반적으로 바로 저장되므로 별도 save() 호출 불필요 (라이브러리 확인 필요)
                # new_event_obj.save() # <--- 보통 필요 없음
                # =====================================

                # add_event 성공 시 객체 또는 URL 반환 여부는 라이브러리 버전에 따라 다를 수 있음
                # 여기서는 성공 여부만 판단
                logger.info(f"[add_event Test] Successfully added event!")
                return True, f"✅ 일정 '{html.escape(summary)}' 추가 완료!"

            # (오류 처리 로직은 이전과 거의 동일)
            except (NotFoundError, DAVError, PutError, AuthorizationError, ConnectionError) as direct_save_err:
                 logger.error(f"[add_event Test] Error during add_event: {direct_save_err}", exc_info=True)
                 if isinstance(direct_save_err, NotFoundError): return False, "오류: 지정된 캘린더를 찾을 수 없습니다."
                 elif isinstance(direct_save_err, AuthorizationError): return False, "오류: CalDAV 인증 실패 (자격 증명 확인)"
                 elif isinstance(direct_save_err, PutError): # add_event도 내부적으로 PUT 사용 시 발생 가능
                      reason = getattr(direct_save_err, 'reason', '') or getattr(direct_save_err, 'body', '')
                      status_code = getattr(direct_save_err, 'status', 'N/A')
                      logger.error(f"Server response (PutError/add_event {status_code}): {reason[:1000]}")
                      php_error_match = re.search(r"Exception \[0\] (.*?) At line (\d+) of (.*?php)", reason)
                      if php_error_match:
                           error_msg = php_error_match.group(1); error_line = php_error_match.group(2); error_file = os.path.basename(php_error_match.group(3))
                           error_detail = f"서버 내부 오류 ({error_file} L{error_line}: {error_msg})"
                           return False, f"❌ CalDAV 서버 저장 실패 ({status_code} Error). {error_detail}"
                      else: return False, f"❌ CalDAV 서버 저장 실패 ({status_code} Error). 서버 응답 확인 필요."
                 elif isinstance(direct_save_err, ConnectionError): return False, "오류: CalDAV 서버 연결 실패"
                 else: return False, f"오류: CalDAV 서버 오류 ({type(direct_save_err).__name__})"
            except Exception as unexpected_err:
                 logger.exception(f"[add_event Test] Unexpected error during add_event: {unexpected_err}")
                 return False, f"오류: 예기치 않은 문제 발생 ({type(unexpected_err).__name__})"

    except Exception as e:
        logger.exception(f"Unexpected error in add_caldav_event function scope (add_event Test): {e}")
        return False, f"오류: 일정 추가 중 최상위 예외 발생 ({type(e).__name__})"

# --- add_caldav_event 함수 끝 ---

# --- 사용 가능한 CalDAV 캘린더 목록 조회 헬퍼 ---
def get_calendars(url: str, username: str, password: str) -> Tuple[bool, Union[List[Dict[str, str]], str]]:
    """사용자가 접근 가능한 CalDAV 캘린더 목록 (이름, URL)을 반환합니다."""
    if not url or not username or not password:
        return False, "CalDAV 접속 정보 누락"

    calendars_info = []
    logger.info("Attempting to get list of calendars...")
    try:
        with DAVClient(url=url, username=username, password=password) as client:
            principal = client.principal()
            calendars = principal.calendars()
            if calendars:
                for calendar in calendars:
                    try:
                        # 캘린더 이름과 URL 추출
                        cal_name = calendar.name if hasattr(calendar, 'name') else "이름 없는 캘린더"
                        cal_url = str(calendar.url)
                        calendars_info.append({'name': cal_name, 'url': cal_url})
                        logger.debug(f"Found calendar: Name='{cal_name}', URL='{cal_url}'")
                    except Exception as cal_err:
                         logger.warning(f"Error processing a calendar object: {cal_err}")
                logger.info(f"Successfully retrieved {len(calendars_info)} calendars.")
                return True, calendars_info
            else:
                logger.warning("No calendars found for the principal.")
                return True, [] # 성공했지만 빈 리스트 반환

    except (caldav.lib.error.AuthorizationError, caldav.lib.error.DAVError) as dav_err:
         logger.error(f"CalDAV error getting calendars: {dav_err}", exc_info=True)
         return False, f"오류: CalDAV 서버 오류 ({type(dav_err).__name__})"
    except ConnectionError as conn_err:
        logger.error(f"CalDAV connection error getting calendars: {conn_err}", exc_info=True)
        return False, "오류: CalDAV 서버 연결 실패"
    except Exception as e:
        logger.exception(f"Unexpected error getting calendars: {e}")
        return False, f"오류: 캘린더 목록 조회 중 예기치 않은 문제 발생 ({type(e).__name__})"
# --- get_calendars 함수 끝 ---

# ======[ 수정 후: get_command_list_message 함수 (최신 명령어 목록 반영) ]======
# ======[ 수정 후: get_command_list_message 함수 (클릭 가능한 명령어 형태로 수정) ]======
def get_command_list_message(user_id: int) -> str:
    """사용자 ID를 기반으로 보여줄 명령어 목록 문자열(HTML 형식)을 생성합니다."""
    is_admin = str(user_id) == str(config.ADMIN_CHAT_ID)
    logger.debug(f"Generating command list for user {user_id} (Is admin: {is_admin})")

    # --- 기본 명령어 목록 ---
    message = "<b>✨ 사용 가능한 명령어 ✨</b>\n\n"

    message += "<b>📅 캘린더 & 일정 관리</b>\n"
    message += "  /today - 🗓️ 오늘 일정 보기\n"  # <code> 제거
    message += "  /week - 📅 이번 주 일정 보기\n"   # <code> 제거
    message += "  /month - 📆 이번 달 일정 보기\n"  # <code> 제거
    message += "  /date - 🗓️ 특정 날짜 일정 보기 (대화형)\n" # <code> 제거
    message += "  /search_events - 🔎 키워드로 일정 검색 (대화형)\n" # <code> 제거
    message += "  /addevent - ➕ 새 일정 추가 (대화형)\n" # <code> 제거
    message += "\n" # 섹션 구분

    message += "<b>👤 주소록 & 연락처</b>\n"
    message += "  /findcontact - 🧑‍🤝‍🧑 이름으로 연락처 검색 (대화형)\n" # <code> 제거
    message += "  /searchcontact - 🔍 키워드로 연락처 검색 (대화형)\n" # <code> 제거
    message += "  /addcontact - ➕ 새 연락처 추가 (대화형)\n" # <code> 제거
    message += "\n" # 섹션 구분

    message += "<b>🤖 AI 비서 & 기타 기능</b>\n"
    message += "  /ask - 💡 AI에게 질문하기 (대화형)\n" # <code> 제거
    message += "  /start 또는 /help - ℹ️ 이 도움말/시작 메뉴 보기\n" # <code> 제거
    message += "  /cancel - 🚫 진행 중인 작업 취소\n" # <code> 제거

    # --- 관리자 전용 명령어 ---
    if is_admin:
        message += "\n\n" # 관리자 섹션 구분
        message += "<b>👑 관리자 전용 명령어 👑</b>\n"
        message += "  /deleteevent - 🗑️ 일정 삭제 (대화형)\n"        # <code> 제거
        message += "  /deletecontact - 🗑️ 연락처 삭제 (대화형)\n"   # <code> 제거
        message += "  /banlist - 🚫 차단된 사용자 목록 보기\n"      # <code> 제거
        message += "  /unban - ✅ 사용자 차단 해제 (대화형)\n"      # <code> 제거
        message += "  /permitlist - ✅ 허용된 사용자 목록 보기\n"    # <code> 제거

    return message
# --- get_command_list_message 함수 끝 ---

# ======[ CalDAV 이벤트 삭제 함수 추가 ]======
# ======[ 수정 후: delete_caldav_event 함수 (object_by_url 대신 다른 방식 사용) ]======
def delete_caldav_event(
    url: str,                      # 기본 CalDAV 접속 URL
    username: str,                 # CalDAV 사용자 이름
    password: str,                 # CalDAV 비밀번호
    event_url_or_uid: str,         # 삭제할 이벤트의 URL 또는 UID
    calendar_url: Optional[str] = None # UID로 삭제 시 대상 캘린더 URL (선택 사항)
) -> Tuple[bool, str]:
    """
    주어진 URL 또는 UID로 CalDAV 이벤트를 삭제합니다.
    (object_by_url 대신 calendar.event_by_url 또는 event_by_uid 사용)
    """
    logger.warning(f"Attempting to delete CalDAV event: {event_url_or_uid}")
    if not url or not username or not password: return False, "오류: CalDAV 접속 정보 누락"
    if not event_url_or_uid: return False, "오류: 삭제할 이벤트 URL 또는 UID 필요"

    event_to_delete = None

    try:
        with DAVClient(url=url, username=username, password=password) as client:
            principal = client.principal() # Principal 객체는 필요할 수 있음

            # 1. event_url_or_uid가 전체 URL인지 확인
            is_full_url = event_url_or_uid.startswith("http")

            if is_full_url:
                target_event_url = event_url_or_uid
                logger.info(f"Attempting to find event by full URL: {target_event_url}")
                # URL에서 캘린더 URL 부분을 추정하거나, 모든 캘린더를 확인해야 할 수 있음
                # 가장 간단한 방법은 모든 캘린더를 순회하며 해당 URL을 가진 이벤트를 찾는 것
                all_calendars = principal.calendars()
                if not all_calendars: return False, "삭제할 캘린더를 찾을 수 없음 (URL 방식)"

                found_in_calendar = None
                for cal in all_calendars:
                    try:
                        # calendar.event_by_url 메서드 사용 시도
                        event_found = cal.event_by_url(target_event_url)
                        if event_found:
                            event_to_delete = event_found
                            found_in_calendar = cal
                            logger.info(f"Found event by URL in calendar '{getattr(cal, 'name', cal.url)}'")
                            break # 찾았으면 종료
                    except NotFoundError:
                        continue # 해당 캘린더에 없음
                    except Exception as e:
                         logger.warning(f"Error searching URL '{target_event_url}' in calendar '{getattr(cal, 'name', cal.url)}': {e}")
                         # 오류 발생 시 다음 캘린더로 계속 진행할 수 있음

                if not event_to_delete:
                     logger.warning(f"Event not found by full URL '{target_event_url}' in any calendar.")
                     # 추가: URL 경로에서 캘린더 URL과 이벤트 파일명을 분리하여 찾는 시도 (더 복잡)
                     # try:
                     #     from urllib.parse import urlparse
                     #     parsed_url = urlparse(target_event_url)
                     #     path_parts = parsed_url.path.strip('/').split('/')
                     #     if len(path_parts) >= 2:
                     #         event_filename = path_parts[-1]
                     #         potential_calendar_path = "/" + "/".join(path_parts[:-1]) + "/"
                     #         potential_calendar_url = f"{parsed_url.scheme}://{parsed_url.netloc}{potential_calendar_path}"
                     #         logger.info(f"Attempting alternative find: Calendar URL='{potential_calendar_url}', Event Filename='{event_filename}'")
                     #         try:
                     #             calendar_obj = caldav.objects.Calendar(client=client, url=potential_calendar_url)
                     #             # event_by_url 이 파일명만으로도 작동하는지 확인 필요 (라이브러리 의존적)
                     #             # event_to_delete = calendar_obj.event_by_url(event_filename)
                     #             # 또는 calendar 내에서 직접 객체를 찾아야 할 수도 있음
                     #             # for ev in calendar_obj.events(): if ev.url.endswith(event_filename): event_to_delete = ev; break
                     #         except Exception as alt_e:
                     #              logger.error(f"Alternative find failed: {alt_e}")
                     # except Exception as url_parse_err:
                     #      logger.error(f"Failed to parse event URL for alternative find: {url_parse_err}")


            # 2. URL이 아니라면 UID로 간주하고 검색
            else:
                event_uid_to_find = event_url_or_uid
                logger.info(f"Attempting to find event by UID '{event_uid_to_find}'...")
                target_calendars = []
                if calendar_url: # 특정 캘린더 지정 시
                    try: target_calendars.append(caldav.objects.Calendar(client=client, url=calendar_url))
                    except Exception as e: logger.error(f"Error getting specified calendar '{calendar_url}': {e}")
                else: # 모든 캘린더 검색
                    try: target_calendars = principal.calendars()
                    except Exception as e: logger.error(f"Error getting calendars from principal: {e}")

                if not target_calendars: return False, "검색할 캘린더를 찾을 수 없음 (UID 방식)"

                for cal in target_calendars:
                    logger.debug(f"Searching UID '{event_uid_to_find}' in calendar: {getattr(cal, 'name', cal.url)}")
                    try:
                        event_found = cal.event_by_uid(event_uid_to_find)
                        if event_found:
                            event_to_delete = event_found
                            logger.info(f"Found event by UID in calendar '{getattr(cal, 'name', cal.url)}'. URL: {event_to_delete.url}")
                            break
                    except NotFoundError: continue
                    except Exception as e: logger.error(f"Error searching UID in calendar '{getattr(cal, 'name', cal.url)}': {e}"); continue

                if not event_to_delete:
                    logger.warning(f"Event with UID '{event_uid_to_find}' not found in specified calendars.")

            # 3. 찾은 이벤트 객체 삭제 시도
            if event_to_delete:
                try:
                    event_summary = "N/A"
                    try: event_summary = getattr(event_to_delete.vobject_instance.vevent.summary, 'value', 'N/A')
                    except Exception: pass

                    logger.warning(f"Deleting event: URL='{event_to_delete.url}', Summary='{event_summary}'")
                    event_to_delete.delete() # <--- Event 객체의 delete() 메서드 사용
                    logger.info(f"Successfully deleted event: {event_to_delete.url}")
                    return True, f"✅ 일정 '{html.escape(event_summary)}' 삭제 완료."
                except Exception as delete_err:
                    logger.error(f"Failed to delete event '{event_to_delete.url}': {delete_err}", exc_info=True)
                    return False, f"❌ 일정 삭제 실패: {delete_err}"
            else:
                # 이벤트 못 찾음
                return False, f"🤷 삭제할 일정 (URL/UID: {event_url_or_uid})을 찾을 수 없습니다."

    # CalDAV 연결/인증/서버 오류 처리
    except (AuthorizationError, ConnectionError, DAVError) as conn_err:
        logger.error(f"CalDAV connection or authentication error during delete: {conn_err}")
        error_msg = f"CalDAV 서버 오류 ({type(conn_err).__name__})"
        if isinstance(conn_err, (AuthorizationError, AuthenticationError)): error_msg = "CalDAV 인증/권한 오류"
        elif isinstance(conn_err, ConnectionError): error_msg = "CalDAV 서버 연결 오류"
        return False, error_msg
    # 기타 예외 처리
    except Exception as e:
        logger.exception(f"Unexpected error in delete_caldav_event for '{event_url_or_uid}'")
        return False, f"예기치 않은 오류 발생: {e}"
# ====================================================================================

# helpers.py 맨 마지막에 있는 check_upcoming_lunar_events 함수 전체 교체

def check_upcoming_lunar_events(days_offset: int) -> List[str]:
    """
    오늘로부터 days_offset일 뒤의 날짜가 음력으로 며칠인지 계산하고,
    캘린더의 해당 '음력 날짜(양력 가상 날짜)'에 '음력' 키워드가 포함된 일정이 있는지 확인합니다.
    """
    messages = []
    
    # 1. 확인 대상 날짜 (미래의 양력 날짜)
    target_date_solar = datetime.now() + timedelta(days=days_offset)
    
    # 2. 양력 -> 음력 변환
    k_calendar = KoreanLunarCalendar()
    k_calendar.setSolarDate(target_date_solar.year, target_date_solar.month, target_date_solar.day)
    
    lunar_month = k_calendar.lunarMonth
    lunar_day = k_calendar.lunarDay
    is_leap = k_calendar.isIntercalation

    logger.info(f"[Lunar Check] {days_offset}일 뒤({target_date_solar.strftime('%Y-%m-%d')})는 음력 {lunar_month}월 {lunar_day}일(윤달:{is_leap}) 입니다.")
    
    # 3. 캘린더 검색
    try:
        current_year = datetime.now().year
        # 검색할 날짜: 올해의 [음력 월] [음력 일] (예: 음력 10월 30일을 찾기 위해 양력 10월 30일을 검색)
        try:
            search_start = datetime(current_year, lunar_month, lunar_day, 0, 0, 0)
        except ValueError:
            # 윤년 등으로 날짜가 없는 경우 (예: 2월 30일 등)
            logger.warning(f"[Lunar Check] {current_year}년 {lunar_month}월 {lunar_day}일은 존재하지 않아 건너뜁니다.")
            return []

        search_end = search_start + timedelta(days=1)
        
        # [중요 수정] 반환값은 (성공여부, 리스트) 튜플입니다. 이를 분리(Unpacking)해야 합니다.
        success, events = fetch_caldav_events(
            search_start, 
            search_end, 
            config.CALDAV_URL, 
            config.CALDAV_USERNAME, 
            config.CALDAV_PASSWORD
        )

        # 성공했고, events가 리스트일 때만 실행
        if success and isinstance(events, list):
            logger.info(f"[Lunar Check] 검색 날짜: {search_start.strftime('%Y-%m-%d')} / 조회된 일정 수: {len(events)}")
            for event in events:
                title = event.get('summary', '')
                # 키워드 체크: 제목에 '음력' 또는 'Lunar'가 있어야 함
                if '음력' in title or 'Lunar' in title:
                    d_day_str = "오늘"
                    if days_offset == 1: d_day_str = "내일"
                    elif days_offset > 1: d_day_str = f"{days_offset}일 뒤"

                    msg = (
                        f"🔔 <b>[음력 기념일 알림]</b>\n"
                        f"{d_day_str} ({target_date_solar.strftime('%m월 %d일')})은\n"
                        f"<b>{html.escape(title)}</b> 입니다! 🎉\n"
                        f"(음력 {lunar_month}월 {lunar_day}일)"
                    )
                    messages.append(msg)
                    logger.info(f"[Lunar Check] 알림 생성 성공: {title}")
        else:
            logger.warning(f"[Lunar Check] 캘린더 조회 실패 또는 일정 없음: {events}")

    except Exception as e:
        logger.error(f"음력 일정 확인 중 에러: {e}", exc_info=True)

    return messages
    
# --- End of File ---