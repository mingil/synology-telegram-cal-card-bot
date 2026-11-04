import logging
import asyncio
from enum import IntEnum
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from handlers.decorators import check_ban, require_auth
from handlers.common import clear_other_conversations

logger = logging.getLogger(__name__)


class AskAIStates(IntEnum):
    WAITING_QUESTION = 30


async def _send_ai_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> int:
    chat_session = context.user_data.get("ai_chat_session")
    if not chat_session:
        await update.message.reply_text("⚠️ AI 세션이 만료되었습니다. /ask 명령어를 다시 입력해주세요.")
        return ConversationHandler.END

    msg = await update.message.reply_text("🤖 답변을 생성하는 중입니다... 🤔")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    try:
        response = await asyncio.wait_for(chat_session.send_message_async(question), timeout=30.0)
        ai_text = response.text or "답변을 생성하지 못했습니다."

        if len(ai_text) > 4000:
            ai_text = ai_text[:3950] + "\n\n...(답변이 너무 길어 생략됨)"

        try:
            formatted_text = ai_text.replace("**", "*")
            await msg.edit_text(f"🤖 *AI 답변:*\n\n{formatted_text}", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.debug(f"AI 마크다운 파싱 에러, 일반 텍스트로 우회: {e}")
            try:
                safe_text = ai_text.replace("*", "").replace("_", "").replace("`", "'")
                await msg.edit_text(f"🤖 AI 답변:\n\n{safe_text}")
            except Exception:
                pass

        return AskAIStates.WAITING_QUESTION

    except asyncio.TimeoutError:
        try:
            await msg.edit_text("⏳ AI 응답 시간이 초과되었습니다. 조금 뒤에 다른 질문을 입력해주세요.")
        except Exception:
            pass
        return AskAIStates.WAITING_QUESTION

    except Exception as e:
        logger.error(f"❌ AI 답변 생성 중 오류: {e}")
        try:
            await msg.edit_text("😵 답변 생성 중 일시적인 서버 오류가 발생했습니다. 다시 입력해주세요.")
        except Exception:
            pass
        return AskAIStates.WAITING_QUESTION


@check_ban
@require_auth
async def ask_ai_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context, ["ai_chat_session"])

    ai_model = context.bot_data.get("ai_model")
    if not ai_model:
        await update.message.reply_text("⚠️ 시스템 오류: 구글 Gemini API 키가 설정되지 않았습니다.")
        return ConversationHandler.END

    # 연속 대화(Session) 시작
    context.user_data["ai_chat_session"] = ai_model.start_chat(history=[])

    # '/ask 질문내용' 형태로 바로 질문이 함께 들어온 경우 즉시 답변
    if context.args:
        initial_question = " ".join(context.args).strip()
        if initial_question:
            return await _send_ai_answer(update, context, initial_question)

    await update.message.reply_text(
        "🤖 <b>AI 비서입니다! (연속 대화 모드)</b>\n\n"
        "이전 대화의 맥락을 기억합니다. 편하게 꼬리물기 질문을 해보세요!\n"
        "💡 <i>(대화를 끝내려면 <b>'종료'</b>, <b>'그만'</b> 또는 <b>/cancel</b> 입력)</i>",
        parse_mode=ParseMode.HTML,
    )
    return AskAIStates.WAITING_QUESTION


async def ask_ai_question_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    question = update.message.text.strip()

    if question.lower() in ["종료", "그만", "끝", "취소", "exit", "quit"]:
        context.user_data.pop("ai_chat_session", None)
        await update.message.reply_text("👋 AI 대화를 종료합니다. 봇 메인 메뉴는 /start 를 눌러주세요.")
        return ConversationHandler.END

    return await _send_ai_answer(update, context, question)
