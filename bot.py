import os
import logging
from logging.handlers import RotatingFileHandler
import datetime
import pytz
from telegram.error import NetworkError, TimedOut
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    ChatMemberHandler,
    Application,
)
from telegram.constants import ParseMode

from core import config, database
from services import notification_service
import handlers.auth as h_auth
import handlers.calendar as h_cal
import handlers.contact as h_contact
import handlers.ai as h_ai
import handlers.common as h_common

# =========================================================
# 📝 실무형 로깅 설정 (콘솔 + 파일 동시 출력 및 용량 방어)
# =========================================================
LOG_FILE_PATH = os.path.join(config.DATA_DIR, "bot.log")

log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

root_logger = logging.getLogger()
root_logger.setLevel(config.LOG_LEVEL)

if root_logger.hasHandlers():
    root_logger.handlers.clear()

try:
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)
except Exception as e:
    print(f"⚠️ 로그 파일 생성 실패: {e}")

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

# 서드파티 라이브러리의 불필요한 네트워크 스팸 로그 억제
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
# =========================================================


# =========================================================
# 🛡️ 글로벌 에러 핸들러 (네트워크 에러 로그 최소화)
# =========================================================
async def global_error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """텔레그램 API 지연 등 자잘한 에러를 깔끔하게 한 줄로 로깅하는 핸들러"""
    err_str = str(context.error)
    if (
        isinstance(context.error, (NetworkError, TimedOut))
        or "Bad Gateway" in err_str
        or "ReadError" in err_str
        or "ConnectError" in err_str
    ):
        logger.warning(f"⚠️ 텔레그램 서버 일시 지연 (자동 복구됨): {context.error}")
    else:
        logger.error(f"❌ 예기치 않은 오류 발생: {context.error}", exc_info=context.error)


async def post_init(application: Application):
    logger.info("✅ 봇 초기화 완료 - Version 2.3 (Synology Optimized)")

    commands = [
        BotCommand("start", "🚀 시작 및 메인 메뉴"),
        BotCommand("help", "❓ 도움말 보기"),
        BotCommand("today", "📅 오늘 일정"),
        BotCommand("week", "🗓 이번 주 일정"),
        BotCommand("month", "📆 이번 달 일정"),
        BotCommand("date", "🔢 특정 날짜 일정 조회"),
        BotCommand("search_events", "🔎 일정 키워드 검색"),
        BotCommand("addevent", "➕ 새 일정 추가"),
        BotCommand("findcontact", "👤 연락처 이름 검색"),
        BotCommand("searchcontact", "🔍 연락처 상세 검색 (번호/이메일/메모)"),
        BotCommand("addcontact", "✏️ 새 연락처 추가"),
        BotCommand("ask", "🤖 AI 질문 (연속 대화)"),
        BotCommand("banlist", "🛡️ 차단 목록 (관리자)"),
        BotCommand("permitlist", "✅ 허용 목록 (관리자)"),
        BotCommand("ban", "⛔ 사용자 차단 (관리자)"),
        BotCommand("unban", "🕊️ 차단 해제 (관리자)"),
        BotCommand("permit", "✅ 권한 부여 (관리자)"),
        BotCommand("revoke", "🛑 권한 취소 (관리자)"),
        BotCommand("cancel", "🚫 진행 중인 작업 취소"),
    ]

    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logger.error(f"메뉴 등록 실패: {e}")

    if config.TARGET_CHAT_ID:
        try:
            await application.bot.send_message(
                chat_id=config.TARGET_CHAT_ID,
                text="🚀 <b>시스템 알림</b>\n봇이 정상적으로 시작되었습니다. (v2.3)",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.my_chat_member:
        return
    new_status = update.my_chat_member.new_chat_member.status
    if new_status in ["left", "kicked"] and config.ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(config.ADMIN_CHAT_ID, "⚠️ 봇 퇴장 알림")
        except Exception:
            pass


async def global_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data

    if data == "show_all_commands":
        await query.answer()
        await h_common.help_command(update, context)
    elif data.startswith("show_") or data == "add_event_prompt":
        await h_cal.calendar_button_handler(update, context)
    elif data == "search_events_prompt":
        await query.answer()
        await query.message.reply_text(
            "🔎 일정을 검색하려면 /search_events 명령어를 입력하세요."
        )
    elif data == "find_contact_prompt":
        await query.answer()
        await query.message.reply_text("🔎 연락처 검색: /findcontact")
    else:
        try:
            await h_cal.calendar_button_handler(update, context)
        except Exception:
            await query.answer("알 수 없는 버튼입니다.")


async def scheduled_checks(context: ContextTypes.DEFAULT_TYPE):
    await notification_service.run_daily_checks(context.application)


def main():
    logger.info("🚀 봇 시작 준비 중...")

    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("❌ 설정 오류: TELEGRAM_BOT_TOKEN 없음.")
        return

    database.init_db()

    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .connect_timeout(15.0)
        .read_timeout(15.0)
        .write_timeout(15.0)
        .get_updates_connect_timeout(15.0)
        .get_updates_read_timeout(30.0)
        .post_init(post_init)
        .build()
    )

    if config.GOOGLE_API_KEY:
        try:
            import google.generativeai as genai

            genai.configure(api_key=config.GOOGLE_API_KEY)
            model = genai.GenerativeModel(config.AI_MODEL_NAME)
            application.bot_data["ai_model"] = model
            logger.info(f"🧠 AI 모델 로드 완료 ({config.AI_MODEL_NAME}).")
        except Exception as e:
            logger.error(f"❌ AI 모델 초기화 실패: {e}")

    # [통합 대화형 핸들러]
    unified_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", h_auth.start),
            CommandHandler("ask", h_ai.ask_ai_start),
            CommandHandler("addevent", h_cal.addevent_start),
            CommandHandler("date", h_cal.date_command_start),
            CommandHandler("search_events", h_cal.search_events_start),
            CommandHandler("findcontact", h_contact.findcontact_start),
            CommandHandler("searchcontact", h_contact.searchcontact_start),
            CommandHandler("addcontact", h_contact.addcontact_start),
            CommandHandler("ban", h_auth.ban_start),
            CommandHandler("unban", h_auth.unban_start),
            CommandHandler("permit", h_auth.permit_start),
            CommandHandler("revoke", h_auth.revoke_start),
        ],
        states={
            # 1. 인증
            h_auth.AuthStates.WAITING_PASSWORD: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_auth.password_received
                )
            ],
            # 2. AI 연속 대화
            h_ai.AskAIStates.WAITING_QUESTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_ai.ask_ai_question_received
                )
            ],
            # 3. 캘린더 일정 추가
            h_cal.AddEventStates.SELECT_CALENDAR: [
                CallbackQueryHandler(
                    h_cal.addevent_calendar_selected, pattern="^addevent_cal_name_"
                )
            ],
            h_cal.AddEventStates.WAITING_TITLE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_cal.addevent_title_received
                )
            ],
            h_cal.AddEventStates.WAITING_START: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_cal.addevent_start_received
                )
            ],
            h_cal.AddEventStates.WAITING_END_OR_ALLDAY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_cal.addevent_end_received
                )
            ],
            # 4. 날짜 지정 조회 & 일정 검색
            h_cal.DateInputStates.WAITING_DATE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_cal.date_input_received
                )
            ],
            h_cal.SearchEventsStates.WAITING_KEYWORD: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    h_cal.search_events_keyword_received,
                )
            ],
            # 5. 연락처 검색 & 추가
            h_contact.FindContactStates.WAITING_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    h_contact.findcontact_name_received,
                )
            ],
            h_contact.SearchContactStates.WAITING_KEYWORD: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    h_contact.searchcontact_keyword_received,
                )
            ],
            h_contact.AddContactStates.WAITING_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    h_contact.addcontact_name_received,
                )
            ],
            h_contact.AddContactStates.WAITING_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    h_contact.addcontact_phone_received,
                )
            ],
            h_contact.AddContactStates.WAITING_EMAIL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    h_contact.addcontact_email_received,
                )
            ],
            # 6. 관리자 명령
            h_auth.AdminStates.WAITING_BAN_INPUT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_auth.ban_input_received
                )
            ],
            h_auth.AdminStates.WAITING_UNBAN_INPUT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_auth.unban_input_received
                )
            ],
            h_auth.AdminStates.WAITING_PERMIT_INPUT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_auth.permit_input_received
                )
            ],
            h_auth.AdminStates.WAITING_REVOKE_INPUT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, h_auth.revoke_input_received
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", h_common.cancel_conversation),
            CommandHandler("today", h_cal.show_today_events),
            CommandHandler("week", h_cal.show_week_events),
            CommandHandler("month", h_cal.show_month_events),
            CommandHandler("help", h_common.help_command),
            CommandHandler("banlist", h_auth.banlist_command),
            CommandHandler("permitlist", h_auth.permitlist_command),
            CallbackQueryHandler(
                h_cal.addevent_calendar_selected, pattern="^addevent_cancel$"
            ),
        ],
        allow_reentry=True,
    )
    application.add_handler(unified_conv_handler)

    # 일반/관리자 단발성 명령어 (대화 상태가 아닐 때 실행)
    application.add_handler(CommandHandler("banlist", h_auth.banlist_command))
    application.add_handler(CommandHandler("permitlist", h_auth.permitlist_command))
    application.add_handler(CommandHandler("today", h_cal.show_today_events))
    application.add_handler(CommandHandler("week", h_cal.show_week_events))
    application.add_handler(CommandHandler("month", h_cal.show_month_events))
    application.add_handler(CommandHandler("help", h_common.help_command))
    application.add_handler(CommandHandler("cancel", h_common.cancel_conversation))

    # 공통 핸들러
    application.add_handler(
        ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    application.add_handler(CallbackQueryHandler(global_button_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, h_common.echo)
    )

    if config.TARGET_CHAT_ID:
        try:
            tz = pytz.timezone(config.TIMEZONE)
            alarm_time = datetime.time(
                hour=config.SCHEDULE_HOUR, minute=config.SCHEDULE_MINUTE, tzinfo=tz
            )
            application.job_queue.run_daily(scheduled_checks, time=alarm_time)
            logger.info(f"⏰ 스케줄러 등록됨 (매일 {alarm_time})")
        except Exception as e:
            logger.error(f"스케줄러 등록 실패: {e}")

    application.add_error_handler(global_error_handler)

    logger.info("🟢 봇 폴링 시작!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 봇 종료 중...")
