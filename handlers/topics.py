from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.loader import collect_all_topics_for_all_tests

TOPIC_PICK_PREFIX = "topic|"
TOPIC_CLEAR = "topic|__clear__"

def _build_topics_keyboard(topics: list[str]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, tp in enumerate(sorted(topics, key=str.lower)):
        row.append(InlineKeyboardButton(f"#{tp}", callback_data=TOPIC_PICK_PREFIX + tp))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Очистити фільтр", callback_data=TOPIC_CLEAR)])
    return InlineKeyboardMarkup(rows)

async def topics_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_topics = collect_all_topics_for_all_tests()
    if not all_topics:
        await update.message.reply_text("Поки що теми відсутні у тестах.")
        return
    kb = _build_topics_keyboard(all_topics)
    await update.message.reply_text(
        "Оберіть тему для фільтрування питань (буде застосовано у навчанні/тестуванні):",
        reply_markup=kb
    )

async def topics_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()

    if data == TOPIC_CLEAR:
        context.user_data.pop("topic_filter", None)
        await q.edit_message_text("Фільтр тем очищено. Показуються всі питання.")
        return

    if data.startswith(TOPIC_PICK_PREFIX):
        topic = data.split("|", 1)[1]
        context.user_data["topic_filter"] = topic
        await q.edit_message_text(f"Обрано тему: #{topic}\n\nТепер навчання/тестування показуватимуть питання лише з цією темою (якщо знайдуться).")
