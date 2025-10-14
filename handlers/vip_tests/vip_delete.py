import os
import stat
import shutil
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_storage import _load_owners, _save_owners, _refresh_catalogs, _cleanup_empty_dirs
from utils.export_docx import _safe_filename
from utils.loader import IGNORED_JSON_SUFFIXES

def _remove_file(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass

def _rmtree_force(path: str) -> None:
    """Більш агресивне видалення дерева (Windows-friendly)."""
    if not os.path.isdir(path):
        return

    def onerror(func, p, exc_info):
        try:
            # Знімаємо read-only і пробуємо ще раз
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onerror=onerror)
    except Exception:
        # Остання спроба: якщо спорожніло — приберемо
        try:
            if not os.listdir(path):
                os.rmdir(path)
        except Exception:
            pass

def _dir_has_any_test_json(abs_dir: str) -> bool:
    """
    True, якщо в теці є ХОЧ ОДИН .json, що НЕ має службового суфікса (тобто це тест).
    Перевіряємо лише поточну теку, без піддиректорій.
    """
    try:
        for fname in os.listdir(abs_dir):
            if not fname.lower().endswith(".json"):
                continue
            if any(fname.lower().endswith(suf) for suf in IGNORED_JSON_SUFFIXES):
                continue
            return True
    except Exception:
        pass
    return False

async def vip_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    context.user_data["vip_delete_idx"] = idx
    name = items[idx]["name"]
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Так, видалити", callback_data="vip_delete_confirm|yes"),
            InlineKeyboardButton("❎ Скасувати", callback_data="vip_delete_confirm|no"),
        ]
    ])
    await query.message.reply_text(f"🗑 Підтвердити видалення тесту **{name}**?", reply_markup=kb)

async def vip_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    choice = (query.data.split("|", 1)[1] if "|" in query.data else "no").strip()
    idx = context.user_data.pop("vip_delete_idx", None)
    items = context.user_data.get("vip_mytests") or []
    if idx is None or not (0 <= idx < len(items)):
        await query.message.reply_text("⚠️ Немає вибраного тесту.")
        return

    item = items[idx]
    name = item["name"]
    abs_path = item["abs_path"]    # JSON тесту
    abs_dir  = item["abs_dir"]     # тека розділу, де лежить JSON (наприклад tests/Test/test1)
    rel      = item["rel"]

    if choice != "yes":
        await query.message.reply_text("❎ Видалення скасовано.")
        return

    # 1) Видаляємо JSON тесту
    _remove_file(abs_path)

    # 2) Повністю видаляємо теки картинок тесту: <abs_dir>/<name>, #<name>, _<name>
    for img_dir_name in (name, f"#{name}", f"_{name}"):
        _rmtree_force(os.path.join(abs_dir, img_dir_name))

    # 3) Прибираємо службові артефакти DOCX, якщо вони були згенеровані
    safe = _safe_filename(name)
    _remove_file(os.path.join(abs_dir, f"{safe}.docx"))
    _remove_file(os.path.join(abs_dir, f"{safe}.docx.meta.json"))

    # 4) Приберемо можливі службові підтеки типу "<test>.comments"
    _rmtree_force(os.path.join(abs_dir, f"{name}.comments"))

    # 5) Якщо в цій теці НЕ залишилось жодного звичайного тестового JSON — зносимо сам розділ повністю
    try:
        if os.path.isdir(abs_dir) and not _dir_has_any_test_json(abs_dir):
            _rmtree_force(abs_dir)
    except Exception:
        pass

    # 6) Очищаємо реєстр власників
    owners = _load_owners()
    owners.pop(rel, None)
    _save_owners(owners)

    # 7) ПІСЛЯ жорсткого видалення — підчищаємо порожні каталоги вгору
    #    (спочатку від каталогу тесту, потім гарантовано ще від його батьківського)
    _cleanup_empty_dirs(abs_dir)
    _cleanup_empty_dirs(os.path.dirname(abs_dir))

    # 8) І тільки ТЕПЕР оновлюємо каталоги/дерево
    _refresh_catalogs(context)

    await query.message.reply_text(f"🗑 Тест **{name}** видалено.")
