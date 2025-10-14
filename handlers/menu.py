import aiofiles
import aiofiles.os
import asyncio
import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from utils.keyboards import (
    main_menu,
    learning_range_keyboard,
    test_settings_keyboard,
    tests_menu,
    browse_menu,
    search_stop_kb,  # ⛔ додано
)
from utils.i18n import t
from utils.loader import attach_images, discover_tests_hierarchy, build_listing_for_path, discover_tests
from handlers.favorites import show_favorites_for_current_test
from utils.export_docx import export_test_to_docx, _safe_filename
from handlers.state_sync import reload_current_test_state
from utils.formatting import format_question_text  # ⛔ для форматованого виводу питань

logger = logging.getLogger("test_bot")

# ----------------------------- ДОПОМІЖНЕ -----------------------------

def _refresh_tree_and_catalog(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Примусово перечитати структуру tests/:
      - bot_data['tests_tree']  (для браузера розділів)
      - bot_data['tests_catalog'] (мапа "назва тесту -> entry")
    """
    try:
        tree = discover_tests_hierarchy("tests")
        context.bot_data["tests_tree"] = tree
    except Exception as e:
        logger.exception("[MENU] discover_tests_hierarchy failed: %s", e)

    try:
        catalog = discover_tests("tests")
        context.bot_data["tests_catalog"] = catalog
    except Exception as e:
        logger.exception("[MENU] discover_tests failed: %s", e)

# ----------------------------- ПОШУК -----------------------------

async def handle_home_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    🔎 Кнопка запускає режим пошуку.
    - Якщо тест НЕ обрано: пошук тесту по назві.
    - Якщо тест обрано: пошук у полі question в поточному тесті.
    """
    lang = context.bot_data.get("lang", "uk")
    test_name = context.user_data.get("current_test")

    # Скидаємо попередній стан пошуку і явно вказуємо новий
    context.user_data.pop("awaiting_search", None)
    context.user_data.pop("search_mode", None)

    if test_name:
        context.user_data["awaiting_search"] = "question"
        context.user_data["search_mode"] = "question"
        await update.message.reply_text(
            "🔎 Введи 6+ символів для пошуку по тексту ПИТАННЯ у вибраному тесті.\n"
            f"Тест: «{test_name}». Пошук триває доти, доки не натиснеш «⛔ Зупинити пошук питань».",
            reply_markup=None
        )
        logger.info("[SEARCH] Awaiting search by QUESTION in test=%s", test_name)
    else:
        context.user_data["awaiting_search"] = "test"
        context.user_data["search_mode"] = "test"
        await update.message.reply_text(
            "🔎 Введи 6+ символів для пошуку тесту за назвою.\n"
            "Потім натисни знайдений тест у списку.\n"
            "Пошук залишається активним, доки не зупиниш його кнопкою.",
            reply_markup=None
        )
        logger.info("[SEARCH] Awaiting search by TEST name (no test selected)")

async def stop_search_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Інлайн-кнопка «⛔ Зупинити пошук питань» — вимикає режим пошуку."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("awaiting_search", None)
    context.user_data.pop("search_mode", None)
    try:
        await query.message.reply_text("⛔ Пошук зупинено. Можна продовжувати роботу.")
    except Exception:
        pass

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробка введеного рядка пошуку. Працює тільки якщо встановлено прапор awaiting_search.
    - awaiting_search == 'test'      → пошук по назвах тестів у bot_data['tests_catalog']
    - awaiting_search == 'question'  → пошук в поточному тесті по полю 'question'
    """
    mode = context.user_data.get("awaiting_search")
    if not mode:
        return  # не наш текст — нехай обробляють інші хендлери через handle_test_selection

    query_text = (update.message.text or "").strip()
    logger.info("[SEARCH] Incoming query='%s' mode=%s", query_text, mode)

    # ⛔ Ігноруємо сам текст кнопки-тригера
    if query_text == "🔎 Пошук":
        return

    if len(query_text) < 6:
        await update.message.reply_text("✍️ Введи, будь ласка, мінімум 6 символів для пошуку.", reply_markup=search_stop_kb())
        return

    if mode == "test":
        catalog = context.bot_data.get("tests_catalog") or {}
        qlow = query_text.lower()
        matches = [name for name in catalog.keys() if qlow in name.lower()]
        logger.info("[SEARCH] Found %d test matches for '%s'", len(matches), query_text)

        if not matches:
            await update.message.reply_text("Нічого не знайдено. Спробуй інший запит.", reply_markup=search_stop_kb())
            return

        matches = matches[:30]
        # Виводимо список тестів (reply-клавіатура), режим пошуку залишається активним
        await update.message.reply_text(
            "🔎 Знайдені тести (натисни, щоб обрати):",
            reply_markup=tests_menu(matches)
        )
        # Додатково — кнопка зупинки пошуку окремим повідомленням (щоб не втратити її за клавіатурою)
        await update.message.reply_text("Коли завершиш пошук — натисни кнопку нижче \nАбо обери тест зі списку", reply_markup=search_stop_kb())
        return

    if mode == "question":
        questions = context.user_data.get("questions", [])
        if not questions:
            await update.message.reply_text("❌ У вибраному тесті немає питань.", reply_markup=search_stop_kb())
            return

        qlow = query_text.lower()
        results = []
        for idx, q in enumerate(questions):
            qtext = str(q.get("question", ""))
            if qlow in qtext.lower():
                results.append(idx)
            if len(results) >= 20:  # обмежимо до 20, щоб не спамити
                break

        logger.info("[SEARCH] Found %d question matches for '%s'", len(results), query_text)

        if not results:
            await update.message.reply_text("Нічого не знайдено у текстах питань.", reply_markup=search_stop_kb())
            return

        # Заголовок про кількість збігів
        await update.message.reply_text(f"🔎 Знайдено збігів: {len(results)}. Показую питання:")

        # Друкуємо кожне знайдене питання у форматі з жирним та відміткою правильної відповіді
        for q_index in results:
            q = questions[q_index]
            body = f"№{q_index + 1}\n\n" + format_question_text(
                q,
                highlight=None,
                hide_correct_on_wrong=False,
                show_correct_if_no_highlight=True
            )
            try:
                await update.message.reply_text(body, parse_mode="HTML", reply_markup=search_stop_kb())
            except Exception as e:
                logger.warning("[SEARCH] send question result failed: %s", e)

        # ⚠️ ВАЖЛИВО: НЕ скидаємо awaiting_search/search_mode тут!
        # Користувач може одразу вводити наступний запит.
        return

# ---------------------- СТАРІ МЕНЮ/ДІЇ ----------------------

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник головного меню"""
    # Вимикаємо режим пошуку при вході в меню
    context.user_data.pop("awaiting_search", None)
    context.user_data.pop("search_mode", None)

    lang = context.bot_data.get("lang", "uk")
    choice = update.message.text
    logger.info(f"[MAIN_MENU] chat={update.effective_chat.id} user={update.effective_user.id} choice={choice!r}")

    if choice == "➕ Додати питання":
        context.user_data["add_question"] = {"step": "question"}
        await update.message.reply_text("✍ Введи текст питання (до 1000 символів):")
        return

    if choice == "🔙 Обрати інший тест":
        logger.info("[MAIN_MENU] Show tree browser (force refresh)")
        context.user_data.clear()
        _refresh_tree_and_catalog(context)
        path = []
        context.user_data["browse_path"] = path
        subfolders, tests, _ = build_listing_for_path(context.bot_data["tests_tree"], path)
        header = "📂 Обери розділ або тест"
        if not subfolders and not tests:
            header += "\n(цей розділ порожній)"
        await update.message.reply_text(
            header,
            reply_markup=browse_menu(path, subfolders, tests)
        )
        return

    test_name = context.user_data.get("current_test")
    total_questions = context.user_data.get("total_questions", 0)

    if not test_name or total_questions == 0:
        logger.info("[MAIN_MENU] No test selected yet — prompting to choose via tree (force refresh)")
        _refresh_tree_and_catalog(context)
        path = []
        context.user_data["browse_path"] = path
        subfolders, tests, _ = build_listing_for_path(context.bot_data["tests_tree"], path)
        await update.message.reply_text(
            t(lang, "choose_test"),
            reply_markup=browse_menu(path, subfolders, tests)
        )
        return

    if choice == "🎓 Режим навчання":
        await reload_current_test_state(context)
        total_questions = context.user_data.get("total_questions", 0)

        logger.info(f"[MAIN_MENU] Go to learning for test={test_name}, total={total_questions}")
        context.user_data["mode"] = "learning"
        await update.message.reply_text(
            t(lang, "learning_pick_range", count=total_questions),
            reply_markup=learning_range_keyboard(total_questions)
        )
    elif choice == "📝 Режим тестування":
        await reload_current_test_state(context)
        total_questions = context.user_data.get("total_questions", 0)

        logger.info(f"[MAIN_MENU] Go to testing for test={test_name}, total={total_questions}")
        context.user_data["mode"] = "test"
        await update.message.reply_text(
            t(lang, "testing_pick_count", count=total_questions),
            reply_markup=test_settings_keyboard()
        )
    elif choice == "📥 Завантажити весь тест":
        logger.info(f"[MAIN_MENU] Download requested for test={test_name}")
        await handle_download_test(update, context)
    elif choice == "⭐ Улюблені":
        logger.info(f"[MAIN_MENU] Show favorites for test={test_name}")
        await show_favorites_for_current_test(update, context)

# ---------------------- DOCX ЛОГІКА ----------------------

def _find_json_for_test(test_dir: str, test_name: str) -> str | None:
    exact = os.path.join(test_dir, f"{test_name}.json")
    if os.path.exists(exact):
        return exact

    try:
        jsons = [f for f in os.listdir(test_dir) if f.lower().endswith(".json")]
    except Exception:
        return None

    if not jsons:
        return None

    low = test_name.lower()
    candidates = sorted(jsons, key=lambda n: (0 if n[:-5].lower() == low else 1, len(n)))
    return os.path.join(test_dir, candidates[0])

async def handle_download_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ЛОГІКА DOCX (без змін по суті).
    """
    lang = context.bot_data.get("lang", "uk")
    test_name = context.user_data.get("current_test")
    test_dir = context.user_data.get("current_test_dir")

    if not test_name or not test_dir:
        await update.message.reply_text("❌ Спочатку оберіть тест.", reply_markup=main_menu())
        return

    # 1) Перечитуємо JSON-и
    base_json_path = _find_json_for_test(test_dir, test_name)
    base_questions = []
    if base_json_path and os.path.exists(base_json_path):
        try:
            with open(base_json_path, "r", encoding="utf-8") as f:
                base_questions = json.load(f)
            if not isinstance(base_questions, list):
                base_questions = []
        except Exception as e:
            logger.exception(f"[DOWNLOAD] Error reading base JSON: {e}")

    custom_json_path = os.path.join(test_dir, f"{test_name} (custom).json")
    custom_questions = []
    if os.path.exists(custom_json_path):
        try:
            with open(custom_json_path, "r", encoding="utf-8") as f:
                custom_questions = json.load(f)
            if not isinstance(custom_questions, list):
                custom_questions = []
        except Exception as e:
            logger.exception(f"[DOWNLOAD] Error reading custom JSON: {e}")

    current_total = len(base_questions) + len(custom_questions)

    # 2) Шляхи до DOCX та META через safe_name
    safe_name = _safe_filename(test_name)
    docx_path = os.path.join(test_dir, f"{safe_name}.docx")
    meta_path = os.path.join(test_dir, f"{safe_name}.docx.meta.json")

    # 3) Спроба перевикористати наявний DOCX
    reused = False
    meta = None
    if os.path.exists(docx_path) and os.path.exists(meta_path):
        try:
            async with aiofiles.open(meta_path, "r", encoding="utf-8") as mf:
                meta_raw = await mf.read()
            meta = json.loads(meta_raw)
        except Exception:
            meta = None

        if meta and isinstance(meta, dict):
            prev_total = (meta.get("counts") or {}).get("total") or meta.get("question_count")
            prev_updated = meta.get("updated_at_iso") or meta.get("generated_at")
            if isinstance(prev_total, int) and prev_total == current_total:
                try:
                    caption = f"📥 Завантажено файл для тесту «{test_name}»."
                    if prev_updated:
                        caption += f"\n🕒 Останнє оновлення: {prev_updated}"
                    with open(docx_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=f,
                            filename=os.path.basename(docx_path),
                            caption=caption
                        )
                    logger.info("[DOWNLOAD] Reused existing DOCX (no regeneration needed)")
                    reused = True
                except Exception as e:
                    logger.exception(f"[DOWNLOAD] Error sending existing DOCX: {e}")

    # 4) Якщо не вийшло перевикористати — генеруємо
    if not reused:
        loop = asyncio.get_event_loop()
        images_dir_base = os.path.join(test_dir, test_name)
        images_dir_custom = os.path.join(test_dir, f"{test_name} (custom)")

        try:
            base_questions = await loop.run_in_executor(None, attach_images, base_questions, images_dir_base)
        except Exception as e:
            logger.warning(f"[DOWNLOAD] attach_images (base) failed: {e}")

        try:
            custom_questions = await loop.run_in_executor(None, attach_images, custom_questions, images_dir_custom)
        except Exception as e:
            logger.warning(f"[DOWNLOAD] attach_images (custom) failed: {e}")

        questions = (base_questions or []) + (custom_questions or [])
        if not questions:
            await update.message.reply_text(
                t(lang, "download_not_found", test=test_name) if callable(t) else f"❌ Не знайшов питання для «{test_name}».",
                reply_markup=main_menu()
            )
            return

        try:
            docx_path, regenerated = await loop.run_in_executor(
                None, export_test_to_docx, test_name, questions, test_dir
            )
            logger.info(f"[DOWNLOAD] DOCX ready: {docx_path} regenerated={regenerated}")
        except Exception as e:
            logger.exception(f"[DOWNLOAD] Export failed: {e}")
            await update.message.reply_text(
                t(lang, "download_error", test=test_name, error=str(e)) if callable(t) else "❌ Не вдалося згенерувати файл.",
                reply_markup=main_menu()
            )
            return

        # Оновлюємо метадані
        try:
            meta = {
                "test_name": test_name,
                "docx_path": docx_path,
                "updated_at_iso": datetime.now().isoformat(timespec="seconds"),
                "regenerated": True,
                "sources": {
                    "base_json": base_json_path,
                    "custom_json": custom_json_path if os.path.exists(custom_json_path) else None
                },
                "counts": {
                    "base": len(base_questions or []),
                    "custom": len(custom_questions or []),
                    "total": len(questions or [])
                }
            }
            async with aiofiles.open(meta_path, "w", encoding="utf-8") as mf:
                await mf.write(json.dumps(meta, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"[DOWNLOAD] Meta write failed: {e}")

        caption = f"📥 Завантажено файл для тесту «{test_name}»."
        if meta and meta.get("updated_at_iso"):
            caption += f"\n🕒 Останнє оновлення: {meta['updated_at_iso']}"

        try:
            with open(docx_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=os.path.basename(docx_path),
                    caption=caption
                )
            logger.info("[DOWNLOAD] Sent regenerated DOCX successfully")
        except FileNotFoundError:
            logger.error(f"[DOWNLOAD] File not found after export: {docx_path}")
            await update.message.reply_text(
                t(lang, "download_not_found", test=test_name) if callable(t) else "❌ Файл не знайдено.",
                reply_markup=main_menu()
            )
            return
        except Exception as e:
            logger.exception(f"[DOWNLOAD] Error sending file: {e}")
            await update.message.reply_text(
                t(lang, "download_error", test=test_name, error=str(e)) if callable(t) else "❌ Не вдалося надіслати файл.",
                reply_markup=main_menu()
            )
            return

        # RAM sync після генерації
        context.user_data["questions"] = questions
        context.user_data["total_questions"] = len(questions)
    else:
        # Якщо перевикористали — теж синхронізуємо RAM зі свіжими JSON
        await reload_current_test_state(context)

# (Для сумісності) — відкриття питання з пошуку
async def open_question_from_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = (query.data or "").split("|")
    if len(data) != 2 or data[0] != "openq":
        return

    try:
        q_index = int(data[1])
    except ValueError:
        return

    questions = context.user_data.get("questions", [])
    if not questions or q_index < 0 or q_index >= len(questions):
        await query.answer("❌ Питання не знайдено.", show_alert=True)
        return

    context.user_data["mode"] = "learning"
    context.user_data["order"] = [q_index]
    context.user_data["step"] = 0
    context.user_data["score"] = 0
    context.user_data["wrong_pairs"] = []
    context.user_data["current_streak"] = 0
    context.user_data["start_time"] = datetime.now()

    from handlers.learning import send_current_question
    await query.message.reply_text("📌 Відкриваю знайдене питання…")
    await send_current_question(query.message.chat_id, context)
