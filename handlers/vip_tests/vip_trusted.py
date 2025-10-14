# handlers/vip_tests/vip_trusted.py
import re
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_storage import (
    _load_owners, _save_owners,
    get_meta_for_rel, save_meta_for_rel,
    list_trusted_display,
    add_trusted_username, remove_trusted_by_key,
    list_pending_display, accept_pending_by_key, decline_pending_by_key,
    get_requests_count_for_rel,
)

log = logging.getLogger("test_bot.vip_trusted")

# локальний нормалізатор username — щоб уникнути залежності від vip_storage.usernamestr
def _normalize_username(s: str) -> str | None:
    if not s:
        return None
    s = s.strip()
    if s.startswith("@"):
        s = s[1:]
    s = s.replace("@", "").strip()
    if not s:
        return None
    # Дозволяємо класичний телеграм-username
    if re.fullmatch(r"[A-Za-z0-9_]{3,32}", s):
        return s
    return None

def _trusted_panel_kb(idx: int, rel: str | None = None) -> InlineKeyboardMarkup:
    """
    Панель «Довірені користувачі» з кнопками:
    - Додати довірених
    - Видалити довірених
    - Запити (N)
    - Назад до редагування
    """
    rows = [
        [InlineKeyboardButton("➕ Додати довірених", callback_data=f"vip_trusted_add|{idx}")],
        [InlineKeyboardButton("➖ Видалити довірених", callback_data=f"vip_trusted_remove|{idx}")]
    ]
    if rel:
        cnt = get_requests_count_for_rel(rel)
        rows.append([InlineKeyboardButton(f"📥 Запити ({cnt})", callback_data=f"vip_trusted_requests|{idx}")])
    rows.append([InlineKeyboardButton("🔙 Назад до редагування", callback_data=f"vip_edit|{idx}")])
    return InlineKeyboardMarkup(rows)

async def vip_trusted_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    rel = item["rel"]
    owners = _load_owners()
    meta = owners.get(rel) or {}
    trusted_ids = meta.get("trusted") or []
    trusted_unames = meta.get("trusted_usernames") or []
    if not isinstance(trusted_ids, list):
        trusted_ids = []
    if not isinstance(trusted_unames, list):
        trusted_unames = []

    # контекст панелі довірених
    context.user_data["vip_trusted_idx"] = idx
    context.user_data["vip_trusted_rel"] = rel

    listing = list_trusted_display(trusted_ids, trusted_unames)
    if listing:
        text = f"👥 Довірені користувачі для «{item['name']}»:\n{listing}\n\n"
    else:
        text = f"👥 Довірені користувачі для «{item['name']}»: (порожньо)\n\n"

    text += "Щоб додати, натисни «➕ Додати довірених» або просто надішли @username / числовий ID у чат."
    await query.message.reply_text(text, reply_markup=_trusted_panel_kb(idx, rel))

async def vip_trusted_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    idx_str = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    try:
        idx = int(idx_str)
    except ValueError:
        return
    context.user_data["vip_trusted_idx"] = idx
    context.user_data["awaiting_vip_trusted_username"] = True
    await query.message.reply_text("✍️ Введіть @username або числовий ID користувача для додавання у довірені:")

def _looks_like_user_identifier(s: str) -> bool:
    if not s:
        return False
    s = s.strip()
    if s.startswith("@"):
        core = s[1:]
        return bool(re.fullmatch(r"[A-Za-z0-9_]{3,32}", core))
    return bool(re.fullmatch(r"\d{5,}", s))

def _resolve_target_idx_for_text(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    idx = context.user_data.get("vip_trusted_idx")
    if isinstance(idx, int):
        return idx
    if context.user_data.get("in_office"):
        items = context.user_data.get("vip_mytests") or []
        if len(items) == 1:
            return 0
    return None

async def _do_add_trusted_by_idx(idx: int, val: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await update.message.reply_text("❌ Тест не знайдено або не вибрано.")
        return

    item = items[idx]
    rel = item["rel"]

    # Визначаємо — це ID чи @username
    if val.startswith("@"):
        uname = _normalize_username(val)
        if not uname:
            await update.message.reply_text("❌ Невірний username.")
            return
        added = add_trusted_username(rel, uname)
        if added:
            await update.message.reply_text(f"✅ Додано до довірених: @{uname}")
        else:
            await update.message.reply_text(f"ℹ️ @{uname} вже є у списку довірених.")
    else:
        # числовий ID
        try:
            uid = int(val)
        except ValueError:
            await update.message.reply_text("❌ Невірний ID.")
            return
        owners = _load_owners()
        meta = owners.get(rel) or {}
        ids = meta.get("trusted") or []
        if uid in ids:
            await update.message.reply_text("ℹ️ Цей користувач вже у списку довірених.")
        else:
            ids.append(uid)
            meta["trusted"] = ids
            owners[rel] = meta
            _save_owners(owners)
            await update.message.reply_text(f"✅ Додано до довірених: ID:{uid}")

    # Готово
    context.user_data.pop("awaiting_vip_trusted_username", None)

    # Показуємо оновлений список
    meta = get_meta_for_rel(rel)
    listing = list_trusted_display(meta.get("trusted", []), meta.get("trusted_usernames", []))
    kb = _trusted_panel_kb(idx, rel)
    await update.message.reply_text(
        f"👥 Довірені для «{item['name']}»:\n{listing or '(порожньо)'}",
        reply_markup=kb
    )

async def vip_trusted_handle_username_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Додає @username/ID до довірених:
      - якщо відкрито панель довірених або натиснуто «➕»;
      - якщо в офісі і рівно один тест — додаємо в нього;
      - якщо тестів кілька — просимо вибрати тест інлайн-кнопкою.
    """
    text = (update.message.text or "").strip()
    if not _looks_like_user_identifier(text):
        return

    awaiting = bool(context.user_data.get("awaiting_vip_trusted_username"))
    idx = _resolve_target_idx_for_text(context)

    log.info("[TRUSTED] incoming='%s' awaiting=%s idx=%s in_office=%s tests_count=%s",
             text, awaiting, idx, context.user_data.get("in_office"),
             len(context.user_data.get("vip_mytests") or []))

    val = text if text.startswith("@") else text

    if awaiting or idx is not None:
        await _do_add_trusted_by_idx(idx if idx is not None else context.user_data.get("vip_trusted_idx", 0), val, update, context)
        return

    # Якщо ми тут — користувач у «Мій кабінет», тестів кілька → запропонувати вибір
    items = context.user_data.get("vip_mytests") or []
    if not items:
        return  # поза офісом — не перехоплюємо

    rows = []
    for i, it in enumerate(items):
        rows.append([InlineKeyboardButton(it["name"], callback_data=f"vip_trusted_pick|{i}|{val}")])
    await update.message.reply_text("Оберіть тест, до якого додати довіреного користувача:", reply_markup=InlineKeyboardMarkup(rows))

async def vip_trusted_pick_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback від вибору тесту для додавання @username/ID."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|", 2)
    if len(parts) != 3:
        return
    _, idx_str, val = parts
    try:
        idx = int(idx_str)
    except ValueError:
        return
    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await query.message.reply_text("❌ Тест не знайдено.")
        return

    # сформуємо "update-like" API (бо _do_add_trusted_by_idx очікує update.message)
    class _MsgProxy:
        def __init__(self, msg):
            self.chat_id = msg.chat_id
        async def reply_text(self, *args, **kwargs):
            await query.message.reply_text(*args, **kwargs)

    proxy_update = type("ProxyUpdate", (), {"message": _MsgProxy(query.message)})()
    await _do_add_trusted_by_idx(idx, val, proxy_update, context)

async def vip_trusted_remove_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Відкриває список довірених для видалення.
    Тепер показуємо по можливості ОБ'ЄДНАНІ кнопки: «ID:xxx + @name»,
    що видаляють і ID, і @username одночасно.
    Одиночні записи (лише ID або лише @) показуються окремо.
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
    rel = item["rel"]
    meta = get_meta_for_rel(rel)
    trusted_ids = list(meta.get("trusted", [])) or []
    trusted_unames = list(meta.get("trusted_usernames", [])) or []

    rows: list[list[InlineKeyboardButton]] = []

    # 1) Спробуємо спарити по індексу — це відповідає випадку прийняття pending,
    #    коли і ID, і username додаються одночасно та у відповідному порядку.
    pair_count = min(len(trusted_ids), len(trusted_unames))
    used_id_idx = set()
    used_un_idx = set()
    for i in range(pair_count):
        uid = trusted_ids[i]
        uname = trusted_unames[i]
        rows.append([
            InlineKeyboardButton(
                f"✖ ID:{uid} + @{uname}",
                callback_data=f"vip_trusted_remove_do|{idx}|both:{uid}:{uname}"
            )
        ])
        used_id_idx.add(i)
        used_un_idx.add(i)

    # 2) Залишкові «тільки ID»
    for j, uid in enumerate(trusted_ids):
        if j in used_id_idx:
            continue
        rows.append([
            InlineKeyboardButton(
                f"✖ ID:{uid}",
                callback_data=f"vip_trusted_remove_do|{idx}|id:{uid}"
            )
        ])

    # 3) Залишкові «тільки @username»
    for k, uname in enumerate(trusted_unames):
        if k in used_un_idx:
            continue
        rows.append([
            InlineKeyboardButton(
                f"✖ @{uname}",
                callback_data=f"vip_trusted_remove_do|{idx}|uname:{uname}"
            )
        ])

    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f"vip_trusted|{idx}")])
    await query.message.reply_text("Оберіть кого видалити зі списку довірених:", reply_markup=InlineKeyboardMarkup(rows))

async def vip_trusted_remove_do(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обробляє видалення:
    - id:<uid> — видаляє лише ID
    - uname:<name> — видаляє лише username
    - both:<uid>:<name> — видаляє і ID, і username одночасно
    """
    query = update.callback_query
    await query.answer()
    parts = (query.data.split("|", 2) if "|" in query.data else [])
    if len(parts) < 3:
        return
    _, idx_str, payload = parts
    try:
        idx = int(idx_str)
    except ValueError:
        return

    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await query.message.reply_text("❌ Тест не знайдено.")
        return

    item = items[idx]
    rel = item["rel"]

    # Розбір payload
    kind, key = None, None
    if payload.startswith("both:"):
        # both:<uid>:<uname>
        rest = payload[5:]
        try:
            uid_str, uname = rest.split(":", 1)
        except ValueError:
            await query.message.reply_text("❌ Невірний параметр видалення.")
            return

        # Видаляємо обидва
        ok1 = remove_trusted_by_key(rel, "id", uid_str)
        ok2 = remove_trusted_by_key(rel, "uname", uname)
        if ok1 or ok2:
            await query.message.reply_text("✅ Видалено зі списку довірених (ID та @username).")
        else:
            await query.message.reply_text("ℹ️ Вказаного користувача не знайдено у списку.")
        await vip_trusted_open(update, context)
        return

    if payload.startswith("id:"):
        kind, key = "id", payload[3:]
    elif payload.startswith("uname:"):
        kind, key = "uname", payload[6:]

    if not kind or key is None:
        await query.message.reply_text("❌ Невірний параметр видалення.")
        return

    done = remove_trusted_by_key(rel, kind, key)
    if done:
        await query.message.reply_text("✅ Видалено зі списку довірених.")
    else:
        await query.message.reply_text("ℹ️ Вказаного користувача не знайдено у списку.")

    await vip_trusted_open(update, context)

# ================== БЛОК «ЗАПИТИ» ==================

def _requests_kb(idx: int, rel: str, pending_len: int) -> InlineKeyboardMarkup:
    """
    Клавіатура для екрана запитів:
    - для кожного запиту окремо: ✅/✖
    - внизу: «Підтвердити всі», «Відхилити всі», «Назад»
    """
    meta = get_meta_for_rel(rel)
    pend = list(meta.get("pending", []))
    rows = []
    for i, req in enumerate(pend):
        uname = req.get("username") or "-"
        uid = req.get("user_id") or "-"
        # ВАЖЛИВО: шорт-нейми під bot.py:
        rows.append([
            InlineKeyboardButton(f"✅ @{uname}", callback_data=f"vip_tr_req_accept|{idx}|{i}"),
            InlineKeyboardButton(f"✖ ID:{uid}", callback_data=f"vip_tr_req_decline|{idx}|{i}"),
        ])
    rows.append([InlineKeyboardButton("✅ Підтвердити всі", callback_data=f"vip_tr_req_accept_all|{idx}")])
    rows.append([InlineKeyboardButton("✖ Відхилити всі", callback_data=f"vip_tr_req_decline_all|{idx}")])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f"vip_trusted|{idx}")])
    return InlineKeyboardMarkup(rows)

async def vip_trusted_requests_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відкрити екран зі списком запитів."""
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
    rel = item["rel"]
    meta = get_meta_for_rel(rel)
    pend = list(meta.get("pending", []))

    if not pend:
        await query.message.reply_text("📭 Запитів наразі немає.", reply_markup=_trusted_panel_kb(idx, rel))
        return

    header = f"📥 Запити на доступ до «{item['name']}»:\n\n" + list_pending_display(pend)
    await query.message.reply_text(header, reply_markup=_requests_kb(idx, rel, len(pend)))

async def vip_trusted_requests_accept_one(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    if len(parts) != 3:
        return
    _, idx_str, req_idx = parts
    try:
        idx = int(idx_str)
    except ValueError:
        return

    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await query.message.reply_text("❌ Тест не знайдено.")
        return
    rel = items[idx]["rel"]

    if accept_pending_by_key(rel, req_idx):
        await query.message.reply_text("✅ Запит підтверджено.")
    else:
        await query.message.reply_text("⚠️ Не вдалося підтвердити (невірний індекс).")

    await vip_trusted_requests_open(update, context)

async def vip_trusted_requests_decline_one(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    if len(parts) != 3:
        return
    _, idx_str, req_idx = parts
    try:
        idx = int(idx_str)
    except ValueError:
        return

    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await query.message.reply_text("❌ Тест не знайдено.")
        return
    rel = items[idx]["rel"]

    if decline_pending_by_key(rel, req_idx):
        await query.message.reply_text("✖ Запит відхилено.")
    else:
        await query.message.reply_text("⚠️ Не вдалося відхилити (невірний індекс).")

    await vip_trusted_requests_open(update, context)

async def vip_trusted_requests_accept_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    rel = items[idx]["rel"]

    meta = get_meta_for_rel(rel)
    pend = list(meta.get("pending", []))
    accepted = 0
    for _ in range(len(pend)):
        if accept_pending_by_key(rel, "0"):
            accepted += 1
    await query.message.reply_text(f"✅ Підтверджено запитів: {accepted}")
    await vip_trusted_requests_open(update, context)

async def vip_trusted_requests_decline_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    rel = items[idx]["rel"]

    meta = get_meta_for_rel(rel)
    pend = list(meta.get("pending", []))
    declined = 0
    for _ in range(len(pend)):
        if decline_pending_by_key(rel, "0"):
            declined += 1
    await query.message.reply_text(f"✖ Відхилено запитів: {declined}")
    await vip_trusted_requests_open(update, context)
