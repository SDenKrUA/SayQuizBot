import os
import shutil
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_storage import (
    _load_owners, _save_owners, _relative_to_tests, _refresh_catalogs, _cleanup_empty_dirs
)
from .vip_ui import _images_prompt_kb

logger = logging.getLogger("test_bot")

async def vip_rewrite_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    target = items[idx]
    context.user_data["vip_rewrite_target"] = target
    context.user_data["awaiting_vip_rewrite"] = True
    await query.message.reply_text(
        f"✏️ Перезапис тесту **{target['name']}**.\n"
        "Надішліть новий файл JSON для цього тесту."
    )

async def vip_dup_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    dup = context.user_data.get("vip_dup") or {}
    rel = dup.get("rel") or "?"
    await query.message.reply_text(
        f"📁 Тест розміщено тут: `/{rel}`\nПерейдіть у дерево розділів, щоб відкрити його.",
    )

async def vip_dup_replace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if "vip_dup" not in context.user_data:
        await query.message.reply_text("⚠️ Немає активного дубліката.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Та сама директорія", callback_data="vip_replace_same")],
        [InlineKeyboardButton("🗂 Обрати інший розділ", callback_data="vip_replace_other")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="vip_cancel")],
    ])
    await query.message.reply_text("Де зберегти нову версію тесту?", reply_markup=kb)

async def vip_replace_same(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import json
    query = update.callback_query
    await query.answer()
    dup = context.user_data.get("vip_dup") or {}
    old_path = dup.get("old_path")
    name = dup.get("name")
    data = dup.get("data")
    old_dir = dup.get("old_dir")

    if not old_path or not os.path.exists(old_path):
        await query.message.reply_text("❌ Не знайшов старий файл для перезапису.")
        return

    try:
        with open(old_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        await query.message.reply_text(f"❌ Не вдалося перезаписати файл: {e}")
        return

    _refresh_catalogs(context)

    # Прибираємо стани
    for k in ("vip_dup", "vip_pending", "awaiting_vip_json"):
        context.user_data.pop(k, None)

    # пропозиція ZIP
    if old_dir and name:
        context.user_data["awaiting_vip_images"] = True
        context.user_data["vip_images_dir"] = os.path.join(old_dir, name)
        await query.message.reply_text(
            "🖼 Додати/оновити архів з картинками для цього тесту?",
            reply_markup=_images_prompt_kb()
        )

    # Автоприбирання порожніх тек (раптом стало порожньо)
    if old_dir:
        _cleanup_empty_dirs(old_dir)

    await query.message.reply_text(f"✅ Тест **{name}** оновлено у тій самій директорії.")

async def vip_replace_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if "vip_dup" not in context.user_data:
        await query.message.reply_text("⚠️ Немає активного дубліката.")
        return
    context.user_data["vip_replace_move"] = True
    context.user_data["vip_browse_path"] = []
    from .vip_ui import _folder_browser_kb
    kb = _folder_browser_kb(context.user_data["vip_browse_path"])
    await query.message.reply_text("Оберіть новий розділ для переміщення тесту:", reply_markup=kb)

async def _handle_replace_move_choose_here(query, context):
    import json
    from .vip_constants import TESTS_ROOT

    dup = context.user_data.get("vip_dup") or {}
    name = dup.get("name")
    data = dup.get("data")
    old_path = dup.get("old_path")
    old_dir = dup.get("old_dir")

    if not (name and data and old_path and old_dir):
        await query.message.reply_text("❌ Неповні дані для переміщення.")
        return

    path = context.user_data.get("vip_browse_path", [])
    new_dir = os.path.join(TESTS_ROOT, *path) if path else TESTS_ROOT
    os.makedirs(new_dir, exist_ok=True)
    new_path = os.path.join(new_dir, f"{name}.json")

    if os.path.exists(new_path):
        await query.message.reply_text("⚠️ У вибраній теці файл з такою назвою вже існує. Оберіть іншу теку.")
        return

    try:
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        await query.message.reply_text(f"❌ Не вдалося записати новий файл: {e}")
        return

    # Перемістимо папку з картинками <old_dir>/<name> → <new_dir>/<name>
    old_images = os.path.join(old_dir, name)
    new_images = os.path.join(new_dir, name)
    try:
        if os.path.isdir(old_images):
            if os.path.exists(new_images):
                shutil.rmtree(new_images, ignore_errors=True)
            shutil.move(old_images, new_images)
    except Exception as e:
        logger.warning("Move images folder failed: %s", e)

    try:
        if os.path.exists(old_path):
            os.remove(old_path)
    except Exception as e:
        logger.warning("Remove old JSON failed: %s", e)

    owners = _load_owners()
    old_key = _relative_to_tests(old_path)
    new_key = _relative_to_tests(new_path)
    meta = owners.pop(old_key, {"owner_id": query.from_user.id, "trusted": []})
    owners[new_key] = meta
    _save_owners(owners)

    _refresh_catalogs(context)

    # запропонувати ZIP у новому місці
    context.user_data["awaiting_vip_images"] = True
    context.user_data["vip_images_dir"] = os.path.join(new_dir, name)
    await query.message.reply_text(
        "🖼 Додати архів з картинками для цього тесту тут?",
        reply_markup=_images_prompt_kb()
    )

    # Автоприбирання порожніх тек догори
    _cleanup_empty_dirs(old_dir)

    for k in ("vip_dup", "vip_browse_path", "vip_replace_move", "vip_pending", "awaiting_vip_json"):
        context.user_data.pop(k, None)

    await query.message.reply_text(
        f"✅ Тест **{name}** переміщено у: `/{new_key}`.\n"
        "Зображення (якщо були) також перенесені."
    )
