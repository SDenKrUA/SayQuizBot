import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from utils.keyboards import tests_menu, main_menu, browse_menu, add_cancel_kb
from utils.i18n import t
from utils.loader import attach_images, discover_tests_hierarchy, build_listing_for_path, discover_tests
from handlers.statistics_db import get_user_favorites_by_test

logger = logging.getLogger("test_bot")

ILLEGAL_WIN_CHARS = set('<>:"/\\|?*')

# ---- helpers: sanitizers ----

def _sanitize_folder_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if any(ch in ILLEGAL_WIN_CHARS for ch in name):
        return ""
    # не дозволяємо іконки/кнопки як назви
    if name.startswith("📁 ") or name.startswith("➕ "):
        return ""
    if name in _RESERVED_INPUTS:
        return ""
    return name

def _sanitize_test_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if any(ch in ILLEGAL_WIN_CHARS for ch in name):
        return ""
    # не дозволяємо іконки/кнопки як назви
    if name.startswith("📁 ") or name.startswith("➕ "):
        return ""
    if name in _RESERVED_INPUTS:
        return ""
    return name

def _is_reserved_input(text: str) -> bool:
    if not text:
        return True
    # Будь-яка «папка» або «кнопка додавання»
    if text.startswith("📁 ") or text.startswith("➕ "):
        return True
    return text in _RESERVED_INPUTS

# Кнопки/рядки, які НІКОЛИ не приймаємо як назву
_RESERVED_INPUTS = {
    "🔎 Пошук",
    "👤 Мій кабінет",
    "🔙 Обрати інший тест",
    "📥 Завантажити весь тест",
    "🎓 Режим навчання",
    "📝 Режим тестування",
    "📊 Моя статистика",
    "❓ Допомога",
    "⭐ Улюблені",
    "🎓 Навчання з улюблених",
    "📝 Тест з улюблених",
    "➕ Додати розділ",
    "➕ Додати тест",
    "⬅️ Назад",
    "🔙 Назад",
}

# ---- refresh & tree helpers ----

async def _refresh_catalogs(context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["tests_catalog"] = discover_tests("tests")
    context.bot_data["tests_tree"] = discover_tests_hierarchy("tests")

async def _send_browse_node_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Відправити повідомлення з поточним вузлом дерева за user_data['browse_path']"""
    tree = context.bot_data.get("tests_tree")
    if not tree:
        tree = discover_tests_hierarchy("tests")
        context.bot_data["tests_tree"] = tree

    path = context.user_data.get("browse_path", [])
    subfolders, tests, _ = build_listing_for_path(tree, path)
    header = "📂 Оберіть розділ або тест"
    if not subfolders and not tests:
        header += "\n(цей розділ порожній)"
    await context.bot.send_message(
        chat_id=chat_id,
        text=header,
        reply_markup=browse_menu(path, subfolders, tests)
    )

async def _show_browse_node(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показати вміст поточного вузла дерева за user_data['browse_path'] (для текстових апдейтів)"""
    tree = context.bot_data.get("tests_tree")
    if not tree:
        tree = discover_tests_hierarchy("tests")
        context.bot_data["tests_tree"] = tree

    path = context.user_data.get("browse_path", [])
    subfolders, tests, _ = build_listing_for_path(tree, path)
    header = "📂 Оберіть розділ або тест"
    if not subfolders and not tests:
        header += "\n(цей розділ порожній)"
    await update.message.reply_text(
        header,
        reply_markup=browse_menu(path, subfolders, tests)
    )

# ---- main handler ----

async def handle_test_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Одноразовий запобіжник від «подвійних» відповідей, якщо інший хендлер уже відповів
    if context.user_data.pop("suppress_test_select_once", False):
        logger.info("[TEST_SELECT] Suppressed once by upstream handler for text=%r", (update.message.text or "").strip())
        return

    lang = context.bot_data.get("lang", "uk")
    text = (update.message.text or "").strip()
    catalog = context.bot_data.get("tests_catalog", {})

    # 🔒 Якщо користувач перебуває у "Моєму кабінеті" — НЕ перехоплюємо його повідомлення тут.
    if context.user_data.get("in_office"):
        logger.info("[TEST_SELECT] Ignored because user is in 'office' mode: %r", text)
        return

    add_question_active = context.user_data.get("add_question_active", False)
    awaiting_comment = context.user_data.get("awaiting_comment", False)
    mode = context.user_data.get("mode")
    awaiting_search = context.user_data.get("awaiting_search")  # 🔎

    logger.info(
        f"[TEST_SELECT] chat={update.effective_chat.id} user={update.effective_user.id} "
        f"text='{text}' add_question_active={add_question_active} "
        f"awaiting_comment={awaiting_comment} mode={mode} catalog_keys={list(catalog.keys())}"
    )

    # Якщо майстер додавання питання активний — не чіпаємо
    if add_question_active:
        logger.info("[TEST_SELECT] Skipped due to active flow (add_question)")
        return

    # Якщо зараз користувач пише коментар — НЕ перехоплюємо текст
    if awaiting_comment:
        from handlers.comments import handle_comment_flow
        logger.info(f"[TEST_SELECT] Forwarding to handle_comment_flow: '{text}'")
        await handle_comment_flow(update, context)
        return

    # 🔎 Якщо очікується пошук — не заважаємо
    if awaiting_search:
        logger.info("[TEST_SELECT] awaiting_search=%s", awaiting_search)
        if text == "🔎 Пошук":
            logger.info("[TEST_SELECT] Ignoring trigger button text during search mode")
            return
        if awaiting_search == "test" and text in catalog:
            logger.info("[TEST_SELECT] Selecting test from search: %s", text)
            context.user_data.pop("awaiting_search", None)
            context.user_data.pop("search_mode", None)
        else:
            from handlers.menu import handle_search_query
            await handle_search_query(update, context)
            return

    # Якщо користувач у режимі навчання/тестування — ігноруємо
    if mode in ["learning", "test"]:
        logger.info(f"[TEST_SELECT] Ignored input during {mode} mode: '{text}'")
        return

    # Команди меню — ігноруємо тут (їх обробляють свої хендлери у group=1)
    menu_commands = [
        "🔎 Пошук",
        "👤 Мій кабінет",
        "🔙 Обрати інший тест",
        "📥 Завантажити весь тест",
        "🎓 Режим навчання",
        "📝 Режим тестування",
        "📊 Моя статистика",
        "❓ Допомога",
        "➕ Додати питання",
        "⭐ Улюблені",
        "🎓 Навчання з улюблених",
        "📝 Тест з улюблених",
    ]
    if text in menu_commands:
        logger.info(f"[TEST_SELECT] Ignored menu command: '{text}'")
        return

    # ==== Навігація папками ====
    if "browse_path" not in context.user_data:
        context.user_data["browse_path"] = []
    path = context.user_data["browse_path"]

    # --- Додавання розділу ---
    if text == "➕ Додати розділ":
        context.user_data["awaiting_new_folder"] = True
        # якщо раптом чекали назву тесту — скасовуємо той режим
        context.user_data.pop("awaiting_new_test", None)
        await update.message.reply_text(
            "🗂 Введіть назву нового розділу (папки), або натисніть «⬅️ Назад» щоб скасувати:",
            reply_markup=add_cancel_kb("folder")
        )
        return

    if context.user_data.get("awaiting_new_folder"):
        # дозволяємо скасування назад
        if text in {"⬅️ Назад", "🔙 Назад"}:
            context.user_data.pop("awaiting_new_folder", None)
            await _show_browse_node(update, context)
            return

        # не приймаємо службові/зарезервовані рядки
        if _is_reserved_input(text):
            await update.message.reply_text("⚠️ Це не назва. Введіть текстову назву нового розділу, або натисніть «⬅️ Назад».")
            return

        name = _sanitize_folder_name(text)
        if not name:
            await update.message.reply_text("❌ Невірна назва. Заборонені символи: <>:\"/\\|?*\nВведіть іншу, або «⬅️ Назад».")
        else:
            tree = context.bot_data.get("tests_tree") or discover_tests_hierarchy("tests")
            subfolders, tests, abs_dir = build_listing_for_path(tree, path)
            try:
                os.makedirs(os.path.join(abs_dir, name), exist_ok=False)
                await update.message.reply_text(f"✅ Розділ «{name}» створено.")
                await _refresh_catalogs(context)
            except FileExistsError:
                await update.message.reply_text("ℹ️ Така папка вже існує.")
        context.user_data.pop("awaiting_new_folder", None)
        await _show_browse_node(update, context)
        return

    # --- Додавання тесту ---
    if text == "➕ Додати тест":
        context.user_data["awaiting_new_test"] = True
        # якщо раптом чекали назву папки — скасовуємо той режим
        context.user_data.pop("awaiting_new_folder", None)
        await update.message.reply_text(
            "📄 Введіть назву нового тесту, або натисніть «⬅️ Назад» щоб скасувати:",
            reply_markup=add_cancel_kb("test")
        )
        return

    if context.user_data.get("awaiting_new_test"):
        if text in {"⬅️ Назад", "🔙 Назад"}:
            context.user_data.pop("awaiting_new_test", None)
            await _show_browse_node(update, context)
            return

        if _is_reserved_input(text):
            await update.message.reply_text("⚠️ Це не назва тесту. Введіть текстову назву, або натисніть «⬅️ Назад».")
            return

        name = _sanitize_test_name(text)
        if not name:
            await update.message.reply_text("❌ Невірна назва. Заборонені символи: <>:\"/\\|?*\nВведіть іншу, або «⬅️ Назад».")
        else:
            tree = context.bot_data.get("tests_tree") or discover_tests_hierarchy("tests")
            subfolders, tests, abs_dir = build_listing_for_path(tree, path)
            file_path = os.path.join(abs_dir, f"{name} (custom).json")
            if os.path.exists(file_path):
                await update.message.reply_text("ℹ️ Такий тест уже існує в цьому розділі.")
            else:
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write("[]")
                    await update.message.reply_text(f"✅ Створено порожній тест «{name} (custom)».")
                    await _refresh_catalogs(context)
                except Exception as e:
                    await update.message.reply_text(f"❌ Не вдалося створити файл: {e}")
        context.user_data.pop("awaiting_new_test", None)
        await _show_browse_node(update, context)
        return

    # Клік по папці
    if text.startswith("📁 "):
        folder = text[2:].strip()
        path.append(folder)
        context.user_data["browse_path"] = path
        await _show_browse_node(update, context)
        return

    # Назад вгору (приймаємо і ⬅️, і 🔙)
    if text in {"⬅️ Назад", "🔙 Назад"}:
        if path:
            path.pop()
        context.user_data["browse_path"] = path
        await _show_browse_node(update, context)
        return

    # ==== Вибір тесту ====
    if text not in catalog:
        logger.warning(f"[TEST_SELECT] Not a test/folder item: '{text}'")
        await _show_browse_node(update, context)
        return

    entry = catalog[text]

    # Завантажуємо зображення (як і було)
    try:
        logger.info(f"[TEST_SELECT] Loading images for test: {text}")
        loop = asyncio.get_event_loop()
        questions = await loop.run_in_executor(None, attach_images, entry["questions"], entry.get("images_dir"))
        logger.info(f"[TEST_SELECT] Images attached: {len(questions)} questions")
    except Exception as e:
        logger.error(f"[TEST_SELECT] Error attaching images: {e}")
        questions = entry["questions"]

    context.user_data["current_test"] = text
    context.user_data["current_test_dir"] = entry.get("dir")
    context.user_data["questions"] = questions
    context.user_data["total_questions"] = entry["total"]

    # скидаємо можливі флаги пошуку/створення
    for k in ("awaiting_search", "search_mode", "awaiting_new_folder", "awaiting_new_test"):
        context.user_data.pop(k, None)

    if "stats" not in context.user_data:
        context.user_data["stats"] = {
            "total_answered": 0,
            "correct_answers": 0,
            "best_streak": 0
        }

    # Попередньо підготуємо набір улюблених для цього тесту
    try:
        rows = await get_user_favorites_by_test(update.effective_user.id, text, limit=10000)
        context.user_data["fav_set"] = {r["q_index"] for r in rows}
    except Exception:
        context.user_data["fav_set"] = set()

    logger.info(f"[TEST_SELECT] Selected: {text}, total={len(questions)}")

    await update.message.reply_text(
        t(lang, "test_selected", test=text, count=len(questions)),
        reply_markup=main_menu()
    )

# ---- Нове: callback для інлайн «❎ Скасувати» ----

async def add_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Скасування режимів додавання розділу/тесту через інлайн-кнопку.
    """
    query = update.callback_query
    await query.answer()
    data = (query.data or "").split("|", 1)
    kind = data[1] if len(data) == 2 else ""

    if kind == "folder":
        context.user_data.pop("awaiting_new_folder", None)
    elif kind == "test":
        context.user_data.pop("awaiting_new_test", None)
    else:
        # Невідомий тип — просто нічого не робимо
        pass

    # Повідомимо та повернемося до поточного вузла дерева
    try:
        await query.edit_message_text("❎ Додавання скасовано.")
    except Exception:
        # Якщо не вдалося відредагувати (наприклад, це не наше повідомлення) — відповімо окремим
        await context.bot.send_message(chat_id=query.message.chat_id, text="❎ Додавання скасовано.")

    await _send_browse_node_message(context, chat_id=query.message.chat_id)
