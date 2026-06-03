import os
import logging
from logging.handlers import (
    RotatingFileHandler,
)  # 👈 [추가] 로그 파일 자동 순환(Rotation) 기능
import datetime
import html
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
# 1. 로그 파일이 저장될 물리적 경로 (볼륨 마운트된 data 폴더 내부)
LOG_FILE_PATH = os.path.join(config.DATA_DIR, "bot.log")

# 2. 로그 포맷 정의 (시간 - 모듈명 - 에러등급 - 내용)
log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# 3. 최상위(Root) 로거 가져오기 및 초기화
root_logger = logging.getLogger()
root_logger.setLevel(config.LOG_LEVEL)

# 중복 출력을 막기 위해 기존 핸들러 초기화
if root_logger.hasHandlers():
    root_logger.handlers.clear()

# 4. 파일 핸들러 (NAS 디스크에 물리적으로 저장: 최대 5MB씩 3개까지만 백업 보관)
try:
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)
except Exception as e:
    print(f"⚠️ 로그 파일 생성 실패: {e}")

# 5. 콘솔 핸들러 (시놀로지 Container Manager 화면에도 동시 출력)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

# 👇 서드파티 라이브러리의 불필요한 네트워크 스팸 로그 억제 (매우 중요)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
# =========================================================

# =========================================================
# 🛡️ 글로벌 에러 핸들러 (네트워크 에러 로그 최소화)
# =========================================================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """텔레그램 API 지연 등 자잘한 에러를 깔끔하게 한 줄로 로깅하는 핸들러"""
    if isinstance(context.error, (NetworkError, TimedOut)) or "Bad Gateway" in str(context.error):
        logger.warning(f"⚠️ 텔레그램 서버 일시 지연 (자동 복구됨): {context.error}")
    else:
        # 치명적인 에러일 경우에만 자세히 출력
        logger.error(f"❌ 예기치 않은 오류 발생: {context.error}", exc_info=context.error)

async def post_init(application: Application):
    logger.info("✅ 봇 초기화 완료 - Version 2.2 (Conversational Admin)")

    commands = [
        BotCommand("start", "🚀 시작 및 메인 메뉴"),
        BotCommand("help", "❓ 도움말 보기"),
        BotCommand("search_events", "🔎 일정 검색"),
        BotCommand("addevent", "➕ 일정 추가"),
        BotCommand("findcontact", "👤 연락처 검색"),
        BotCommand("addcontact", "✏️ 연락처 추가"),
        BotCommand("today", "📅 오늘 일정"),
        BotCommand("week", "🗓 이번 주 일정"),
        BotCommand("ask", "🤖 AI 질문"),
        BotCommand("banlist", "🛡️ 차단 목록 (관리자)"),
        BotCommand("permitlist", "✅ 허용 목록 (관리자)"),
        BotCommand("ban", "⛔ 사용자 차단 (관리자)"),
        BotCommand("unban", "🕊️ 차단 해제 (관리자)"),
        BotCommand("permit", "✅ 권한 부여 (관리자)"),
        BotCommand("revoke", "🛑 권한 취소 (관리자)"),
        BotCommand("cancel", "🚫 작업 취소"),
    ]

    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logger.error(f"메뉴 등록 실패: {e}")

    if config.TARGET_CHAT_ID:
        try:
            await application.bot.send_message(
                chat_id=config.TARGET_CHAT_ID,
                text="🚀 <b>시스템 알림</b>\n봇이 업데이트되었습니다. (관리자 기능 대화형으로 변경)",
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
        except:
            pass


async def global_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "show_all_commands":
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
        except:
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
        .post_init(post_init)
        .build()
    )

    if config.GOOGLE_API_KEY:
        import google.generativeai as genai

        genai.configure(api_key=config.GOOGLE_API_KEY)
        model = genai.GenerativeModel(config.AI_MODEL_NAME)
        application.bot_data["ai_model"] = model
        logger.info("🧠 AI 모델 로드 완료.")

    # [1] 인증 핸들러
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("start", h_auth.start)],
            states={
                h_auth.AuthStates.WAITING_PASSWORD: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, h_auth.password_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )

    # [2] AI 핸들러
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("ask", h_ai.ask_ai_start)],
            states={
                h_ai.AskAIStates.WAITING_QUESTION: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, h_ai.ask_ai_question_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )

    # [3] 캘린더 추가 핸들러
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("addevent", h_cal.addevent_start)],
            states={
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
            },
            fallbacks=[
                CommandHandler("cancel", h_common.cancel_conversation),
                CallbackQueryHandler(
                    h_cal.addevent_calendar_selected, pattern="^addevent_cancel$"
                ),
            ],
        )
    )

    # [4] 기타 캘린더/연락처 핸들러들
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("date", h_cal.date_command_start)],
            states={
                h_cal.DateInputStates.WAITING_DATE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, h_cal.date_input_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("search_events", h_cal.search_events_start)],
            states={
                h_cal.SearchEventsStates.WAITING_KEYWORD: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        h_cal.search_events_keyword_received,
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("findcontact", h_contact.findcontact_start)],
            states={
                h_contact.FindContactStates.WAITING_NAME: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        h_contact.findcontact_name_received,
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )
    application.add_handler(
        ConversationHandler(
            entry_points=[
                CommandHandler("searchcontact", h_contact.searchcontact_start)
            ],
            states={
                h_contact.SearchContactStates.WAITING_KEYWORD: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        h_contact.searchcontact_keyword_received,
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("addcontact", h_contact.addcontact_start)],
            states={
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
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )

    # [5] 관리자 조회 명령어
    application.add_handler(CommandHandler("banlist", h_auth.banlist_command))
    application.add_handler(CommandHandler("permitlist", h_auth.permitlist_command))

    # [6] 관리자 액션 핸들러 (대화형) - 여기를 수정함
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("ban", h_auth.ban_start)],
            states={
                h_auth.AdminStates.WAITING_BAN_INPUT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, h_auth.ban_input_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("unban", h_auth.unban_start)],
            states={
                h_auth.AdminStates.WAITING_UNBAN_INPUT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, h_auth.unban_input_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("permit", h_auth.permit_start)],
            states={
                h_auth.AdminStates.WAITING_PERMIT_INPUT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, h_auth.permit_input_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("revoke", h_auth.revoke_start)],
            states={
                h_auth.AdminStates.WAITING_REVOKE_INPUT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, h_auth.revoke_input_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
        )
    )

    # [7] 일반 명령어
    application.add_handler(CommandHandler("today", h_cal.show_today_events))
    application.add_handler(CommandHandler("week", h_cal.show_week_events))
    application.add_handler(CommandHandler("month", h_cal.show_month_events))
    application.add_handler(CommandHandler("help", h_common.help_command))

    # [8] 공통 핸들러
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

# 👇 기존 명령어 핸들러들 등록된 코드 아래쪽, run_polling 바로 위에 추가!
    application.add_error_handler(global_error_handler)

    logger.info("🟢 봇 폴링 시작!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 봇 종료 중...")
