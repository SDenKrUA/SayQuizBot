import os
from typing import List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ContextTypes

from utils.auth import is_owner
from utils.loader import discover_tests_hierarchy
from utils.mod_tools import (
    TESTS_ROOT,
    find_empty_sections,
    delete_section,
    rename_section,
    delete_test,
    move_test,
    find_custom_tests,
)

# ---------- Token Map (щоб не перевищувати 64 байти у callback_data) ----------

def _get_pathmap(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("own_pathmap", {})

def _token_for_path(context: ContextTypes.DEFAULT_TYPE, rel_path: str) -> str:
    mp = _get_pathmap(context)
    for k, v in mp.items():
        if v == rel_path:
            return k
    token = f"p{len(mp)}"
    mp[token] = rel_path
    return token

def _resolve_token(context: ContextTypes.DEFAULT_TYPE, token: str) -> str:
    mp = _get_pathmap(context)
    return mp.get(token, "")

# ---------- UI Builders ----------

def _kb(rows: List[List[Tuple[str, str]]]) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows]
    return InlineKeyboardMarkup(keyboard)

def _owner_root_kb() -> InlineKeyboardMarkup:
    rows = [
        [("📁 Розділи", "own|sec|root"), ("📚 Тести (custom)", "own|tests|custom")],
        [("🧹 Видалити порожні розділи", "own|sec|del_empty")],
        [("🔄 Оновити", "own|refresh")],
    ]
    return _kb(rows)

def _sections_kb(context: ContextTypes.DEFAULT_TYPE, subfolders: List[str], cur_rel: str) -> InlineKeyboardMarkup:
    rows: List[List[Tuple[str, str]]] = []

    if cur_rel:
        up_path = os.path.dirname(cur_rel)
        tok = _token_for_path(context, up_path)
        rows.append([("⬆️ Вгору", f"own|sec|open|{tok}")])

    for d in subfolders:
        nxt = os.path.join(cur_rel, d) if cur_rel else d
        tok = _token_for_path(context, nxt)
        rows.append([("📂 " + d, f"own|sec|open|{tok}")])

    if cur_rel:
        tok_cur = _token_for_path(context, cur_rel)
        rows.append([
            ("🗑 Видалити цю теку", f"own|sec|del|{tok_cur}"),
            ("✏️ Перейменувати", f"own|sec|ren|{tok_cur}")
        ])
    rows.append([("🏠 На головну", "own|home")])
    return _kb(rows)

def _custom_tests_list_kb(context: ContextTypes.DEFAULT_TYPE, items: List[str], page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    start = page * page_size
    end = start + page_size
    chunk = items[start:end]
    rows: List[List[Tuple[str, str]]] = []
    for rel in chunk:
        tok = _token_for_path(context, rel)
        rows.append([
            ("🗑", f"own|tests|del|{tok}"),
            ("📦 Перемістити", f"own|tests|mv|{tok}"),
            ("📄 " + os.path.basename(rel), "own|tests|noop")
        ])
    nav: List[Tuple[str, str]] = []
    if start > 0:
        nav.append(("⬅️", f"own|tests|page|{page-1}"))
    if end < len(items):
        nav.append(("➡️", f"own|tests|page|{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([("🏠 На головну", "own|home")])
    return _kb(rows)

def _sections_pick_kb(context: ContextTypes.DEFAULT_TYPE, cur_rel: str) -> InlineKeyboardMarkup:
    tree = discover_tests_hierarchy(TESTS_ROOT)
    parts = [] if not cur_rel else cur_rel.split(os.sep)
    node = tree
    for p in parts:
        node = node["subdirs"].get(p, None) if node else None
    subfolders = sorted(list(node["subdirs"].keys())) if node else []

    rows: List[List[Tuple[str, str]]] = []
    tok_cur = _token_for_path(context, cur_rel)
    rows.append([("📍 Обрати тут", f"own|mv|choose|{tok_cur}")])
    if cur_rel:
        parent = os.path.dirname(cur_rel)
        tok_up = _token_for_path(context, parent)
        rows.append([("⬆️ Вгору", f"own|mv|open|{tok_up}")])
    for d in subfolders:
        nxt = os.path.join(cur_rel, d) if cur_rel else d
        tok = _token_for_path(context, nxt)
        rows.append([("📂 " + d, f"own|mv|open|{tok}")])
    rows.append([("❌ Скасувати", "own|cancel")])
    return _kb(rows)

# ---------- Entry ----------

async def owner_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_owner(user.id):
        await update.effective_message.reply_text("⛔ Лише для власника бота.")
        return
    context.user_data["own_pathmap"] = {}
    await update.effective_message.reply_text(
        "👑 <b>Адмін-панель (власник)</b>\nОберіть дію:",
        parse_mode="HTML",
        reply_markup=_owner_root_kb()
    )

# ---------- Router ----------

async def owner_router_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not user or not is_owner(user.id):
        await query.edit_message_text("⛔ Доступ заборонено (не власник).")
        return

    parts = (query.data or "").split("|")
    if len(parts) < 2 or parts[0] != "own":
        return

    if parts[1] == "home":
        context.user_data["own_pathmap"] = {}
        await query.edit_message_text(
            "👑 <b>Адмін-панель (власник)</b>\nОберіть дію:",
            parse_mode="HTML",
            reply_markup=_owner_root_kb()
        )
        return

    if parts[1] == "refresh":
        context.user_data["own_pathmap"] = {}
        await owner_entry(update, context)
        return

    # --------- SECTIONS ----------
    if parts[1] == "sec":
        if len(parts) >= 3 and parts[2] == "root":
            context.user_data["own_pathmap"] = {}
            tree = discover_tests_hierarchy(TESTS_ROOT)
            subfolders = sorted(list(tree["subdirs"].keys()))
            await query.edit_message_text(
                "<b>Розділи — корінь</b>",
                parse_mode="HTML",
                reply_markup=_sections_kb(context, subfolders, "")
            )
            return

        if len(parts) >= 4 and parts[2] == "open":
            rel = _resolve_token(context, parts[3])
            tree = discover_tests_hierarchy(TESTS_ROOT)
            node = tree
            if rel:
                for p in rel.split(os.sep):
                    node = node["subdirs"].get(p, None) if node else None
            subfolders = sorted(list(node["subdirs"].keys())) if node else []
            title = f"<b>Розділи — {rel or 'корінь'}</b>"
            await query.edit_message_text(
                title,
                parse_mode="HTML",
                reply_markup=_sections_kb(context, subfolders, rel)
            )
            return

        if len(parts) >= 3 and parts[2] == "del_empty":
            empties = find_empty_sections(TESTS_ROOT)
            if not empties:
                await query.edit_message_text(
                    "🧹 Порожніх розділів не знайдено.",
                    reply_markup=_owner_root_kb()
                )
                return
            await query.edit_message_text(
                "🧹 Знайдено порожні теки:\n" + "\n".join(f"• {e}" for e in empties) + "\n\nВидалити всі?",
                reply_markup=_kb([[("✅ Так", "own|sec|del_empty|yes"), ("❌ Ні", "own|home")]])
            )
            return

        if len(parts) >= 4 and parts[2] == "del_empty" and parts[3] == "yes":
            empties = find_empty_sections(TESTS_ROOT)
            ok_cnt = 0
            for rel in empties:
                ok, _ = delete_section(rel, TESTS_ROOT)
                if ok:
                    ok_cnt += 1
            await query.edit_message_text(
                f"🧹 Видалено порожніх тек: {ok_cnt}",
                reply_markup=_owner_root_kb()
            )
            return

        if len(parts) >= 4 and parts[2] == "del":
            rel = _resolve_token(context, parts[3])
            ok, msg = delete_section(rel, TESTS_ROOT)
            await query.edit_message_text(
                ("✅ " if ok else "⚠️ ") + msg,
                reply_markup=_owner_root_kb()
            )
            return

        # ✏️ Перейменувати — тепер через ForceReply (не блокує інші тексти)
        if len(parts) >= 4 and parts[2] == "ren":
            rel = _resolve_token(context, parts[3])
            context.user_data["own_ren_target"] = rel
            context.user_data["own_waiting_rename"] = True
            await query.message.reply_text(
                f"✏️ Введіть нову назву для теки:\n<code>{rel or '.'}</code>",
                parse_mode="HTML",
                reply_markup=ForceReply(selective=True, input_field_placeholder="Нова назва теки")
            )
            return

    # --------- TESTS ----------
    if parts[1] == "tests":
        if len(parts) >= 3 and parts[2] == "custom":
            items = find_custom_tests(TESTS_ROOT)
            context.user_data["own_tests_list"] = items
            context.user_data["own_pathmap"] = {}
            await query.edit_message_text(
                f"📚 <b>Кастом-тести</b> ({len(items)})",
                parse_mode="HTML",
                reply_markup=_custom_tests_list_kb(context, items, page=0)
            )
            return

        if len(parts) >= 4 and parts[2] == "page":
            try:
                page = int(parts[3])
            except ValueError:
                page = 0
            items = context.user_data.get("own_tests_list") or find_custom_tests(TESTS_ROOT)
            await query.edit_message_text(
                f"📚 <b>Кастом-тести</b> ({len(items)})",
                parse_mode="HTML",
                reply_markup=_custom_tests_list_kb(context, items, page=page)
            )
            return

        if len(parts) >= 4 and parts[2] == "del":
            rel = _resolve_token(context, parts[3])
            context.user_data["own_del_test"] = rel
            await query.edit_message_text(
                f"🗑 Видалити тест?\n<code>{rel}</code>",
                parse_mode="HTML",
                reply_markup=_kb([[("✅ Так", "own|tests|del_do"), ("❌ Ні", "own|tests|custom")]])
            )
            return

        if len(parts) >= 3 and parts[2] == "del_do":
            rel = context.user_data.get("own_del_test")
            if not rel:
                await query.edit_message_text("⚠️ Не вибрано тест.", reply_markup=_owner_root_kb())
                return
            ok, msg = delete_test(rel, with_media=True, root=TESTS_ROOT)
            items = find_custom_tests(TESTS_ROOT)
            context.user_data["own_tests_list"] = items
            context.user_data["own_pathmap"] = {}
            await query.edit_message_text(
                (f"✅ {msg}" if ok else f"⚠️ {msg}") + f"\n\n📚 Залишилось: {len(items)}",
                reply_markup=_custom_tests_list_kb(context, items, page=0)
            )
            return

        if len(parts) >= 4 and parts[2] == "mv":
            rel = _resolve_token(context, parts[3])
            context.user_data["own_mv_test"] = rel
            context.user_data["own_pathmap"] = {}
            await query.edit_message_text(
                f"📦 Куди перемістити?\n<code>{rel}</code>",
                parse_mode="HTML",
                reply_markup=_sections_pick_kb(context, "")
            )
            return

    # --------- MOVE ----------
    if parts[1] == "mv":
        if len(parts) >= 4 and parts[2] == "open":
            rel = _resolve_token(context, parts[3])
            await query.edit_message_text(
                f"📦 Оберіть теку\n<code>{rel or '.'}</code>",
                parse_mode="HTML",
                reply_markup=_sections_pick_kb(context, rel)
            )
            return

        if len(parts) >= 4 and parts[2] == "choose":
            rel = _resolve_token(context, parts[3])
            test_rel = context.user_data.get("own_mv_test")
            if not test_rel:
                await query.edit_message_text("⚠️ Тест не вибрано.", reply_markup=_owner_root_kb())
                return
            ok, msg = move_test(test_rel, rel, TESTS_ROOT)
            items = find_custom_tests(TESTS_ROOT)
            context.user_data["own_tests_list"] = items
            context.user_data["own_pathmap"] = {}
            await query.edit_message_text(
                (f"✅ {msg}" if ok else f"⚠️ {msg}") + f"\n\n📚 Кастом-тести: {len(items)}",
                reply_markup=_custom_tests_list_kb(context, items, page=0)
            )
            return

    if parts[1] == "cancel":
        context.user_data["own_pathmap"] = {}
        await query.edit_message_text("❌ Скасовано.", reply_markup=_owner_root_kb())
        return

    await query.answer("OK")

# ---------- Text entry for rename (REPLY-only) ----------

async def owner_text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Спрацьовує тільки якщо:
      1) це reply на запит перейменування (ForceReply),
      2) прапорець own_waiting_rename встановлено,
      3) відправник — власник.
    """
    if not (update.message and update.message.reply_to_message):
        return
    if not context.user_data.get("own_waiting_rename"):
        return
    user = update.effective_user
    if not user or not is_owner(user.id):
        return

    new_name = (update.effective_message.text or "").strip()
    rel = context.user_data.get("own_ren_target")
    context.user_data["own_waiting_rename"] = False
    context.user_data["own_ren_target"] = None

    if not new_name:
        await update.effective_message.reply_text("⚠️ Порожня назва. Операцію скасовано.", reply_markup=_owner_root_kb())
        return
    ok, msg = rename_section(rel, new_name, TESTS_ROOT)
    await update.effective_message.reply_text(("✅ " if ok else "⚠️ ") + msg, reply_markup=_owner_root_kb())
