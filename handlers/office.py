# handlers/office.py
import os
import json
import logging
from typing import List, Tuple

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes

from utils.i18n import t
from handlers.start import cmd_start
from handlers.favorites import show_favorites
from handlers.start import cmd_stats
from handlers.vip_tests import office_my_tests_entry, office_shared_tests_entry
from handlers.wrong_answers import wrong_answers_cmd  # ✅ додано

from handlers.vip_tests.vip_constants import TESTS_ROOT
from handlers.vip_tests.vip_storage import _load_owners, get_meta_for_rel  # ✅ доповнено імпорт

# 👑 Власник бота
from utils.auth import is_owner
from handlers.owner_panel import owner_entry

logger = logging.getLogger("test_bot.office")

# Кнопки
BTN_STATS = "Моя статистика"
BTN_FAVS = "Мої улюблені"
BTN_MY_TESTS = "Мої тести"
BTN_SHARED_TESTS = "Спільні тести"
BTN_MY_QUESTIONS = "Мої питання"
BTN_MY_WRONG = "Мої помилки"  # ✅ додано
BTN_OWNER = "👑 Адмін-панель"  # ✅ нове (показується лише власнику)
BTN_BACK = "⬅️ Назад"


def office_keyboard(user_is_owner: bool = False) -> ReplyKeyboardMarkup:
    """
    Формує клавіатуру «Мій кабінет».
    Якщо user_is_owner=True — останній рядок: [👑 Адмін-панель, ⬅️ Назад]
    Якщо False — останній рядок: [⬅️ Назад]
    """
    kb = [
        [KeyboardButton(BTN_STATS), KeyboardButton(BTN_FAVS)],
        [KeyboardButton(BTN_MY_TESTS), KeyboardButton(BTN_SHARED_TESTS)],
        [KeyboardButton(BTN_MY_QUESTIONS), KeyboardButton(BTN_MY_WRONG)],
    ]
    if user_is_owner:
        kb.append([KeyboardButton(BTN_OWNER), KeyboardButton(BTN_BACK)])
    else:
        kb.append([KeyboardButton(BTN_BACK)])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def _ua_users(n: int) -> str:
    """
    Українська форма слова «користувач» за числом n.
    1 — користувач, 2-4 — користувачі, 5+ — користувачів.
    """
    n_abs = abs(n) % 100
    n1 = n_abs % 10
    if 11 <= n_abs <= 14:
        return "користувачів"
    if n1 == 1:
        return "користувач"
    if 2 <= n1 <= 4:
        return "користувачі"
    return "користувачів"


async def office_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Скинемо інші майстри/флаги, щоб не заважали
    for k in ("awaiting_search", "search_mode", "awaiting_comment", "add_question_active"):
        context.user_data.pop(k, None)
    context.user_data["in_office"] = True

    # Хто користувач і чи він власник бота
    user_id = update.effective_user.id
    user_is_owner = is_owner(user_id)

    # --- НОВЕ: перевірка запитів на спільне користування тестом ---
    owners = _load_owners() or {}

    # беремо лише ті записи, де поточний користувач — власник тесту
    pending_lines: List[str] = []
    total_pending = 0

    for rel, meta in owners.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("owner_id") != user_id:
            continue

        # читаємо актуальні дані через get_meta_for_rel (уніфікована форма)
        m = get_meta_for_rel(rel)
        pend = m.get("pending") or []
        cnt = len(pend)
        if cnt <= 0:
            continue

        # Назва тесту — з файлу (назва JSON без ".json")
        test_title = os.path.splitext(os.path.basename(rel))[0]
        pending_lines.append(f"{test_title} — {cnt} {_ua_users(cnt)}")
        total_pending += cnt

    if total_pending > 0:
        middle = "У вас є запит на спільне користування тестом"
        middle += "\n" + "\n".join(pending_lines)
    else:
        middle = "У вас немає повідомлень  від тестів"  # зберігаю точну фразу, як ви просили

    text = "👤 Мій кабінет\n" + middle + "\nОберіть розділ."

    await update.message.reply_text(text, reply_markup=office_keyboard(user_is_owner=user_is_owner))


async def office_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    context.user_data["in_office"] = True

    if text == BTN_STATS:
        await cmd_stats(update, context)
        return

    if text == BTN_FAVS:
        await show_favorites(update, context)
        return

    if text == BTN_MY_TESTS:
        await office_my_tests_entry(update, context)
        return

    if text == BTN_SHARED_TESTS:
        await office_shared_tests_entry(update, context)
        return

    if text == BTN_MY_QUESTIONS:
        await office_my_questions(update, context)
        return

    if text == BTN_MY_WRONG:
        await wrong_answers_cmd(update, context)
        return

    if text == BTN_OWNER:
        if is_owner(update.effective_user.id):
            await owner_entry(update, context)
        else:
            await update.message.reply_text("⛔ Лише для власника бота.")
        return

    if text == BTN_BACK:
        context.user_data["suppress_test_select_once"] = True
        context.user_data["in_office"] = False
        for k in ("awaiting_search", "search_mode"):
            context.user_data.pop(k, None)
        await cmd_start(update, context)
        return

    await update.message.reply_text(
        "Оберіть дію нижче:",
        reply_markup=office_keyboard(user_is_owner=is_owner(update.effective_user.id)),
    )


# --------- «Мої питання» ---------
def _iter_json_tests(root: str) -> List[Tuple[str, str]]:
    """
    Повертає список пар (abs_json_path, rel_path_from_tests).
    Враховує лише *.json файли.
    """
    out: List[Tuple[str, str]] = []
    root_abs = os.path.abspath(root)
    for dirpath, _, filenames in os.walk(root_abs):
        for fn in filenames:
            if not fn.lower().endswith(".json"):
                continue
            abs_json = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_json, root_abs).replace("\\", "/")
            out.append((abs_json, rel))
    return out


def _read_json_list(abs_json: str) -> int:
    """
    Повертає кількість елементів (питань) у файлі JSON, якщо це масив.
    Помилки — 0.
    """
    try:
        with open(abs_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return len(data)
    except Exception:
        pass
    return 0


async def office_my_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показує підбірку тестів, у які ти міг додавати питання:
    1) Тести, де ТИ — власник (за tests/_owners.json).
    2) Усі тести з поміткою (custom).

    Для кожного пункту показуємо кількість питань у відповідному JSON.
    """
    user_id = update.effective_user.id
    owners = _load_owners()

    # 1) Тести, де ти власник
    owned: List[Tuple[str, str]] = []
    for rel, meta in owners.items():
        if isinstance(meta, dict) and meta.get("owner_id") == user_id:
            owned.append((os.path.join(TESTS_ROOT, rel), rel))

    # 2) Усі (custom) тести
    customs: List[Tuple[str, str]] = []
    for abs_json, rel in _iter_json_tests(TESTS_ROOT):
        base = os.path.basename(abs_json)
        if base.endswith(" (custom).json"):
            customs.append((abs_json, rel))

    # Формуємо текст
    lines: List[str] = []
    if owned:
        lines.append("Ваші власні тести (де ви могли додавати питання без '(custom)'):")
        for abs_json, rel in sorted(owned, key=lambda x: x[1].lower()):
            name = os.path.splitext(os.path.basename(abs_json))[0]
            count = _read_json_list(abs_json)
            lines.append(f"• {name}  —  /{rel}  ({count} питань)")
        lines.append("")

    if customs:
        lines.append("Тести (custom), куди можуть додавати всі користувачі:")
        for abs_json, rel in sorted(customs, key=lambda x: x[1].lower()):
            name = os.path.splitext(os.path.basename(abs_json))[0]
            count = _read_json_list(abs_json)
            lines.append(f"• {name}  —  /{rel}  ({count} питань)")
    else:
        if not owned:
            lines.append("Поки що немає тестів, куди ви додавали питання.")

    text = "\n".join(lines) if lines else "Поки що немає тестів, куди ви додавали питання."
    await update.message.reply_text(text)
