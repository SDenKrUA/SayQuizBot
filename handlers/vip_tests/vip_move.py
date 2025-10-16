# handlers/vip_tests/vip_move.py
import os
import shutil
import stat
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_constants import TESTS_ROOT
from .vip_storage import (
    _load_owners, _save_owners, _relative_to_tests, _refresh_catalogs, _cleanup_empty_dirs
)
from utils.export_docx import _safe_filename
from utils.loader import IGNORED_JSON_SUFFIXES, discover_tests, discover_tests_hierarchy

logger = logging.getLogger("test_bot.vip_move")

# ========= helpers: single-message editing for MOVE =========

def _set_move_msg(context: ContextTypes.DEFAULT_TYPE, mid: int, chat_id: int) -> None:
    context.user_data["vip_move_msg_id"] = mid
    context.user_data["vip_move_chat_id"] = chat_id

def _get_move_msg(context: ContextTypes.DEFAULT_TYPE) -> tuple[int | None, int | None]:
    return context.user_data.get("vip_move_msg_id"), context.user_data.get("vip_move_chat_id")

async def _edit_move_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, kb: InlineKeyboardMarkup) -> None:
    """
    Редагуємо ОДНЕ повідомлення для сценарію «перемістити тест».
    Якщо ще немає закріпленого message_id — створимо повідомлення і запам’ятаємо його.
    """
    msg_id, chat_id = _get_move_msg(context)
    if msg_id and chat_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=kb
            )
            return
        except Exception as e:
            logger.debug("[MOVE] edit failed, fallback to reply: %s", e)
    m = await update.effective_message.reply_text(text, reply_markup=kb)
    _set_move_msg(context, m.message_id, m.chat_id)

# --- Допоміжне ----

def _is_test_json(filename: str) -> bool:
    """True, якщо це звичайний тестовий JSON (без службових суфіксів)."""
    if not filename.lower().endswith(".json"):
        return False
    low = filename.lower()
    for suf in IGNORED_JSON_SUFFIXES:
        if low.endswith(suf):
            return False
    return True

def _safe_rmtree(path: str) -> None:
    if not os.path.isdir(path):
        return
    def onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    try:
        shutil.rmtree(path, onerror=onerror)
    except Exception:
        try:
            if not os.listdir(path):
                os.rmdir(path)
        except Exception:
            pass

# --- Локальний браузер тек для режиму «перемістити тест» (з idx) ---

def _move_browser_kb(path, idx: int) -> InlineKeyboardMarkup:
    """
    Браузер тек для релокації:
      - показує лише «справжні» розділи;
      - ховає папки-картинки:
          * назва каталогу збігається з base-name будь-якого тестового JSON у тій самій теці,
          * або починається з '#' / '_' (альтернативні каталоги зображень),
          * або закінчується на '.comments'.
      - завжди має «Скасувати» → повернення до меню редагування тесту.
    """
    abs_dir = os.path.join(TESTS_ROOT, *path) if path else TESTS_ROOT
    try:
        items = os.listdir(abs_dir)
    except FileNotFoundError:
        items = []

    # зберемо множину base-name тестових JSON у поточному каталозі
    json_basenames = set()
    for fname in items:
        if _is_test_json(fname):
            json_basenames.add(os.path.splitext(fname)[0].lower())

    # підкаталоги
    subdirs = []
    for name in items:
        p = os.path.join(abs_dir, name)
        if not os.path.isdir(p):
            continue

        low = name.lower()

        # 1) папка з картинками має рівно таку ж назву, як JSON поруч
        if low in json_basenames:
            continue
        # 2) службові каталоги (варіанти каталогів зображень або коментарів)
        if name.startswith("#") or name.startswith("_") or low.endswith(".comments"):
            continue

        subdirs.append(name)

    subdirs.sort(key=lambda s: s.lower())

    rows = [[InlineKeyboardButton(f"📁 {name}", callback_data=f"vip_move_open|{name}")] for name in subdirs]
    ctrl = []
    if path:
        ctrl.append(InlineKeyboardButton("⬅️ Назад (вгору)", callback_data="vip_move_up"))
    ctrl.append(InlineKeyboardButton("✅ Обрати тут", callback_data="vip_move_choose_here"))
    rows.append(ctrl)
    rows.append([InlineKeyboardButton("❎ Скасувати", callback_data=f"vip_edit|{idx}")])
    return InlineKeyboardMarkup(rows)

# --- ПУБЛІЧНІ ХЕНДЛЕРИ (ONE-MESSAGE FLOW) ---

async def vip_edit_move_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Старт меню перенесення тесту (ONE-MESSAGE).
    Зберігає item у context.user_data['vip_move_item'] та idx у 'vip_move_idx'.
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

    # Перевіряємо право власника
    owners = _load_owners()
    rel = items[idx]["rel"]
    meta = owners.get(rel) or {}
    owner_id = meta.get("owner_id")
    if owner_id != query.from_user.id:
        await query.message.reply_text("🔒 Лише власник може переносити тест в інший розділ.")
        return

    # зберігаємо стан «move»
    context.user_data["vip_move_item"] = items[idx]
    context.user_data["vip_move_browse_path"] = []
    context.user_data["vip_move_idx"] = idx
    _set_move_msg(context, query.message.message_id, query.message.chat_id)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗂 Обрати наявний розділ", callback_data=f"vip_move_pick|{idx}")],
        [InlineKeyboardButton("❎ Скасувати", callback_data=f"vip_edit|{idx}")],
    ])
    await _edit_move_panel(
        update, context,
        "ℹ️ Якщо потрібного розділу ще немає — спочатку створіть його у дереві тестів, "
        "потім поверніться сюди й перемістіть тест.\n\n"
        "Що робимо зараз?",
        kb
    )

async def vip_move_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відкрити браузер тек для вибору цільового розділу (ONE-MESSAGE)."""
    query = update.callback_query
    await query.answer()

    # фіксуємо повідомлення панелі
    _set_move_msg(context, query.message.message_id, query.message.chat_id)

    path = context.user_data.get("vip_move_browse_path") or []
    idx = context.user_data.get("vip_move_idx", 0)
    kb = _move_browser_kb(path, idx)
    await _edit_move_panel(update, context, "📂 Оберіть цільовий розділ:", kb)

async def vip_move_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відкрити підпапку в режимі перенесення (ONE-MESSAGE)."""
    query = update.callback_query
    await query.answer()

    name = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    path = context.user_data.get("vip_move_browse_path") or []
    path.append(name)
    context.user_data["vip_move_browse_path"] = path

    _set_move_msg(context, query.message.message_id, query.message.chat_id)

    idx = context.user_data.get("vip_move_idx", 0)
    kb = _move_browser_kb(path, idx)
    await _edit_move_panel(update, context, "📂 Оберіть цільовий розділ:", kb)

async def vip_move_up(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Піднятись вгору в режимі перенесення (ONE-MESSAGE)."""
    query = update.callback_query
    await query.answer()

    path = context.user_data.get("vip_move_browse_path") or []
    if path:
        path.pop()
    context.user_data["vip_move_browse_path"] = path

    _set_move_msg(context, query.message.message_id, query.message.chat_id)

    idx = context.user_data.get("vip_move_idx", 0)
    kb = _move_browser_kb(path, idx)
    await _edit_move_panel(update, context, "📂 Оберіть цільовий розділ:", kb)

async def vip_move_choose_here(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Підтвердження вибору поточної теки і саме перенесення:
      - переносимо JSON
      - переносимо теки картинок (<name>, #<name>, _<name>)
      - переносимо comments (<name>.comments)
      - переносимо docx і docx.meta
      - оновлюємо _owners.json ключ (rel)
      - оновлюємо каталоги
      - чистимо порожні теки уверх до TESTS_ROOT
      - редагуємо поточне повідомлення панелі на фінальний результат
      - БЕЗ додаткових reply у чат (залишаємося в тому ж меню)
    """
    query = update.callback_query
    await query.answer()

    item = context.user_data.get("vip_move_item")
    idx = context.user_data.get("vip_move_idx", 0)
    if not item:
        await query.message.reply_text("⚠️ Немає активного файлу для збереження.")
        return

    name = item["name"]
    old_path = item["abs_path"]
    old_dir  = item["abs_dir"]

    path = context.user_data.get("vip_move_browse_path") or []
    new_dir = os.path.join(TESTS_ROOT, *path) if path else TESTS_ROOT
    os.makedirs(new_dir, exist_ok=True)
    new_path = os.path.join(new_dir, f"{name}.json")

    # фіксуємо повідомлення панелі
    _set_move_msg(context, query.message.message_id, query.message.chat_id)

    if os.path.exists(new_path):
        kb = _move_browser_kb(path, idx)
        await _edit_move_panel(update, context, "⚠️ У вибраній теці вже існує файл із такою назвою. Оберіть інший розділ.", kb)
        return

    owners = _load_owners()
    old_rel = _relative_to_tests(old_path)
    meta = owners.get(old_rel) or {}
    if meta.get("owner_id") != query.from_user.id:
        await query.message.reply_text("🔒 Лише власник може переносити тест в інший розділ.")
        return

    # 1) JSON
    try:
        shutil.move(old_path, new_path)
    except Exception as e:
        kb = _move_browser_kb(path, idx)
        await _edit_move_panel(update, context, f"❌ Не вдалося перемістити файл: {e}", kb)
        return

    # 2) теки картинок
    for img_dir_name in (name, f"#{name}", f"_{name}"):
        src = os.path.join(old_dir, img_dir_name)
        dst = os.path.join(new_dir, img_dir_name)
        try:
            if os.path.isdir(src):
                if os.path.exists(dst):
                    _safe_rmtree(dst)
                shutil.move(src, dst)
        except Exception as e:
            logger.warning("Move images folder failed: %s", e)

    # 3) comments
    src_comments = os.path.join(old_dir, f"{name}.comments")
    dst_comments = os.path.join(new_dir, f"{name}.comments")
    try:
        if os.path.isdir(src_comments):
            if os.path.exists(dst_comments):
                _safe_rmtree(dst_comments)
            shutil.move(src_comments, dst_comments)
    except Exception as e:
        logger.warning("Move comments folder failed: %s", e)

    # 4) docx/meta
    safe = _safe_filename(name)
    for fn in (f"{safe}.docx", f"{safe}.docx.meta.json"):
        src = os.path.join(old_dir, fn)
        dst = os.path.join(new_dir, fn)
        try:
            if os.path.exists(src):
                shutil.move(src, dst)
        except Exception as e:
            logger.warning("Move export file failed: %s", e)

    # 5) owners
    new_rel = _relative_to_tests(new_path)
    owners[new_rel] = meta
    owners.pop(old_rel, None)
    _save_owners(owners)

    # 6) каталоги (перезбір дерева щоб головне меню/браузер оновились у пам'яті)
    try:
        context.bot_data["tests_catalog"] = discover_tests(TESTS_ROOT)
        context.bot_data["tests_tree"] = discover_tests_hierarchy(TESTS_ROOT)
    except Exception:
        _refresh_catalogs(context)

    # 7) прибираємо порожні теки уверх до TESTS_ROOT
    try:
        _cleanup_empty_dirs(old_dir)
    except Exception as e:
        logger.warning("Cleanup upward failed: %s", e)

    # Очистка стану MOVE (ID повідомлення залишаємо, щоб лишитись у цьому ж екрані)
    for k in ("vip_move_item", "vip_move_browse_path"):
        context.user_data.pop(k, None)
    # idx лишаємо для кнопки «Назад до редагування»
    # context.user_data["vip_move_idx"] збережено навмисно

    # Фінальне оновлення ТІЄЇ Ж панелі (ONE-MESSAGE) — без додаткових reply у чат
    final_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад до редагування", callback_data=f"vip_edit|{idx}")]
    ])
    await _edit_move_panel(
        update, context,
        f"✅ Тест «{name}» переміщено у: `/{new_rel}`.\n"
        "Усі пов’язані файли та папки також перенесено.\n"
        "Порожні старі розділи прибрано до кореня tests/.",
        final_kb
    )
