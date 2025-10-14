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
from utils.loader import IGNORED_JSON_SUFFIXES, discover_tests, discover_tests_hierarchy, build_listing_for_path
from utils.keyboards import browse_menu

logger = logging.getLogger("test_bot.vip_move")

# --- Допоміжне ---

def _is_test_json(filename: str) -> bool:
    """
    True, якщо це звичайний тестовий JSON (без службових суфіксів).
    """
    if not filename.lower().endswith(".json"):
        return False
    low = filename.lower()
    for suf in IGNORED_JSON_SUFFIXES:
        if low.endswith(suf):
            return False
    return True

def _tree_has_any_useful_files(root_dir: str) -> bool:
    """
    Перевіряє, чи є у піддереві root_dir:
      - хоч один "тестовий" JSON (не службовий),
      - або будь-які інші файли.
    Якщо нічого — False (можна видаляти як порожнє дерево).
    """
    try:
        for _cur, _dirs, files in os.walk(root_dir):
            for fn in files:
                if _is_test_json(fn):
                    return True
                # будь-який файл також означає «не порожньо»
                return True
        return False
    except Exception:
        # обережність: краще не видаляти, якщо сталася помилка
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

def _is_empty_dir(path: str) -> bool:
    try:
        return os.path.isdir(path) and len(os.listdir(path)) == 0
    except Exception:
        return False

def _prune_empty_branch_up_to_root(start_dir: str) -> None:
    """
    Підіймається вгору від start_dir і видаляє ВСІ порожні теки,
    доки не дійде до TESTS_ROOT (його не чіпає).
    """
    try:
        cur = start_dir
        tests_root_abs = os.path.abspath(TESTS_ROOT)
        while True:
            if not os.path.isdir(cur):
                break
            # якщо не порожньо — зупиняємось
            try:
                if os.listdir(cur):
                    break
            except Exception:
                break

            # порожня тека — видаляємо
            try:
                os.rmdir(cur)
            except Exception:
                # на випадок прав — спробуємо агресивно
                _safe_rmtree(cur)

            parent = os.path.dirname(cur)
            if not parent or os.path.abspath(parent) == tests_root_abs or parent == cur:
                break
            cur = parent
    except Exception as e:
        logger.warning("Prune upward failed: %s", e)

# --- Локальний браузер тек для режиму «перемістити тест» (свій префікс) ---

def _move_browser_kb(path):
    """
    Браузер тек для релокації:
      - показує лише «справжні» розділи;
      - ховає папки-картинки:
          * назва каталогу збігається з base-name будь-якого тестового JSON у тій самій теці,
          * або починається з '#' / '_' (альтернативні каталоги зображень),
          * або закінчується на '.comments'.
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
        ctrl.append(InlineKeyboardButton("⬆️ Назад", callback_data="vip_move_up"))
    ctrl.append(InlineKeyboardButton("✅ Обрати тут", callback_data="vip_move_choose_here"))
    rows.append(ctrl)
    return InlineKeyboardMarkup(rows)

# --- ПУБЛІЧНІ ХЕНДЛЕРИ ---

async def vip_edit_move_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Старт меню перенесення тесту.
    Зберігає item у context.user_data['vip_move_item'] і показує короткі інструкції.
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

    context.user_data["vip_move_item"] = items[idx]
    context.user_data["vip_move_browse_path"] = []

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📁 Розділ існує", callback_data=f"vip_move_pick|{idx}")],
        [InlineKeyboardButton("➕ Створити розділ", callback_data=f"vip_edit|{idx}")],
    ])
    await query.message.reply_text(
        "ℹ️ Якщо потрібного розділу ще немає — спочатку створіть його у дереві тестів, "
        "потім поверніться сюди й перемістіть тест.\n\n"
        "Що робимо зараз?",
        reply_markup=kb
    )

async def vip_move_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відкрити браузер тек для вибору цільового розділу перенесення."""
    query = update.callback_query
    await query.answer()
    context.user_data["vip_move_browse_path"] = context.user_data.get("vip_move_browse_path") or []
    kb = _move_browser_kb(context.user_data["vip_move_browse_path"])
    await query.message.reply_text("Оберіть цільовий розділ:", reply_markup=kb)

async def vip_move_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відкрити підпапку в режимі перенесення (клік по '📁 name')."""
    query = update.callback_query
    await query.answer()
    name = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    path = context.user_data.get("vip_move_browse_path") or []
    path.append(name)
    context.user_data["vip_move_browse_path"] = path
    kb = _move_browser_kb(path)
    await query.message.reply_text("Оберіть цільовий розділ:", reply_markup=kb)

async def vip_move_up(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Піднятись вгору в режимі перенесення."""
    query = update.callback_query
    await query.answer()
    path = context.user_data.get("vip_move_browse_path") or []
    if path:
        path.pop()
    context.user_data["vip_move_browse_path"] = path
    kb = _move_browser_kb(path)
    await query.message.reply_text("Оберіть цільовий розділ:", reply_markup=kb)

async def vip_move_choose_here(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Підтвердження вибору поточної теки і саме перенесення:
      - переносимо JSON
      - переносимо теки картинок (<name>, #<name>, _<name>)
      - переносимо comments (<name>.comments)
      - переносимо docx і docx.meta
      - оновлюємо _owners.json ключ (rel)
      - оновлюємо каталоги
      - видаляємо порожню гілку директорій уверх до TESTS_ROOT
      - відразу надсилаємо ОНОВЛЕНУ клавіатуру дерева тестів
    """
    query = update.callback_query
    await query.answer()

    item = context.user_data.get("vip_move_item")
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

    if os.path.exists(new_path):
        await query.message.reply_text("⚠️ У вибраній теці вже існує файл із такою назвою. Оберіть інший розділ.")
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
        await query.message.reply_text(f"❌ Не вдалося перемістити файл: {e}")
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

    # 6) каталоги (перезбір дерева щоб головне меню/браузер оновились)
    try:
        context.bot_data["tests_catalog"] = discover_tests(TESTS_ROOT)
        context.bot_data["tests_tree"] = discover_tests_hierarchy(TESTS_ROOT)
    except Exception:
        _refresh_catalogs(context)

    # 7) прибираємо порожню гілку уверх до TESTS_ROOT
    try:
        # old_dir міг спорожніти; приберемо його і всіх порожніх батьків до tests/
        _prune_empty_branch_up_to_root(old_dir)
    except Exception as e:
        logger.warning("Prune empty branch upward failed: %s", e)

    # Очистка стану
    for k in ("vip_move_item", "vip_move_browse_path"):
        context.user_data.pop(k, None)

    # 8) оновимо клавіатуру дерева тестів, якщо користувач у браузері
    try:
        tree = context.bot_data.get("tests_tree")
        if not tree:
            tree = discover_tests_hierarchy(TESTS_ROOT)
            context.bot_data["tests_tree"] = tree

        path = context.user_data.get("browse_path", [])
        cur_path = list(path)
        while True:
            subfolders, tests, _ = build_listing_for_path(tree, cur_path)
            if subfolders is not None:
                break
            if not cur_path:
                break
            cur_path.pop()

        header = "📂 Оберіть розділ або тест"
        if cur_path != path:
            context.user_data["browse_path"] = cur_path
        await query.message.reply_text(header, reply_markup=browse_menu(cur_path, subfolders, tests))
    except Exception as e:
        logger.warning("Failed to send refreshed browse keyboard: %s", e)

    await query.message.reply_text(
        f"✅ Тест «{name}» переміщено у: `/{new_rel}`.\n"
        "Усі пов’язані файли та папки також перенесено.\n"
        "Порожні старі розділи повністю прибрано до кореня tests/."
    )
