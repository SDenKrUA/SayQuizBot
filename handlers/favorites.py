from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from utils.keyboards import (
    build_options_markup,
    main_menu,
    favorites_clear_inline_kb,
    favorites_clear_confirm_kb,
)
from handlers.statistics_db import (
    save_favorite_db,
    delete_favorite_db,
    get_user_favorites_by_test,
    get_favorite_counts_by_test,
    delete_all_favorites,
)
from handlers.comments import get_comments_count
from utils.i18n import t

# --- Inline toggle (callback fav|<q_index>) ---
async def favorite_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Тогл улюбленого для поточного питання.
    Після зміни стану – оновлюємо лише розмітку (reply_markup) повідомлення з питанням.
    """
    query = update.callback_query
    data = (query.data or "").split("|")
    await query.answer()  # короткий toast

    if len(data) != 2:
        await query.answer("⚠️ Невірні дані.", show_alert=False)
        return

    try:
        q_index = int(data[1])
    except ValueError:
        await query.answer("⚠️ Невірний індекс.", show_alert=False)
        return

    test_name = context.user_data.get("current_test", "unknown")
    test_dir = context.user_data.get("current_test_dir")
    questions = context.user_data.get("questions", [])
    if q_index >= len(questions):
        await query.answer("❌ Питання не знайдено.", show_alert=True)
        return

    q = questions[q_index]
    user = query.from_user

    # Локальний кеш улюблених для швидкого доступу
    fav_set = context.user_data.get("fav_set")
    if fav_set is None:
        rows = await get_user_favorites_by_test(user.id, test_name, limit=10000)
        fav_set = {r["q_index"] for r in rows}
        context.user_data["fav_set"] = fav_set

    # Тогл
    if q_index in fav_set:
        await delete_favorite_db(user_id=user.id, test_name=test_name, q_index=q_index)
        fav_set.discard(q_index)
        await query.answer("⭐ Видалено з улюблених", show_alert=False)
    else:
        await save_favorite_db(
            user_id=user.id,
            username=user.username,
            test_name=test_name,
            q_index=q_index,
            question_text=q.get("question", "")
        )
        fav_set.add(q_index)
        await query.answer("⭐ Додано до улюблених", show_alert=False)

    # Актуальний лічильник коментарів, щоб не скидало на (0)
    try:
        comments_count = await get_comments_count(test_name, q_index, test_dir)
    except Exception:
        comments_count = 0

    try:
        markup = build_options_markup(
            q_index=q_index,
            highlight=True,
            is_favorited=(q_index in fav_set),
            comments_count=comments_count
        )
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception:
        pass


# --- /favorites: зведення по тестах ---
async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /favorites — показати зведену кількість улюблених по кожному тесту.
    Під повідомленням додаємо інлайн-кнопку «Очистити всі Улюблені».
    """
    user_id = update.effective_user.id
    lang = context.bot_data.get("lang", "uk")
    counts = await get_favorite_counts_by_test(user_id)

    if not counts:
        await update.message.reply_text(t(lang, "favorites_empty"))
        return

    text_lines = [t(lang, "favorites_list_title")]
    for row in counts:
        test = row["test_name"]
        cnt = row["count"]
        noun = "питання" if (cnt % 10 in (2,3,4) and cnt % 100 not in (12,13,14)) else "питань" if cnt != 1 else "питання"
        text_lines.append(f"{test} — {cnt} {noun}")

    # Надсилаємо з інлайн-кнопкою очищення
    await update.message.reply_text("\n".join(text_lines), reply_markup=favorites_clear_inline_kb())


# --- '⭐ Улюблені' в меню поточного тесту ---
async def show_favorites_for_current_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показати варіанти режимів по улюблених питаннях поточного тесту:
    - 🎓 Навчання з улюблених
    - 📝 Тест з улюблених
    """
    user_id = update.effective_user.id
    test_name = context.user_data.get("current_test")

    if not test_name:
        await update.message.reply_text("❌ Спочатку обери тест зі списку.")
        return

    rows = await get_user_favorites_by_test(user_id, test_name, limit=10000)
    fav_indices = sorted({r["q_index"] for r in rows})

    if not fav_indices:
        await update.message.reply_text(f"ℹ️ У тебе ще немає улюблених питань у тесті «{test_name}».")
        return

    # Збережемо набір у user_data для швидкого доступу та відображення ✅
    context.user_data["fav_set"] = set(fav_indices)

    kb = ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎓 Навчання з улюблених"), KeyboardButton("📝 Тест з улюблених")],
            [KeyboardButton("🔙 Назад")]
        ],
        resize_keyboard=True
    )
    await update.message.reply_text(
        f"⭐ Улюблені для «{test_name}»: {len(fav_indices)}",
        reply_markup=kb
    )


# --- Старт навчання тільки по улюблених ---
async def start_favorites_learning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запускає навчання тільки по улюблених питаннях поточного тесту (у порядку зростання індексів).
    """
    user_id = update.effective_user.id
    test_name = context.user_data.get("current_test")
    questions = context.user_data.get("questions", [])
    if not test_name or not questions:
        await update.message.reply_text("❌ Спочатку обери тест зі списку.", reply_markup=main_menu())
        return

    rows = await get_user_favorites_by_test(user_id, test_name, limit=10000)
    fav_indices = sorted({r["q_index"] for r in rows})
    if not fav_indices:
        await update.message.reply_text("ℹ️ Немає улюблених для цього тесту.", reply_markup=main_menu())
        return

    # Стан сесії навчання
    context.user_data["mode"] = "learning"
    context.user_data["order"] = fav_indices
    context.user_data["step"] = 0
    context.user_data["score"] = 0
    context.user_data["wrong_pairs"] = []
    context.user_data["current_streak"] = 0

    # ВАЖЛИВО: скидаємо “живе” повідомлення, щоб надсилати НОВЕ, а не редагувати старе
    context.user_data.pop("question_chat_id", None)
    context.user_data.pop("question_message_id", None)

    from handlers.learning import send_current_question
    await update.message.reply_text("🎓 Починаємо навчання по улюблених!", reply_markup=None)
    await send_current_question(update.effective_chat.id, context)


# --- Старт тесту тільки по улюблених ---
async def start_favorites_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запускає тест тільки по улюблених питаннях поточного тесту (випадковий порядок).
    """
    import random

    user_id = update.effective_user.id
    test_name = context.user_data.get("current_test")
    questions = context.user_data.get("questions", [])
    if not test_name or not questions:
        await update.message.reply_text("❌ Спочатку обери тест зі списку.", reply_markup=main_menu())
        return

    rows = await get_user_favorites_by_test(user_id, test_name, limit=10000)
    fav_indices = list({r["q_index"] for r in rows})
    if not fav_indices:
        await update.message.reply_text("ℹ️ Немає улюблених для цього тесту.", reply_markup=main_menu())
        return

    random.shuffle(fav_indices)

    # Стан сесії тесту
    context.user_data["mode"] = "test"
    context.user_data["order"] = fav_indices
    context.user_data["step"] = 0
    context.user_data["score"] = 0
    context.user_data["wrong_pairs"] = []
    context.user_data["current_streak"] = 0

    from datetime import datetime
    context.user_data["start_time"] = datetime.now()

    # ВАЖЛИВО: скидаємо “живе” повідомлення, щоб надсилати НОВЕ, а не редагувати старе
    context.user_data.pop("question_chat_id", None)
    context.user_data.pop("question_message_id", None)

    lang = context.bot_data.get("lang", "uk")
    await update.message.reply_text(
        t(lang, "testing_start", test=test_name, count=len(fav_indices)),
        reply_markup=None
    )

    # 🔧 ФІКС: використовуємо рендер тестового питання з handlers.testing
    from handlers.testing import _show_question
    await _show_question(update, context, fav_indices[0])


# === Нове: очищення всіх улюблених через інлайн-кнопку ===
async def clear_all_favorites_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Почати процес очищення — показати підтвердження."""
    query = update.callback_query
    await query.answer()
    lang = context.bot_data.get("lang", "uk")
    await query.message.reply_text(t(lang, "favorites_clear_prompt"), reply_markup=favorites_clear_confirm_kb())

async def clear_all_favorites_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Підтвердження очищення."""
    query = update.callback_query
    await query.answer()
    lang = context.bot_data.get("lang", "uk")

    data = (query.data or "").split("|")
    choice = data[1] if len(data) > 1 else "no"

    if choice == "yes":
        user_id = query.from_user.id
        n = await delete_all_favorites(user_id)
        # очистимо локальний кеш, якщо був
        if "fav_set" in context.user_data:
            context.user_data["fav_set"].clear()
        await query.message.reply_text(t(lang, "favorites_cleared", n=n))
    else:
        await query.message.reply_text(t(lang, "favorites_clear_cancel"))
