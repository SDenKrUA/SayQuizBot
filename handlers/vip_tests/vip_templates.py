import io
import json
from telegram import Update
from telegram.ext import ContextTypes

def _make_sample_json():
    """
    Повертає приклад валідного тесту у НОВОМУ форматі:
    - кожне питання має поля: question, answers (масив із text/correct),
      а також ДОДАТКОВО: topics (масив хештегів або порожній) і explanation (рядок або порожній).
    - приклади охоплюють: кілька хештегів, один хештег, без хештегів; з поясненням і без пояснення.
    """
    return [
        {
            "question": "1. Under ISM, what is a \"non-conformity\"?",
            "answers": [
                {"text": "Official log book entries not being completed correctly", "correct": False},
                {"text": "A safety officer not being nominated for the vessel", "correct": False},
                {"text": "The wearing of non-standard Personal protective equipment", "correct": False},
                {"text": "An observed situation where objective evidence indicates the non-fulfilment of a specified requirement", "correct": True}
            ],
            "topics": ["#ISM", "#Safety", "#Audit"],
            "explanation": "ISM Code defines a non-conformity as an observed situation where objective evidence indicates the non-fulfilment of a specified requirement."
        },
        {
            "question": "2. Every inflatable liferaft, inflatable lifejacket and hydrostatic release units shall be serviced:",
            "answers": [
                {"text": "Every 36 months.", "correct": False},
                {"text": "Every 18 months.", "correct": False},
                {"text": "Every 24 months.", "correct": False},
                {"text": "Every 12 months.", "correct": True}
            ],
            "topics": ["#SOLAS"],  # один хештег
            "explanation": ""       # без пояснення
        },
        {
            "question": "3. What is the primary purpose of a cargo tank inerting system on a chemical/oil tanker?",
            "answers": [
                {"text": "To reduce oxygen concentration below the flammable limit", "correct": True},
                {"text": "To increase the cargo temperature for faster discharge", "correct": False},
                {"text": "To neutralize toxic vapors by chemical reaction", "correct": False},
                {"text": "To dry the cargo tanks after washing", "correct": False}
            ],
            "topics": [],  # без хештегів
            "explanation": "Inert gas keeps oxygen content typically below 8%, preventing formation of a flammable atmosphere."
        },
        {
            "question": "4. Which action is MOST appropriate if you suspect a small electrical fire in the engine control room?",
            "answers": [
                {"text": "Use a CO₂ or dry powder extinguisher after isolating the power", "correct": True},
                {"text": "Spray water directly onto the panel to cool it down", "correct": False},
                {"text": "Open all doors to ventilate the smoke immediately", "correct": False},
                {"text": "Ignore the alarm until the chief engineer arrives", "correct": False}
            ],
            "topics": ["#Firefighting", "#Engine"],  # кілька хештегів
            "explanation": ""  # без пояснення
        }
    ]

async def vip_send_template(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Надсилає користувачу файл-шаблон <test>.json у НОВОМУ форматі з полями topics та explanation.
    """
    query = update.callback_query
    await query.answer()
    payload = json.dumps(_make_sample_json(), ensure_ascii=False, indent=2)
    bio = io.BytesIO(payload.encode("utf-8"))
    bio.name = "<test>.json"
    caption = (
        "📎 Приклад файлу тесту (<test>.json) — НОВИЙ формат із темами та поясненнями.\n"
        "• JSON-масив із 4+ питань\n"
        "• Поля: 'question', 'answers' (кожна відповідь має 'text' і 'correct')\n"
        "• Додатково: 'topics' — масив хештегів (може бути порожній/1/декілька), "
        "'explanation' — пояснення (може бути порожнім)\n"
        "• У кожному питанні щонайменше одна відповідь з 'correct': true\n"
        "• Збережіть файл з назвою вашого тесту, наприклад My Test.json"
    )
    await query.message.reply_document(document=bio, caption=caption)

async def vip_start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_vip_json"] = True
    await query.message.reply_text(
        "📤 Надішліть файл повного тесту у форматі JSON (*.json) у НОВОМУ форматі (з 'topics' та 'explanation').\n"
        "Після перевірки я запитаю, куди саме його додати."
    )
