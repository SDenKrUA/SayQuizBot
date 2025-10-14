import io
import json
from telegram import Update
from telegram.ext import ContextTypes

def _make_sample_json():
    return [
        {
            "question": "1. Sample question one?",
            "answers": [
                {"text": "Option A", "correct": False},
                {"text": "Option B", "correct": True},
                {"text": "Option C", "correct": False},
                {"text": "Option D", "correct": False}
            ]
        },
        {
            "question": "2. Sample question two?",
            "answers": [
                {"text": "Option A", "correct": False},
                {"text": "Option B", "correct": False},
                {"text": "Option C", "correct": True},
                {"text": "Option D", "correct": False}
            ]
        },
        {
            "question": "3. Sample question three?",
            "answers": [
                {"text": "Option A", "correct": True},
                {"text": "Option B", "correct": False},
                {"text": "Option C", "correct": False},
                {"text": "Option D", "correct": False}
            ]
        },
        {
            "question": "4. Sample question four?",
            "answers": [
                {"text": "Option A", "correct": False},
                {"text": "Option B", "correct": False},
                {"text": "Option C", "correct": False},
                {"text": "Option D", "correct": True}
            ]
        }
    ]

async def vip_send_template(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    payload = json.dumps(_make_sample_json(), ensure_ascii=False, indent=2)
    bio = io.BytesIO(payload.encode("utf-8"))
    bio.name = "<test>.json"
    caption = (
        "📎 Приклад файлу тесту (<test>.json).\n"
        "• JSON-масив питань\n• Кожне питання має 'question' та 'answers'\n"
        "• У варіантах хоча б один 'correct': true\n"
        "• Мінімум 4 питання"
    )
    await query.message.reply_document(document=bio, caption=caption)

async def vip_start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_vip_json"] = True
    await query.message.reply_text(
        "📤 Надішліть файл повного тесту у форматі JSON (*.json).\n"
        "Після перевірки я запитаю, куди саме його додати."
    )
