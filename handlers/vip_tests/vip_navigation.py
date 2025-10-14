# handlers/vip_tests/vip_navigation.py
import os
from telegram import Update
from telegram.ext import ContextTypes

from .vip_constants import TESTS_ROOT, ILLEGAL_WIN_CHARS
from .vip_ui import _folder_browser_kb, _images_prompt_kb
from .vip_storage import (
    _relative_to_tests,
    _load_owners,
    _save_owners,
    _refresh_catalogs,
    save_meta_for_rel,
)

def _sanitize_folder_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if any(ch in ILLEGAL_WIN_CHARS for ch in name):
        return ""
    if name.startswith("📁 ") or name.startswith("➕ "):
        return ""
    return name

async def vip_choose_folder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["vip_browse_path"] = []
    await query.message.reply_text(
        "📂 Оберіть цільовий розділ:",
        reply_markup=_folder_browser_kb(context.user_data["vip_browse_path"])
    )

async def vip_nav_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|", 1)
    if len(parts) != 2:
        return
    name = parts[1].strip()
    path = context.user_data.get("vip_browse_path", [])
    path = list(path) + [name]
    context.user_data["vip_browse_path"] = path
    where = os.path.join(*path) if path else "/"
    await query.message.reply_text(
        f"📂 {where}",
        reply_markup=_folder_browser_kb(path)
    )

async def vip_nav_up(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    path = context.user_data.get("vip_browse_path", [])
    if path:
        path.pop()
    context.user_data["vip_browse_path"] = path
    where = os.path.join(*path) if path else "/"
    await query.message.reply_text(
        f"📂 {where}",
        reply_markup=_folder_browser_kb(path)
    )

async def vip_choose_here(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    path = context.user_data.get("vip_browse_path", [])
    abs_dir = os.path.join(TESTS_ROOT, *path) if path else TESTS_ROOT
    os.makedirs(abs_dir, exist_ok=True)

    pending = context.user_data.get("vip_pending")
    relocate = context.user_data.get("vip_relocate_ctx")

    # --- СТВОРЕННЯ НОВОГО ТЕСТУ З VIP-ЗАВАНТАЖЕННЯ ---
    if pending:
        name = pending["name"]
        data = pending["data"]
        json_path = os.path.join(abs_dir, f"{name}.json")

        if os.path.exists(json_path):
            await query.message.reply_text("⚠️ У вибраній теці файл з такою назвою вже існує. Оберіть іншу теку.")
            await query.message.reply_text("📂 Оберіть інший розділ:", reply_markup=_folder_browser_kb(path))
            return

        import json
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            await query.message.reply_text(f"❌ Не вдалося записати файл: {e}")
            return

        # ✅ ЗАПИСАТИ ВЛАСНИКА ТЕСТУ В _owners.json
        try:
            rel_key = _relative_to_tests(json_path)
            save_meta_for_rel(rel_key, {
                "owner_id": query.from_user.id,
                "trusted": [],
                "trusted_usernames": [],
                "pending": [],
            })
        except Exception:
            # без паніки, просто продовжимо — але тест може не з’явитись у «Мої тести»
            pass

        # Оновити каталоги/дерево, аби тест одразу з’явився у меню/офісі
        try:
            _refresh_catalogs(context)
        except Exception:
            pass

        # під ZIP
        context.user_data["vip_images_dir"] = os.path.join(abs_dir, name)
        context.user_data["awaiting_vip_images"] = True
        for k in ("vip_pending", "awaiting_vip_json"):
            context.user_data.pop(k, None)

        rel_pretty = os.path.relpath(json_path, TESTS_ROOT)
        rel_pretty = rel_pretty.replace("\\", "/")
        await query.message.reply_text(f"✅ Збережено: /{rel_pretty}")
        await query.message.reply_text("🖼 Додати архів з картинками для цього тесту?", reply_markup=_images_prompt_kb())
        return

    # --- ПЕРЕМІЩЕННЯ (релокація) ІСНУЮЧОГО ТЕСТУ ---
    if relocate:
        src_json = relocate.get("src_json")
        name = relocate.get("name")
        if not src_json or not os.path.isfile(src_json):
            await query.message.reply_text("⚠️ Немає активного файлу для збереження.")
            return

        dst_json = os.path.join(abs_dir, f"{name}.json")
        if os.path.exists(dst_json):
            await query.message.reply_text("⚠️ У вибраній теці файл з такою назвою вже існує. Оберіть іншу теку.")
            await query.message.reply_text("📂 Оберіть інший розділ:", reply_markup=_folder_browser_kb(path))
            return

        import shutil
        try:
            shutil.move(src_json, dst_json)
        except Exception as e:
            await query.message.reply_text(f"❌ Не вдалося перемістити JSON: {e}")
            return

        # картинки
        try:
            old_images = os.path.join(os.path.dirname(src_json), name)
            new_images = os.path.join(abs_dir, name)
            if os.path.isdir(old_images):
                if os.path.exists(new_images):
                    shutil.rmtree(new_images, ignore_errors=True)
                shutil.move(old_images, new_images)
        except Exception:
            pass

        # супутні файли
        try:
            src_dir = os.path.dirname(src_json)
            base = name
            for fn in (f"{base}.docx", f"{base}.docx.meta.json", f"{base}.comments"):
                p = os.path.join(src_dir, fn)
                if os.path.isdir(p):
                    shutil.move(p, os.path.join(abs_dir, fn))
                elif os.path.isfile(p):
                    shutil.move(p, os.path.join(abs_dir, fn))
        except Exception:
            pass

        # оновити owners і каталоги
        try:
            owners = _load_owners()
            old_key = _relative_to_tests(src_json)
            new_key = _relative_to_tests(dst_json)
            meta = owners.pop(old_key, owners.get(old_key, {}))
            owners[new_key] = meta
            _save_owners(owners)
            _refresh_catalogs(context)
        except Exception:
            pass

        for k in ("vip_browse_path", "vip_relocate_ctx"):
            context.user_data.pop(k, None)

        rel_dir = os.path.relpath(abs_dir, TESTS_ROOT).replace("\\", "/")
        await query.message.reply_text(f"✅ Тест «{name}» переміщено до /{rel_dir}")
        return

    await query.message.reply_text("ℹ️ Немає активної операції для збереження тут.")

async def vip_create_root(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_vip_root_folder_name"] = True
    await query.message.reply_text("📁 Введіть назву нового розділу у корені (або «⬅️ Назад» для скасування):")

async def vip_handle_root_folder_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_vip_root_folder_name"):
        return
    text = (update.message.text or "").strip()
    if text in {"⬅️ Назад", "🔙 Назад"}:
        context.user_data.pop("awaiting_vip_root_folder_name", None)
        await update.message.reply_text("❎ Скасовано створення розділу.")
        return

    name = (text or "").strip()
    if not name or any(ch in ILLEGAL_WIN_CHARS for ch in name) or name.startswith(("📁 ", "➕ ")):
        await update.message.reply_text("❌ Невірна назва. Заборонені символи: <>:\"/\\|?*\nВведіть іншу, або «⬅️ Назад».")
        return

    abs_dir = os.path.join(TESTS_ROOT, name)
    try:
        os.makedirs(abs_dir, exist_ok=False)
        await update.message.reply_text(f"✅ Розділ «{name}» створено у корені.")
    except FileExistsError:
        await update.message.reply_text("ℹ️ Така папка вже існує.")
    finally:
        context.user_data.pop("awaiting_vip_root_folder_name", None)
