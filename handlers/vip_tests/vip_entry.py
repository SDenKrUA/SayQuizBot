import os
import logging
from typing import List, Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_storage import _load_owners
from .vip_constants import TESTS_ROOT
from utils.loader import discover_tests, attach_images
from utils.keyboards import main_menu
from utils.i18n import t

logger = logging.getLogger("test_bot.vip")

async def office_my_tests_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показує список тестів, де current_user є owner у tests/_owners.json.
    Кнопки: Шаблон / Завантажити / ⚙️ Редагувати / 🗑 Видалити / ➡️ Перейти до тесту.
    """
    user_id = update.effective_user.id
    owners = _load_owners()

    my_items: List[Dict[str, Any]] = []
    for rel, meta in owners.items():
        if isinstance(meta, dict) and meta.get("owner_id") == user_id:
            name = os.path.splitext(os.path.basename(rel))[0]
            abs_path = os.path.join(TESTS_ROOT, rel)
            abs_dir = os.path.dirname(abs_path)
            my_items.append({
                "name": name,
                "rel": rel,
                "abs_path": abs_path,
                "abs_dir": abs_dir,
            })

    my_items.sort(key=lambda x: x["name"].lower())
    context.user_data["vip_mytests"] = my_items

    if not my_items:
        text = (
            "🗂 У вас ще немає завантажених повних тестів.\n\n"
            "• «Завантажити повний» — надішліть файл <test>.json у правильній структурі.\n"
            "• «Шаблон для тесту» — отримаєте приклад на 4 питання."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Завантажити повний", callback_data="vip_upload_full")],
            [InlineKeyboardButton("📎 Шаблон для тесту", callback_data="vip_template")],
        ])
        await update.message.reply_text(text, reply_markup=kb)
        return

    listing = "\n".join(f"• {it['name']}  —  /{it['rel']}" for it in my_items)
    rows = [
        [InlineKeyboardButton("📤 Завантажити повний", callback_data="vip_upload_full")],
        [InlineKeyboardButton("📎 Шаблон для тесту", callback_data="vip_template")],
    ]
    for idx, it in enumerate(my_items):
        rows.append([
            InlineKeyboardButton(f"⚙️ Редагувати: {it['name']}", callback_data=f"vip_edit|{idx}"),
            InlineKeyboardButton(f"🗑 {it['name']}", callback_data=f"vip_delete|{idx}"),
        ])
        rows.append([
            InlineKeyboardButton("➡️ Перейти до тесту", callback_data=f"vip_go|{idx}")
        ])

    await update.message.reply_text(
        "🗂 Ваші тести (VIP):\n" + listing + "\n\nОберіть дію нижче:",
        reply_markup=InlineKeyboardMarkup(rows)
    )

async def office_shared_tests_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Список тестів, де current_user має підтверджений доступ як довірений.
    Доступні дії: ⚙️ Редагувати / 🗑 Видалити / ➡️ Перейти до тесту.
    (Керування довіреними приховане для не-власників у vip_edit_menu.)
    """
    user_id = update.effective_user.id
    username = (update.effective_user.username or "").strip()
    uname_lower = username.lower() if username else None

    owners = _load_owners()

    shared_items: List[Dict[str, Any]] = []
    for rel, meta in owners.items():
        if not isinstance(meta, dict):
            continue
        # чи є user довіреним?
        is_trusted = False
        try:
            ids = meta.get("trusted") or []
            unames = meta.get("trusted_usernames") or []
            if user_id and user_id in ids:
                is_trusted = True
            elif uname_lower and any(u.lower() == uname_lower for u in unames):
                is_trusted = True
        except Exception:
            is_trusted = False

        if not is_trusted:
            continue

        name = os.path.splitext(os.path.basename(rel))[0]
        abs_path = os.path.join(TESTS_ROOT, rel)
        abs_dir = os.path.dirname(abs_path)
        shared_items.append({
            "name": name,
            "rel": rel,
            "abs_path": abs_path,
            "abs_dir": abs_dir,
        })

    shared_items.sort(key=lambda x: x["name"].lower())
    context.user_data["vip_mytests"] = shared_items  # переюзаємо той самий масив/індекси для vip_edit/vip_delete/vip_go

    if not shared_items:
        await update.message.reply_text("🤝 У вас поки немає підтверджених доступів до чужих тестів.")
        return

    listing = "\n".join(f"• {it['name']}  —  /{it['rel']}" for it in shared_items)
    rows = []
    for idx, it in enumerate(shared_items):
        rows.append([
            InlineKeyboardButton(f"⚙️ Редагувати: {it['name']}", callback_data=f"vip_edit|{idx}"),
            InlineKeyboardButton(f"🗑 {it['name']}", callback_data=f"vip_delete|{idx}"),
        ])
        rows.append([
            InlineKeyboardButton("➡️ Перейти до тесту", callback_data=f"vip_go|{idx}")
        ])

    await update.message.reply_text(
        "🤝 Спільні тести (доступ надано власниками):\n" + listing + "\n\nОберіть дію нижче:",
        reply_markup=InlineKeyboardMarkup(rows)
    )

async def vip_go_to_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обробник '➡️ Перейти до тесту' з екрана Мої/Спільні тести.
    Встановлює поточний тест і відкриває головне меню режимів.
    """
    query = update.callback_query
    await query.answer()

    idx_str = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    try:
        idx = int(idx_str)
    except ValueError:
        return

    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await query.message.reply_text("❌ Тест не знайдено.")
        return

    item = items[idx]
    test_name = item["name"]
    test_dir = item["abs_dir"]

    # Оновлюємо каталог і беремо запис про тест
    try:
        context.bot_data["tests_catalog"] = discover_tests("tests")
        entry = (context.bot_data.get("tests_catalog") or {}).get(test_name)
    except Exception as e:
        logger.exception("discover_tests failed: %s", e)
        entry = None

    questions = []
    if entry:
        # Підв'язуємо зображення, якщо є
        try:
            questions = attach_images(entry["questions"], entry.get("images_dir"))
        except Exception as e:
            logger.warning("attach_images failed: %s", e)
            questions = entry["questions"] or []
    else:
        # Фолбек: спробуємо прочитати JSON напряму
        json_path = os.path.join(test_dir, f"{test_name}.json")
        try:
            import json
            with open(json_path, "r", encoding="utf-8") as f:
                questions = json.load(f)
        except Exception as e:
            logger.error("Failed to load test JSON directly: %s", e)
            await query.message.reply_text("❌ Не вдалося відкрити тест.")
            return

    # Зберігаємо стан користувача для цього тесту
    context.user_data["current_test"] = test_name
    context.user_data["current_test_dir"] = test_dir
    context.user_data["questions"] = questions
    context.user_data["total_questions"] = len(questions)

    # скидаємо можливі флаги пошуку/офісу
    context.user_data.pop("awaiting_search", None)
    context.user_data.pop("search_mode", None)
    context.user_data["in_office"] = False

    if "stats" not in context.user_data:
        context.user_data["stats"] = {
            "total_answered": 0,
            "correct_answers": 0,
            "best_streak": 0
        }

    lang = context.bot_data.get("lang", "uk")
    await query.message.reply_text(
        t(lang, "test_selected", test=test_name, count=len(questions)),
        reply_markup=main_menu()
    )
