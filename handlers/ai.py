# handlers/ai.py
import logging
from enum import IntEnum
from telegram import Update

# [수정] ChatAction 경로 수정
from telegram.constants import ChatAction
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
        "🤖 AI에게 무엇이든 물어보세요!\n"
        "질문을 입력해주세요.\n\n"
        "취소하려면 /cancel 을 입력하세요."
    )
    return AskAIStates.WAITING_QUESTION


async def ask_ai_question_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    question = update.message.text
    ai_model = context.bot_data.get("ai_model")

    if not ai_model:
        await update.message.reply_text(
            "⚠️ AI 모델이 설정되지 않았거나 로드 실패했습니다."
        )
        return ConversationHandler.END

    msg = await update.message.reply_text("🤖 AI가 답변을 생각 중입니다... 🤔")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    try:
        response = await ai_model.generate_content_async(question)
        ai_text = response.text

        if len(ai_text) > 4000:
            ai_text = ai_text[:4000] + "...\n(답변이 너무 깁니다)"

        await msg.edit_text(f"🤖 <b>AI 답변:</b>\n\n{ai_text}", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"AI 답변 생성 중 오류: {e}", exc_info=True)
        await msg.edit_text("😵 AI 답변 생성 중 오류가 발생했습니다.")

    return ConversationHandler.END
