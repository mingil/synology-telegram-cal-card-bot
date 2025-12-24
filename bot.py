# bot.py
import logging
import datetime
import html
import pytz
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler, ChatMemberHandler, Application
)
from telegram.constants import ParseMode

from core import config, database
from services import notification_service
import handlers.auth as h_auth
import handlers.calendar as h_cal
import handlers.contact as h_contact
import handlers.ai as h_ai
import handlers.common as h_common

# --- 로깅 설정 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=config.LOG_LEVEL
)
logger = logging.getLogger(__name__)

# [수정] 봇 시작 시 메뉴 설정 (이모티콘 복구 및 전체 명령어 추가)
async def post_init(application: Application):
    """봇 시작 후 초기화 작업 및 알림 전송"""
    logger.info("✅ 봇 초기화 완료")
    
    # 명령어 메뉴 버튼 설정 (이모티콘 포함)
    commands = [
        BotCommand("start", "🚀 시작 및 메인 메뉴"),
        BotCommand("help", "❓ 도움말 보기"),
        BotCommand("today", "📅 오늘 일정 조회"),
        BotCommand("week", "🗓 이번 주 일정 조회"),
        BotCommand("month", "📆 이번 달 일정 조회"),
        BotCommand("date", "📌 특정 날짜 조회"),
        BotCommand("search_events", "🔎 일정 키워드 검색"),
        BotCommand("addevent", "➕ 새 일정 추가"),
        BotCommand("findcontact", "👤 연락처 이름 검색"),
        BotCommand("searchcontact", "🔍 연락처 상세 검색"),
        BotCommand("addcontact", "✏️ 새 연락처 추가"),
        BotCommand("ask", "🤖 AI에게 질문하기"),
        BotCommand("cancel", "🚫 작업 취소"),
        BotCommand("banlist", "🛡️ 차단 목록 (관리자)"),
        BotCommand("permitlist", "✅ 허용 목록 (관리자)")
    ]
    
    await application.bot.set_my_commands(commands)

    if config.TARGET_CHAT_ID:
        try:
            await application.bot.send_message(
                chat_id=config.TARGET_CHAT_ID,
                text="🚀 <b>시스템 알림</b>\n봇이 성공적으로 재시작되었습니다.\n메뉴가 업데이트되었습니다.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"시작 알림 전송 실패: {e}")

async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.my_chat_member: return
    new_status = update.my_chat_member.new_chat_member.status
    chat = update.my_chat_member.chat
    
    if new_status in ['left', 'kicked']:
        logger.warning(f"봇 퇴장: {chat.title}")
        if config.ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    config.ADMIN_CHAT_ID, 
                    f"⚠️ <b>봇 퇴장 알림</b>\n{html.escape(chat.title)}", 
                    parse_mode=ParseMode.HTML
                )
            except Exception: pass

async def global_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """메인 버튼 처리"""
    query = update.callback_query
    data = query.data
    
    # 캘린더 관련 버튼
    if data.startswith("show_") or data == "add_event_prompt":
        if data == "show_all_commands":
            await h_common.help_command(update, context)
        else:
            await h_cal.calendar_button_handler(update, context)
    
    elif data == "search_events_prompt":
         await query.answer()
         await query.message.reply_text("🔎 일정을 검색하려면 /search_events 명령어를 입력하세요.")

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

    application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    if config.GOOGLE_API_KEY:
        import google.generativeai as genai
        genai.configure(api_key=config.GOOGLE_API_KEY)
        model = genai.GenerativeModel(config.AI_MODEL_NAME)
        application.bot_data['ai_model'] = model
        logger.info("🧠 AI 모델 로드 완료.")

    # [인증]
    auth_handler = ConversationHandler(
        entry_points=[CommandHandler("start", h_auth.start)],
        states={h_auth.AuthStates.WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_auth.password_received)]},
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    )
    application.add_handler(auth_handler)

    # [AI]
    ai_handler = ConversationHandler(
        entry_points=[CommandHandler("ask", h_ai.ask_ai_start)],
        states={h_ai.AskAIStates.WAITING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_ai.ask_ai_question_received)]},
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    )
    application.add_handler(ai_handler)

    # [캘린더 추가]
    add_event_handler = ConversationHandler(
        entry_points=[CommandHandler("addevent", h_cal.addevent_start)],
        states={
            h_cal.AddEventStates.SELECT_CALENDAR: [CallbackQueryHandler(h_cal.addevent_calendar_selected, pattern='^addevent_cal_name_')],
            h_cal.AddEventStates.WAITING_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_cal.addevent_title_received)],
            h_cal.AddEventStates.WAITING_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_cal.addevent_start_received)],
            h_cal.AddEventStates.WAITING_END_OR_ALLDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_cal.addevent_end_received)],
        },
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation), CallbackQueryHandler(h_cal.addevent_calendar_selected, pattern='^addevent_cancel$')],
    )
    application.add_handler(add_event_handler)

    # [캘린더 조회/검색]
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("date", h_cal.date_command_start)],
        states={h_cal.DateInputStates.WAITING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_cal.date_input_received)]},
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("search_events", h_cal.search_events_start)],
        states={h_cal.SearchEventsStates.WAITING_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_cal.search_events_keyword_received)]},
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    ))

    # [연락처]
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("findcontact", h_contact.findcontact_start)],
        states={h_contact.FindContactStates.WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_contact.findcontact_name_received)]},
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("searchcontact", h_contact.searchcontact_start)],
        states={h_contact.SearchContactStates.WAITING_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_contact.searchcontact_keyword_received)]},
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addcontact", h_contact.addcontact_start)],
        states={
            h_contact.AddContactStates.WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_contact.addcontact_name_received)],
            h_contact.AddContactStates.WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_contact.addcontact_phone_received)],
            h_contact.AddContactStates.WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_contact.addcontact_email_received)],
        },
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    ))

    # [관리자]
    application.add_handler(CommandHandler("banlist", h_auth.banlist_command))
    application.add_handler(CommandHandler("permitlist", h_auth.permitlist_command))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("unban", h_auth.unban_start)],
        states={h_auth.UnbanStates.WAITING_TARGET_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_auth.unban_target_received)]},
        fallbacks=[CommandHandler("cancel", h_common.cancel_conversation)],
    ))

    # [단일 명령어]
    application.add_handler(CommandHandler("today", h_cal.show_today_events))
    application.add_handler(CommandHandler("week", h_cal.show_week_events))
    application.add_handler(CommandHandler("month", h_cal.show_month_events))
    
    # /help 핸들러
    application.add_handler(CommandHandler("help", h_common.help_command))

    # [기타]
    application.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(global_button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h_common.echo))

    if config.TARGET_CHAT_ID:
        try:
            tz = pytz.timezone(config.TIMEZONE)
            alarm_time = datetime.time(hour=config.SCHEDULE_HOUR, minute=config.SCHEDULE_MINUTE, tzinfo=tz)
            application.job_queue.run_daily(scheduled_checks, time=alarm_time)
            logger.info(f"⏰ 스케줄러 등록됨 (매일 {alarm_time})")
        except Exception as e:
            logger.error(f"스케줄러 등록 실패: {e}")

    logger.info("🟢 봇 폴링 시작!")
    application.run_polling()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 봇 종료 중...")