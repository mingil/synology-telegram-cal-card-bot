# bot.py
"""
텔레그램 봇 메인 실행 파일
- Application 설정 및 실행
- 스케줄링 작업 등록 (JobQueue 사용)
- Google AI 모델 초기화
- DB 초기화
"""

# --- 표준 라이브러리 임포트 ---
import asyncio
import datetime # date, time, timedelta 등 사용
import logging # 로깅 먼저 임포트
import os
import html
import json
from enum import IntEnum # 핸들러 파일에서만 쓰이면 여기서 지워도 됩니다.
from typing import Any, Dict, List, Optional, Union # 필요한 타입 힌트
import re # helpers.py 에서만 쓰이면 여기서 지워도 됩니다.
import traceback # helpers.py 에서만 쓰이면 여기서 지워도 됩니다.
import uuid # helpers.py 에서만 쓰이면 여기서 지워도 됩니다.

# --- 로컬 모듈 임포트 (config 먼저) ---
import config # LOG_LEVEL 등 설정값 사용 위해 필요

# ======[ 로깅 설정 (파일 상단, config 임포트 후) ]======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=config.LOG_LEVEL # config에서 로그 레벨 가져오기
)
logger = logging.getLogger(__name__)
# ======================================================

# --- 로컬 모듈 임포트 (나머지) ---
import database
import helpers
from korean_lunar_calendar import KoreanLunarCalendar # 음력 계산 위함

# --- 외부 라이브러리 임포트 ---
import google.generativeai as genai
import pytz
from dateutil.relativedelta import relativedelta
import caldav # CalDAV 라이브러리
from caldav.davclient import DAVClient
from caldav.lib.error import NotFoundError, DAVError, AuthorizationError # 필요한 에러 타입

# --- iCalendar 및 반복 일정 라이브러리 임포트 (정리된 방식) ---
try:
    # icalendar 임포트
    from icalendar import Calendar as iCalCalendar, Event as iCalEvent, vCalAddress, vText
except ImportError:
    iCalCalendar, iCalEvent, vCalAddress, vText = None, None, None, None
    logger.warning("⚠️ icalendar 라이브러리 설치 안됨. 관련 기능 제한됨.")

try:
    # recurring_ical_events 모듈 임포트 (Calendar 클래스 직접 임포트 대신)
    import recurring_ical_events
except ImportError:
    recurring_ical_events = None
    logger.warning("⚠️ recurring_ical_events 라이브러리 설치 안됨. 반복 일정 기능 제한됨.")
# -------------------------------------------------------------

import vobject # vobject 임포트

# Telegram 관련 임포트
from telegram import Update, BotCommand
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler,
                          ContextTypes, ConversationHandler, MessageHandler,
                          filters, ChatMemberHandler)
from telegram.constants import ChatAction, ParseMode

# --- 핸들러 및 상태 Enum 임포트 (기존과 동일) ---
from handlers import (
    AuthStates, AskAIStates, DateInputStates, SearchEventsStates,
    FindContactStates, AddContactStates, DeleteContactStates,
    SearchContactStates, UnbanStates, AddEventStates, DeleteEventStates,
    start, ask_ai_start, date_command_start, search_events_start,
    findcontact_start, addcontact_start, deletecontact_start,
    searchcontact_start, unban_start, addevent_start,
    banlist_command, permitlist_command,
    show_today_events, show_week_events, show_month_events,
    deleteevent_start, echo,
    password_received, ask_ai_question_received, date_input_received,
    search_events_keyword_received, findcontact_name_received,
    addcontact_name_received, addcontact_phone_received, addcontact_email_received,
    deletecontact_target_received, searchcontact_keyword_received,
    unban_target_received, addevent_title_received, addevent_start_received,
    addevent_end_received, deleteevent_keyword_received,
    button_callback_handler, addevent_calendar_selected,
    delete_confirmation_callback, cancel_conversation, inform_cancel_needed,
    deleteevent_method_selected, deleteevent_event_selected,
    deleteevent_confirm_callback, my_chat_member_handler
)
# ==================================================


#========================================================================================

# --- 시작/종료 알림 함수 ---
async def send_startup_notification(application: Application):
    # ... (기존 코드 유지) ...
    bot = application.bot
    chat_id = config.TARGET_CHAT_ID
    if bot and chat_id:
        try:
            await bot.send_message(chat_id=chat_id, text="✅ [텔레그램 봇 알림] 봇 시작 및 초기화 완료!")
            print("Startup notification sent.")
        except Exception as e:
            print(f"Failed to send startup notification: {e}")

async def send_shutdown_notification(application: Application):
    # ... (기존 코드 유지) ...
    bot = application.bot
    chat_id = config.TARGET_CHAT_ID
    if bot and chat_id:
        try:
            await bot.send_message(chat_id=chat_id, text="⚠️ [텔레그램 봇 알림] 봇이 종료됩니다...")
            print("Shutdown notification sent.")
        except Exception as e:
            print(f"Failed to send shutdown notification: {e}")

# --- Google AI 모델 설정 ---
model = None
if config.GOOGLE_API_KEY:
    try:
        genai.configure(api_key=config.GOOGLE_API_KEY)
        model = genai.GenerativeModel(config.AI_MODEL_NAME)
        logger.info("Google AI Model configured successfully.")
    except Exception as e: logger.error(f"Error configuring Google AI: {e}")
else: logger.warning("GOOGLE_API_KEY not set. AI features disabled.")

# ==================================================
#  반복 이벤트 확인 및 알림 기능 (JobQueue 콜백) - 최종 수정 버전 v7 (로그 개선)
# ==================================================
async def check_recurring_events(context: ContextTypes.DEFAULT_TYPE):
    """
    CalDAV에서 반복 이벤트를 확인하고 조건(오늘, 1주 후, 1달 후)에 맞으면
    텔레그램 알림을 보냅니다. 음력(윤달 포함) 및 일반 반복 이벤트를 처리합니다.
    """
    bot = context.bot
    function_start_time = datetime.datetime.now()
    # [로그 개선] 작업 시작 로그 개선 (실행 시간 포함)
    logger.info(f"🤖 [{function_start_time.strftime('%Y-%m-%d %H:%M:%S')}] 반복 이벤트 확인 작업 시작 (v7 - 로그 개선)...")

    # --- 설정값 로드 및 확인 ---
    target_chat_id_str = config.TARGET_CHAT_ID
    caldav_url = config.CALDAV_URL
    caldav_user = config.CALDAV_USERNAME
    caldav_pwd = config.CALDAV_PASSWORD
    tz_str = config.TIMEZONE

    # [로그 개선] 필수 설정값 누락 시 명확한 에러 로그
    if not target_chat_id_str: logger.error("🚨 CRITICAL: TARGET_CHAT_ID 설정 없음! 작업 중단."); return
    try: target_chat_id = int(target_chat_id_str)
    except ValueError: logger.error(f"🚨 CRITICAL: TARGET_CHAT_ID 값 오류 ('{target_chat_id_str}')! 작업 중단."); return
    if not (caldav_url and caldav_user and caldav_pwd): logger.warning("⚠️ CalDAV 설정 부족. 반복 이벤트 확인 작업을 건너<0xEB><0x9B><0x81>니다."); return

    # --- 라이브러리 로드 확인 ---
    if not iCalCalendar or not iCalEvent: logger.error("🚨 CRITICAL: icalendar 라이브러리 로드 실패! 작업 중단."); return
    if not recurring_ical_events: logger.error("🚨 CRITICAL: recurring_ical_events 라이브러리 로드 실패! 작업 중단."); return
    # ---------------------------------

    # --- 시간대 설정 ---
    try: TIMEZONE = pytz.timezone(tz_str)
    except pytz.UnknownTimeZoneError: logger.warning(f"⚠️ 알 수 없는 시간대 설정: '{tz_str}'. UTC 시간대로 진행합니다."); TIMEZONE = pytz.utc

    # --- 기준 날짜 계산 ---
    now_aware = datetime.datetime.now(TIMEZONE)
    today_date = now_aware.date()
    one_week_later = today_date + datetime.timedelta(days=7)
    one_month_later = today_date + relativedelta(months=1)

    # --- 이벤트 검색 기간 설정 ---
    search_start_dt = datetime.datetime.combine(today_date, datetime.time.min, tzinfo=TIMEZONE)
    search_end_dt = datetime.datetime.combine(today_date + relativedelta(months=2), datetime.time.max, tzinfo=TIMEZONE)

    # [로그 개선] 기준 날짜/기간 로그 명확화
    logger.info(f"기준 날짜: 오늘={today_date}, 1주 후={one_week_later}, 1달 후={one_month_later} (시간대: {tz_str})")
    logger.info(f"이벤트 검색 기간: {search_start_dt.strftime('%Y-%m-%d')} ~ {search_end_dt.strftime('%Y-%m-%d')}")

    events_to_notify: List[Dict[str, Any]] = []
    processed_event_count = 0
    total_calendars = 0
    processed_calendars = 0
    client = None

    try:
        # [로그 개선] CalDAV 연결 시도 로그
        logger.info(f"🔗 CalDAV 서버 연결 시도: {caldav_url}")
        client = DAVClient(url=caldav_url, username=caldav_user, password=caldav_pwd)
        try:
            principal = client.principal()
            calendars = principal.calendars()
            total_calendars = len(calendars) # 전체 캘린더 수 저장
        # [로그 개선] 인증/서버 오류 시 더 명확한 로그 및 사용자 알림
        except (AuthorizationError, DAVError) as auth_dav_err:
            logger.critical(f"🚨 CalDAV 인증/권한 오류 또는 서버 오류! {auth_dav_err}")
            await bot.send_message(chat_id=target_chat_id, text=f"🚨 CalDAV 서버 접속 오류 발생! (인증/권한 문제 또는 서버 오류). 관리자 확인 필요.")
            return
        except ConnectionError as conn_err:
             logger.critical(f"🚨 CalDAV 서버 연결 실패: {conn_err}")
             await bot.send_message(chat_id=target_chat_id, text=f"🚨 CalDAV 서버 연결 실패! 네트워크 또는 서버 주소를 확인해주세요.")
             return
        except Exception as e:
            logger.critical(f"🚨 CalDAV Principal/Calendar 목록 조회 중 치명적 오류: {e}", exc_info=True)
            await bot.send_message(chat_id=target_chat_id, text=f"🚨 CalDAV 처리 중 예상치 못한 오류 발생 (캘린더 목록 조회). 관리자 로그 확인 필요.")
            return

        if not calendars: logger.warning("⚠️ 접근 가능한 캘린더가 없습니다."); return
        logger.info(f"✅ CalDAV 연결 성공. 총 {total_calendars}개 캘린더 검색 시작...")

        # --- 각 캘린더 순회 ---
        for idx, calendar_obj in enumerate(calendars):
            processed_calendars += 1
            calendar_name = getattr(calendar_obj, 'name', '[이름 없음]')
            calendar_url_log = calendar_obj.url
            # [로그 개선] 처리 중인 캘린더 정보 명시 (진행률 표시)
            logger.info(f"  [{processed_calendars}/{total_calendars}] 캘린더 '{calendar_name}' 처리 시작...")
            try:
                # ======[ 원본 이벤트 가져오기 ]======
                logger.debug(f"    [DEBUG] '{calendar_name}' 원본 이벤트 로딩...")
                fetched_original_events = calendar_obj.events()
                event_count_in_cal = len(fetched_original_events)
                logger.debug(f"    [DEBUG] '{calendar_name}' 에서 {event_count_in_cal}개 원본 이벤트 발견.")
                # ==================================

                # --- 각 원본 이벤트 처리 ---
                for event_idx, event_dav in enumerate(fetched_original_events):
                    processed_event_count += 1
                    uid = "N/A"; summary = "N/A"; event_data = None; event_url_log = getattr(event_dav, 'url', '[URL 없음]')
                    # [로그 개선] 상세 디버그 로그 (처리 중인 이벤트 번호 포함)
                    logger.debug(f"      [DEBUG] ({event_idx+1}/{event_count_in_cal}) 이벤트 처리 중: URL={event_url_log}")
                    try:
                        # ... (이벤트 데이터 추출 및 icalendar 파싱 로직 동일) ...
                        event_data = event_dav.data
                        if not event_data: logger.debug(f"        [DEBUG] 데이터 없는 이벤트 건너<0xEB><0x9B><0x81>: {event_url_log}"); continue
                        cal = iCalCalendar.from_ical(event_data)

                        vevent_found = False
                        for component in cal.walk('VEVENT'):
                            vevent_found = True
                            vevent = component
                            uid = str(vevent.get('uid', 'N/A'))
                            summary = str(vevent.get('summary', 'N/A'))
                            rrule = vevent.get('rrule')

                            if not rrule: continue

                            rrule_str = rrule.to_ical().decode('utf-8').upper()
                            is_yearly = 'FREQ=YEARLY' in rrule_str
                            is_monthly = 'FREQ=MONTHLY' in rrule_str
                            if not is_yearly and not is_monthly: continue
                            event_frequency = 'yearly' if is_yearly else 'monthly'

                            logger.debug(f"        [DEBUG] 반복 이벤트 확인: UID='{uid}', Summary='{summary}', Type='{event_frequency}'")

                            # ======[ 음력 생일 처리 ]======
                            is_lunar_birthday = False
                            lunar_match = helpers.parse_lunar_date_from_summary(summary)
                            target_solar_date: Optional[datetime.date] = None

                            if is_yearly and lunar_match:
                                logger.debug(f"          [DEBUG] 음력 이벤트 감지: {lunar_match}")
                                lunar_month, lunar_day, is_leap = lunar_match
                                try:
                                    solar_birthday_this_year = helpers.get_solar_date_for_lunar(today_date.year, lunar_month, lunar_day, is_leap)
                                    if not solar_birthday_this_year or solar_birthday_this_year < today_date:
                                        next_year = today_date.year + 1
                                        logger.debug(f"          [DEBUG] 올해 음력 생일 지남/실패. 내년({next_year}) 계산.")
                                        target_solar_date = helpers.get_solar_date_for_lunar(next_year, lunar_month, lunar_day, is_leap)
                                    else: target_solar_date = solar_birthday_this_year

                                    if target_solar_date:
                                        is_lunar_birthday = True
                                        logger.debug(f"          [DEBUG] 음력 -> 양력 변환 결과: {target_solar_date}")
                                        notification_type = None; base_message = ""
                                        lunar_date_str = f"{lunar_month}/{lunar_day}{' 윤' if is_leap else ''}"
                                        if target_solar_date == today_date: notification_type = 'day'; base_message = f"오늘은 **{html.escape(summary)}** (양력 {target_solar_date.strftime('%m/%d')}) 입니다! 🎉"
                                        elif target_solar_date == one_week_later: notification_type = 'week'; base_message = f"📌 1주일 후 ({target_solar_date.strftime('%m/%d')}) : **{html.escape(summary)}** (음력 {lunar_date_str})"
                                        elif target_solar_date == one_month_later: notification_type = 'month'; base_message = f"🗓️ 1개월 후 ({target_solar_date.strftime('%m/%d')}) : **{html.escape(summary)}** (음력 {lunar_date_str})"

                                        if notification_type and base_message:
                                            final_message = base_message
                                            if "생일" in summary or "생신" in summary: final_message = "🎂🎉 " + final_message
                                            notification_key_date_str = target_solar_date.strftime('%Y-%m-%d')
                                            already_sent = database.has_notification_been_sent(uid, notification_key_date_str, notification_type)
                                            if not already_sent:
                                                events_to_notify.append({'uid': uid, 'target_date_str': notification_key_date_str, 'notification_type': notification_type, 'message': final_message})
                                                # [로그 개선] 알림 추가 로그 명확화
                                                logger.info(f"      ➡️ 알림 추가 [LUNAR/{notification_type.upper()}]: '{summary}' (기준일: {notification_key_date_str})")
                                            else: logger.debug(f"          [DEBUG] 건너<0xEB><0x9B><0x81> (이미 발송됨): UID={uid}, Date={notification_key_date_str}, Type={notification_type}")
                                    else: logger.warning(f"        [WARN] 음력 이벤트 '{summary}'의 최종 양력 날짜 계산 실패.")
                                except Exception as lunar_err: logger.error(f"      [ERROR] 음력 생일 처리 중 오류 ('{summary}'): {lunar_err}", exc_info=True)
                            # --- 음력 생일 처리 끝 ---

                            # ======[ 일반 반복 일정 처리 ]======
                            if not is_lunar_birthday:
                                logger.debug(f"        [DEBUG] 일반 반복 처리 시작 (recurring_ical_events)...")
                                try:
                                    rie_cal = recurring_ical_events.of(cal) # of() 함수 사용
                                    # recurring_ical_events 3.0.0 이상 버전은 .between()을 지원
                                    recurring_instances = rie_cal.between(search_start_dt, search_end_dt)
                                    instance_list = list(recurring_instances)
                                    instance_count = len(instance_list)
                                    logger.debug(f"        [DEBUG] recurring_ical_events: {instance_count}개 인스턴스 발견.")

                                    for instance_obj in instance_list:
                                        instance_dt = None; is_all_day = False
                                        if isinstance(instance_obj, datetime.datetime): instance_dt = instance_obj
                                        elif isinstance(instance_obj, iCalEvent):
                                            dtstart_prop = instance_obj.get('dtstart')
                                            if dtstart_prop and hasattr(dtstart_prop, 'dt'):
                                                start_value = dtstart_prop.dt
                                                if isinstance(start_value, datetime.datetime): instance_dt = start_value; is_all_day = False
                                                elif isinstance(start_value, datetime.date): instance_dt = datetime.datetime.combine(start_value, datetime.time.min); is_all_day = True
                                                else: logger.warning(f"          [WARN] Event 객체 내 dtstart 값이 이상함: {type(start_value)}")
                                            else: logger.warning(f"          [WARN] Event 객체에서 dtstart 값 못 찾음.")
                                        else: logger.warning(f"        [WARN] recurring_ical_events가 예상 못한 타입 반환: {type(instance_obj)}. 건너<0xEB><0x9B><0x81>."); continue

                                        if not instance_dt: logger.warning(f"        [WARN] 인스턴스에서 유효한 datetime 못 얻음. 건너<0xEB><0x9B><0x81>."); continue

                                        if instance_dt.tzinfo is None or instance_dt.tzinfo.utcoffset(instance_dt) is None: instance_dt_aware = TIMEZONE.localize(instance_dt)
                                        else: instance_dt_aware = instance_dt.astimezone(TIMEZONE)
                                        instance_date = instance_dt_aware.date()

                                        logger.debug(f"          [DEBUG] 인스턴스 시간 확인: Date={instance_date.strftime('%Y-%m-%d')}, Time={instance_dt_aware.strftime('%H:%M:%S')}, AllDay={is_all_day}")

                                        notification_type = None; base_message = ""
                                        time_str = "" if is_all_day else f" ({instance_dt_aware.strftime('%H:%M')})"
                                        if instance_date == today_date: notification_type = 'day'; base_message = f"🔔 오늘 **{html.escape(summary)}**{time_str} 일정이 있습니다!"
                                        elif instance_date == one_week_later: notification_type = 'week'; base_message = f"📌 1주일 후 ({instance_date.strftime('%m/%d')}) : **{html.escape(summary)}**{time_str}"
                                        elif instance_date == one_month_later and is_yearly: notification_type = 'month'; base_message = f"🗓️ 1개월 후 ({instance_date.strftime('%m/%d')}) : **{html.escape(summary)}**{time_str}"

                                        if notification_type and base_message:
                                            final_message = base_message
                                            if "생일" in summary or "생신" in summary: final_message = "🎂🎉 " + final_message
                                            notification_key_date_str = instance_date.strftime('%Y-%m-%d')
                                            already_sent = database.has_notification_been_sent(uid, notification_key_date_str, notification_type)
                                            if not already_sent:
                                                events_to_notify.append({'uid': uid, 'target_date_str': notification_key_date_str, 'notification_type': notification_type, 'message': final_message})
                                                # [로그 개선] 알림 추가 로그 명확화
                                                logger.info(f"      ➡️ 알림 추가 [{event_frequency.upper()}/{notification_type.upper()}]: '{summary}' (기준일: {notification_key_date_str})")
                                            else: logger.debug(f"          [DEBUG] 건너<0xEB><0x9B><0x81> (이미 발송됨): UID={uid}, Date={notification_key_date_str}, Type={notification_type}")
                                    # --- 인스턴스 루프 끝 ---

                                except AttributeError as attr_err: logger.error(f"      [ERROR] recurring_ical_events 속성 오류 (UID='{uid}', Summary='{summary}'): {attr_err}. 라이브러리 설치/API 확인 필요.", exc_info=True)
                                except Exception as recur_err: logger.error(f"      [ERROR] recurring_ical_events 처리 오류 (UID='{uid}', Summary='{summary}'): {recur_err}", exc_info=True)
                            # --- 일반 반복 일정 처리 끝 ---
                            break # VEVENT 하나 처리 완료
                        # --- VEVENT 컴포넌트 루프 끝 ---
                        if not vevent_found: logger.debug(f"      [DEBUG] VEVENT 컴포넌트 없음: URL={event_url_log}")
                    # --- 개별 원본 이벤트 처리 중 예외 ---
                    except Exception as inner_e: logger.error(f"    🚨 개별 이벤트 처리 오류 (URL: {event_url_log}): {inner_e}", exc_info=True)
                # --- 원본 이벤트 루프 끝 ---
            # --- 캘린더 처리 중 예외 ---
            except Exception as outer_e: logger.error(f"  🚨 캘린더 '{calendar_name}' 처리 중 오류: {outer_e}", exc_info=True)
            # [로그 개선] 각 캘린더 처리 완료 로그
            logger.info(f"  ✅ 캘린더 '{calendar_name}' 처리 완료.")
        # --- 캘린더 루프 끝 ---

    # --- 전체 CalDAV 처리 중 예외 ---
    except (AuthorizationError, ConnectionError, DAVError) as conn_dav_err:
        logger.critical(f"🚨 CalDAV 연결/인증/서버 오류 (최상위): {conn_dav_err}")
        try: await bot.send_message(chat_id=target_chat_id, text=f"🚨 CalDAV 서버 오류 발생! 관리자 확인 필요.")
        except Exception: pass
    except Exception as general_e:
        logger.critical(f"🚨 반복 이벤트 확인 작업 중 예기치 않은 심각한 오류 발생: {general_e}", exc_info=True)
        try: await bot.send_message(chat_id=target_chat_id, text=f"🚨 반복 일정 확인 중 심각한 오류 발생! 로그 확인 필요: {type(general_e).__name__}")
        except Exception as report_err: logger.error(f"🚨 오류 보고 메시지 발송 실패: {report_err}")
    finally:
        pass # client.close() 불필요

    # --- 최종 결과 로깅 및 알림 발송 ---
    logger.info(f"📊 이벤트 검색 완료. 확인된 원본 이벤트 수: {processed_event_count}")
    if events_to_notify:
        unique_event_keys = set()
        unique_events_to_notify = []
        for event_info in events_to_notify:
            key = (event_info['uid'], event_info['target_date_str'], event_info['notification_type'])
            if key not in unique_event_keys: unique_events_to_notify.append(event_info); unique_event_keys.add(key)
        logger.info(f"📨 {len(unique_events_to_notify)}개의 고유 알림 발송 예정.")
        sorted_events = sorted(unique_events_to_notify, key=lambda x: (x['target_date_str'], x['message']))
        from collections import defaultdict
        grouped_messages = defaultdict(list)
        for event_info in sorted_events: grouped_messages[event_info['target_date_str']].append(event_info)
        sent_count = 0; failed_count = 0
        for target_date_str, events_on_date in sorted(grouped_messages.items()):
             # [로그 개선] helpers.py 에 요일 함수가 없어도 오류나지 않도록 처리
             day_of_week_ko = ""
             if hasattr(helpers, 'get_day_of_week_ko'):
                 try: day_of_week_ko = helpers.get_day_of_week_ko(target_date_str)
                 except Exception as e: logger.warning(f"요일 변환 함수 오류: {e}")
             date_header = f"🗓️ {target_date_str} ({day_of_week_ko})" if day_of_week_ko else f"🗓️ {target_date_str}"
             messages_for_this_date = [event['message'] for event in events_on_date]
             combined_message = f"<b>{date_header} 알림</b>\n\n" + "\n\n".join(messages_for_this_date)
             try:
                MAX_MSG_LEN = 4000
                if len(combined_message) > MAX_MSG_LEN:
                    logger.warning(f"⚠️ 통합 메시지가 너무 김 ({len(combined_message)}자, {target_date_str}). 개별 발송합니다.")
                    await bot.send_message(chat_id=target_chat_id, text=f"<b>{date_header} 알림</b>\n(메시지가 길어 개별 전송합니다)", parse_mode=ParseMode.HTML); await asyncio.sleep(0.5)
                    for event_info in events_on_date:
                        try:
                            await bot.send_message(chat_id=target_chat_id, text=event_info['message'], parse_mode=ParseMode.MARKDOWN)
                            database.record_notification_sent(event_info['uid'], event_info['target_date_str'], event_info['notification_type'])
                            sent_count += 1; await asyncio.sleep(0.3)
                        except Exception as send_error: logger.error(f"🚨 개별 알림 발송 실패 (UID: {event_info.get('uid', 'N/A')}): {send_error}", exc_info=True); failed_count += 1
                else:
                    await bot.send_message(chat_id=target_chat_id, text=combined_message, parse_mode=ParseMode.HTML)
                    for event_info in events_on_date: database.record_notification_sent(event_info['uid'], event_info['target_date_str'], event_info['notification_type'])
                    sent_count += len(events_on_date); logger.debug(f"  [DB] 알림 기록 완료: {len(events_on_date)}건 ({target_date_str})")
                await asyncio.sleep(0.5)
             except Exception as send_error: logger.error(f"🚨 통합 알림 발송 실패 (Date: {target_date_str}): {send_error}", exc_info=True); failed_count += len(events_on_date)
        logger.info(f"✅ 알림 발송 완료: 성공 {sent_count}건, 실패 {failed_count}건")
    else: logger.info("✅ 발송할 새 알림 없음.")

    duration = datetime.datetime.now() - function_start_time
    # [로그 개선] 작업 종료 로그 명확화
    logger.info(f"🏁 반복 이벤트 확인 작업 종료. (총 소요 시간: {duration})")
# ==================================================

# ==================================================
#  Main Function
# ==================================================
def main() -> None:
    """봇 메인 실행 함수: Application 설정, JobQueue 등록, 핸들러 등록, 폴링 시작"""
    logger.info("main() 함수 시작됨.")

    # --- 초기 설정 확인 ---
    if not config.TELEGRAM_BOT_TOKEN: logger.critical("TELEGRAM_BOT_TOKEN 없음! 종료."); return
    logger.info("텔레그램 토큰 확인 완료.")
    if model: logger.info("Google AI 모델 확인 완료.")
    else: logger.warning("Google AI 모델 설정 안됨. /ask 사용 불가.")
    try: database.init_db()
    except Exception as db_err: logger.error(f"DB 초기화 오류: {db_err}", exc_info=True); return

    # --- Telegram Application 생성 ---
    try:
        application = (
            ApplicationBuilder()
            .token(config.TELEGRAM_BOT_TOKEN)
            # .post_init(set_bot_commands) # BotFather 방식 사용 시 주석 처리
            .post_init(send_startup_notification)
            .post_shutdown(send_shutdown_notification)
            .build()
        )
        if model: application.bot_data['ai_model'] = model; logger.info("AI 모델 bot_data 저장 완료.")
        logger.info("Telegram Application 빌드 완료.")
    except Exception as app_err: logger.error(f"App 빌드 오류: {app_err}", exc_info=True); return

    # --- JobQueue 작업 등록 ---
    logger.info("JobQueue 작업 등록 시도...")
    # (JobQueue 등록 로직은 기존과 동일하게 유지)
    if config.TARGET_CHAT_ID and config.CALDAV_URL and config.CALDAV_USERNAME and config.CALDAV_PASSWORD:
        try:
            target_chat_id_int = int(config.TARGET_CHAT_ID)
            tz_str = config.TIMEZONE
            try: schedule_timezone = pytz.timezone(tz_str)
            except pytz.UnknownTimeZoneError: logger.warning(f"시간대 오류: {tz_str}, UTC 사용"); schedule_timezone = pytz.utc
            daily_time = datetime.time(hour=config.SCHEDULE_HOUR, minute=config.SCHEDULE_MINUTE, tzinfo=schedule_timezone)
            application.job_queue.run_daily( check_recurring_events, time=daily_time, name="daily_recurring_check")
            logger.info(f"✅ JobQueue 작업 등록됨 (매일 {daily_time.strftime('%H:%M %Z')}).")
        except ValueError: logger.error(f"TARGET_CHAT_ID ('{config.TARGET_CHAT_ID}') 숫자 아님")
        except Exception as e: logger.error(f"JobQueue 작업 등록 오류: {e}", exc_info=True)
    else: logger.warning("JobQueue 작업 등록 조건 불충족 (ID/CalDAV 정보 확인)")


    # --- 핸들러 등록 ---
    try:
        # ======[ 수정: 핸들러 함수 이름 직접 사용 ]======
        # --- 인증 대화 핸들러 ---
        auth_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start), CommandHandler("help", start)],
            states={AuthStates.WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_received)]}, # handlers.password_received -> password_received
            fallbacks=[CommandHandler("cancel", cancel_conversation)], # handlers.cancel_conversation -> cancel_conversation
        )
        application.add_handler(auth_conv_handler)

        # --- AI 질문 대화 핸들러 ---
        ask_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("ask", ask_ai_start)], # handlers.ask_ai_start -> ask_ai_start
            states={AskAIStates.WAITING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_ai_question_received), # handlers.ask_ai_question_received -> ask_ai_question_received
                MessageHandler(filters.COMMAND & filters.Regex(r'^/(?!cancel\b).*'), inform_cancel_needed) # handlers.inform_cancel_needed -> inform_cancel_needed
            ]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)], # handlers.cancel_conversation -> cancel_conversation
            allow_reentry=True
        )
        application.add_handler(ask_conv_handler)

        # --- 날짜별 일정 조회 대화 핸들러 ---
        date_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("date", date_command_start)], # handlers.date_command_start -> date_command_start
            states={DateInputStates.WAITING_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, date_input_received), # handlers.date_input_received -> date_input_received
                MessageHandler(filters.COMMAND & filters.Regex(r'^/(?!cancel\b).*'), inform_cancel_needed)
            ]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            allow_reentry=True
        )
        application.add_handler(date_conv_handler)

        # --- 일정 검색 대화 핸들러 ---
        search_events_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('search_events', search_events_start)], # handlers.search_events_start -> search_events_start
            states={SearchEventsStates.WAITING_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_events_keyword_received)]}, # handlers.search_events_keyword_received -> search_events_keyword_received
            fallbacks=[CommandHandler('cancel', cancel_conversation)],
            per_message=False, name="search_events_conversation", persistent=False
        )
        application.add_handler(search_events_conv_handler)

        # --- 일정 추가 대화 핸들러 ---
        add_event_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("addevent", addevent_start)], # handlers.addevent_start -> addevent_start
            states={
                AddEventStates.SELECT_CALENDAR: [CallbackQueryHandler(addevent_calendar_selected, pattern='^addevent_cal_name_')], # handlers.addevent_calendar_selected -> addevent_calendar_selected
                AddEventStates.WAITING_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addevent_title_received)], # handlers.addevent_title_received -> addevent_title_received
                AddEventStates.WAITING_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, addevent_start_received)], # handlers.addevent_start_received -> addevent_start_received
                AddEventStates.WAITING_END_OR_ALLDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, addevent_end_received)] # handlers.addevent_end_received -> addevent_end_received
            },
            fallbacks=[
                CommandHandler("cancel", cancel_conversation),
                CallbackQueryHandler(addevent_calendar_selected, pattern='^addevent_cancel$'), # 취소 버튼 처리
                MessageHandler(filters.COMMAND & filters.Regex(r'^/(?!cancel\b).*'), inform_cancel_needed)
            ],
            name="add_event_conversation", persistent=False
        )
        application.add_handler(add_event_conv_handler)


        # ======[ 이벤트 삭제 대화 핸들러 추가 ]======
        delete_event_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("deleteevent", deleteevent_start)],
            states={
                DeleteEventStates.SELECT_METHOD: [
                    CallbackQueryHandler(deleteevent_method_selected, pattern='^delete_event_(recent|search|cancel)$')
                ],
                DeleteEventStates.WAITING_KEYWORD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, deleteevent_keyword_received)
                ],
                DeleteEventStates.SELECT_EVENT: [
                    CallbackQueryHandler(deleteevent_event_selected, pattern='^delete_event_idx_')
                ],
                DeleteEventStates.CONFIRM_DELETION: [
                    CallbackQueryHandler(deleteevent_confirm_callback, pattern='^delete_event_confirm_(yes|no)$')
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel_conversation),
                # SELECT_METHOD 단계에서의 취소 버튼 처리 (위 SELECT_METHOD 상태에서 처리하므로 여기서 중복 필요 없을 수 있음)
                # CallbackQueryHandler(deleteevent_method_selected, pattern='^delete_event_cancel$'),
                # SELECT_EVENT 단계에서의 취소 버튼 처리
                CallbackQueryHandler(deleteevent_event_selected, pattern='^delete_event_cancel$'),
                # 다른 명령어 입력 시 안내
                MessageHandler(filters.COMMAND & filters.Regex(r'^/(?!cancel\b).*'), inform_cancel_needed)
            ],
            name="delete_event_conversation", # 고유 이름 지정
            persistent=False # 대화 상태 저장 안 함
        )
        application.add_handler(delete_event_conv_handler)
        # ========================================

        # --- 연락처 검색(이름) 대화 핸들러 ---
        find_contact_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("findcontact", findcontact_start)], # handlers.findcontact_start -> findcontact_start
            states={FindContactStates.WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, findcontact_name_received), # handlers.findcontact_name_received -> findcontact_name_received
                MessageHandler(filters.COMMAND & filters.Regex(r'^/(?!cancel\b).*'), inform_cancel_needed)
            ]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            allow_reentry=True
        )
        application.add_handler(find_contact_conv_handler)

        # --- 연락처 추가 대화 핸들러 ---
        add_contact_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("addcontact", addcontact_start)], # handlers.addcontact_start -> addcontact_start
            states={
                AddContactStates.WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcontact_name_received)], # handlers.addcontact_name_received -> addcontact_name_received
                AddContactStates.WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcontact_phone_received)], # handlers.addcontact_phone_received -> addcontact_phone_received
                AddContactStates.WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcontact_email_received)] # handlers.addcontact_email_received -> addcontact_email_received
            },
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            allow_reentry=True
        )
        application.add_handler(add_contact_conv_handler)

        # --- 연락처 삭제 대화 핸들러 ---
        delete_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("deletecontact", deletecontact_start)], # handlers.deletecontact_start -> deletecontact_start
            states={
                DeleteContactStates.WAITING_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, deletecontact_target_received)], # handlers.deletecontact_target_received -> deletecontact_target_received
                DeleteContactStates.CONFIRM_DELETION: [CallbackQueryHandler(delete_confirmation_callback, pattern='^(confirm_delete|cancel_delete)$')] # handlers.delete_confirmation_callback -> delete_confirmation_callback
            },
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            allow_reentry=True
        )
        application.add_handler(delete_conv_handler)

        # --- 연락처 검색(키워드) 대화 핸들러 ---
        search_contact_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("searchcontact", searchcontact_start)], # handlers.searchcontact_start -> searchcontact_start
            states={SearchContactStates.WAITING_KEYWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, searchcontact_keyword_received), # handlers.searchcontact_keyword_received -> searchcontact_keyword_received
                MessageHandler(filters.COMMAND & filters.Regex(r'^/(?!cancel\b).*'), inform_cancel_needed)
            ]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            allow_reentry=True
        )
        application.add_handler(search_contact_conv_handler)

        # --- 관리자 명령어 핸들러 ---
        application.add_handler(CommandHandler("banlist", banlist_command)) # handlers.banlist_command -> banlist_command
        # /unban 은 ConversationHandler 로 변경
        # ======[ /permitlist 핸들러 등록 추가 ]======
        application.add_handler(CommandHandler("permitlist", permitlist_command))
        unban_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("unban", unban_start)], # handlers.unban_start -> unban_start
            states={UnbanStates.WAITING_TARGET_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, unban_target_received)]}, # handlers.unban_target_received -> unban_target_received
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            name="unban_conversation", persistent=False,
        )
        application.add_handler(unban_conv_handler)

        # ======[ 봇 퇴장 알림 핸들러 등록 (수정) ]======
        # 봇 자신의 상태 변경만 처리 (MY_CHAT_MEMBER)
        # ChatMemberUpdatedHandler -> ChatMemberHandler 로 변경
        application.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
        logger.info("ChatMemberHandler (for bot's own status) registered.")

        # --- 단일 명령어 핸들러 ---
        application.add_handler(CommandHandler("today", show_today_events)) # handlers.show_today_events -> show_today_events
        application.add_handler(CommandHandler("week", show_week_events))   # handlers.show_week_events -> show_week_events
        application.add_handler(CommandHandler("month", show_month_events)) # handlers.show_month_events -> show_month_events

        # --- 콜백 쿼리 핸들러 (가장 일반적인 핸들러) ---
        # 특정 패턴이 없는 버튼 클릭은 여기서 처리
        application.add_handler(CallbackQueryHandler(button_callback_handler)) # handlers.button_callback_handler -> button_callback_handler

        # --- Echo 핸들러 (가장 마지막) ---
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo)) # handlers.echo -> echo
        # ==================================================

        logger.info("모든 핸들러 등록 완료.")

    except Exception as handler_err:
        logger.error(f"핸들러 등록 오류: {handler_err}", exc_info=True)
        return # 핸들러 등록 실패 시 종료

# ==========================================================
    # [추가됨] 음력 기념일 자동 알림 스케줄러 (매일 아침 9시 실행)
    # ==========================================================
    async def scheduled_lunar_alarm(context: ContextTypes.DEFAULT_TYPE):
        """매일 아침 실행되어 30일/7일/1일 뒤가 음력 기념일인지 확인"""
        chat_id = config.TARGET_CHAT_ID
        if not chat_id:
            return

        # 30일 전, 7일 전, 1일 전 미리 알림
        check_days_list = [30, 7, 1] 
        
        for days in check_days_list:
            # helpers.py에 추가할 함수를 호출하여 메시지를 가져옴
            try:
                # 비동기 안에서 동기 함수 실행을 위해 run_in_executor 사용 권장되나, 
                # 간단한 연산이므로 직접 호출합니다.
                messages = helpers.check_upcoming_lunar_events(days)
                for msg in messages:
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"음력 스케줄러 실행 중 오류: {e}")

    # 매일 오전 9시 00분에 실행 (시간 변경 가능)
    # timezone은 config.TZ (Asia/Seoul)를 따름
    if application.job_queue:
        application.job_queue.run_daily(
            scheduled_lunar_alarm, 
            time=datetime.time(hour=7, minute=0, second=0, tzinfo=pytz.timezone('Asia/Seoul'))
        )
        logger.info("📅 음력 기념일 알림 스케줄러 등록 완료 (매일 09:00)")
    # ==========================================================

    # ===== 봇 실행 =====
    logger.info("봇 폴링 시작...")
    try:
        logger.info(">>> Calling application.run_polling()...")
        application.run_polling() # 블로킹 함수
        logger.warning(">>> Polling loop finished unexpectedly.") # 정상 종료 외의 경우
    except (KeyboardInterrupt, SystemExit):
        logger.info("종료 신호 수신. Application shutdown 시작됨...")
    except Exception as e:
        logger.error(f"봇 실행 중 예상치 못한 오류 발생: {e}", exc_info=True)
    # ====================

# --- 스크립트 실행 부분 ---
if __name__ == '__main__':
    logger.info("######## Script execution started ########")
    try:
        main()
    except Exception as main_run_err:
        logger.critical(f"Critical error running main function: {main_run_err}", exc_info=True)
    finally:
        logger.info("######## Script execution finished ########")

# --- End of File ---