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
    WAITING_QUESTION = 1

@check_ban
@require_auth
async def ask_ai_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_other_conversations(context)
    await update.message.reply_text(
        "🤖 <b>AI 비서입니다!</b> 무엇이든 물어보세요.\n"
        "질문을 입력해주세요. (취소: /cancel)",
        parse_mode=ParseMode.HTML
    )
    return AskAIStates.WAITING_QUESTION

async def ask_ai_question_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    question = update.message.text.strip()
    ai_model = context.bot_data.get("ai_model")

    if not ai_model:
        await update.message.reply_text("⚠️ 시스템 오류: 구글 Gemini API 키가 설정되지 않았습니다.")
        return ConversationHandler.END

    msg = await update.message.reply_text("🤖 답변을 생성하는 중입니다... 🤔")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    try:
        # [핵심 최적화] 타임아웃 30초 설정으로 봇 무한 대기 방어
        response = await asyncio.wait_for(ai_model.generate_content_async(question), timeout=30.0)
        ai_text = response.text

        # 텔레그램 한 번에 보낼 수 있는 메시지 제한(4096자) 방어
        if len(ai_text) > 4000:
            ai_text = ai_text[:3950] + "\n\n...(답변이 너무 길어 생략됨)"

        # 마크다운 파싱 에러 대비 이중 방어
        try:
            await msg.edit_text(f"🤖 <b>AI 답변:</b>\n\n{ai_text}", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await msg.edit_text(f"🤖 AI 답변:\n\n{ai_text}")

    except asyncio.TimeoutError:
        await msg.edit_text("⏳ AI 응답 시간이 초과되었습니다. 나중에 다시 시도해주세요.")
    except Exception as e:
        logger.error(f"❌ AI 답변 생성 중 오류: {e}")
        await msg.edit_text("😵 답변 생성 중 오류가 발생했습니다.")

    return ConversationHandler.END
