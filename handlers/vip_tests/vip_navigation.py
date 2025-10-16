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

# ===== Helpers for single control-message UI =====

def _set_ctrl_from_query(context: ContextTypes.DEFAULT_TYPE, query) -> None:
    """
    Запам'ятати керуюче повідомлення (chat_id, message_id) на базі поточного callback'а.
    """
    context.user_data["vip_ctrl"] = {
        "chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
    }

def _get_ctrl(context: ContextTypes.DEFAULT_TYPE):
    """
    Повернути (chat_id, message_id) керуючого повідомлення, якщо воно відоме.
    """
    data = context.user_data.get("vip_ctrl") or {}
    cid = data.get("chat_id")
    mid = data.get("message_id")
    if isinstance(cid, int) and isinstance(mid, int):
        return cid, mid
    return None, None

async def _edit_ctrl_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    """
    Редагувати текст/клавіатуру керуючого повідомлення. Якщо немає ctrl — використати query.message.
    """
    query = update.callback_query if update and update.callback_query else None
    chat_id, message_id = _get_ctrl(context)
    if chat_id and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            # якщо редагування не вдалось (видалили або ін.) — впадемо у fallback
            pass

    # fallback: редагуємо поточне повідомлення та синхронізуємо ctrl
    if query and query.message:
        _set_ctrl_from_query(context, query)
        try:
            await query.message.edit_text(text=text, reply_markup=reply_markup)
            return
        except Exception:
            # останній шанс — просто відповісти новим і зробити його контролем
            m = await query.message.reply_text(text=text, reply_markup=reply_markup)
            context.user_data["vip_ctrl"] = {"chat_id": m.chat_id, "message_id": m.message_id}
            return

    # якщо прийшли з текстового апдейту (без query) і немає ctrl
    if update and update.message:
        m = await update.message.reply_text(text=text, reply_markup=reply_markup)
        context.user_data["vip_ctrl"] = {"chat_id": m.chat_id, "message_id": m.message_id}

def _sanitize_folder_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if any(ch in ILLEGAL_WIN_CHARS for ch in name):
        return ""
    if name.startswith("📁 ") or name.startswith("➕ "):
        return ""
    return name

def _where_str(path_list) -> str:
    return (os.path.join(*path_list) if path_list else "/").replace("\\", "/")

# ====== Navigation (single-message) ======

async def vip_choose_folder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # зафіксувати control-message на цей callback
    _set_ctrl_from_query(context, query)

    context.user_data["vip_browse_path"] = []
    where = _where_str([])
    await _edit_ctrl_text(
        update, context,
        text=f"📂 Оберіть цільовий розділ:\n\n<b>{where}</b>",
        reply_markup=_folder_browser_kb(context.user_data["vip_browse_path"])
    )

async def vip_nav_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|", 1)
    if len(parts) != 2:
        return
    name = parts[1].strip()
    path = list(context.user_data.get("vip_browse_path", [])) + [name]
    context.user_data["vip_browse_path"] = path
    where = _where_str(path)
    await _edit_ctrl_text(
        update, context,
        text=f"📂 {where}",
        reply_markup=_folder_browser_kb(path)
    )

async def vip_nav_up(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    path = list(context.user_data.get("vip_browse_path", []))
    if path:
        path.pop()
    context.user_data["vip_browse_path"] = path
    where = _where_str(path)
    await _edit_ctrl_text(
        update, context,
        text=f"📂 {where}",
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
            await _edit_ctrl_text(
                update, context,
                text="⚠️ У вибраній теці файл з такою назвою вже існує. Оберіть іншу теку.\n\n"
                     f"📂 {_where_str(path)}",
                reply_markup=_folder_browser_kb(path)
            )
            return

        import json
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            await _edit_ctrl_text(update, context, text=f"❌ Не вдалося записати файл: {e}")
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
            pass

        # Оновити каталоги/дерево
        try:
            _refresh_catalogs(context)
        except Exception:
            pass

        # під ZIP
        context.user_data["vip_images_dir"] = os.path.join(abs_dir, name)
        context.user_data["awaiting_vip_images"] = True
        for k in ("vip_pending", "awaiting_vip_json"):
            context.user_data.pop(k, None)

        rel_pretty = os.path.relpath(json_path, TESTS_ROOT).replace("\\", "/")
        await _edit_ctrl_text(
            update, context,
            text=(
                f"✅ Збережено: /{rel_pretty}\n\n"
                "🖼 Додати архів з картинками для цього тесту?"
            ),
            reply_markup=_images_prompt_kb()
        )
        return

    # --- ПЕРЕМІЩЕННЯ (релокація) ІСНУЮЧОГО ТЕСТУ ---
    if relocate:
        src_json = relocate.get("src_json")
        name = relocate.get("name")
        if not src_json or not os.path.isfile(src_json):
            await _edit_ctrl_text(update, context, text="⚠️ Немає активного файлу для збереження.")
            return

        dst_json = os.path.join(abs_dir, f"{name}.json")
        if os.path.exists(dst_json):
            await _edit_ctrl_text(
                update, context,
                text="⚠️ У вибраній теці файл з такою назвою вже існує. Оберіть іншу теку.\n\n"
                     f"📂 {_where_str(path)}",
                reply_markup=_folder_browser_kb(path)
            )
            return

        import shutil
        try:
            shutil.move(src_json, dst_json)
        except Exception as e:
            await _edit_ctrl_text(update, context, text=f"❌ Не вдалося перемістити JSON: {e}")
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
        await _edit_ctrl_text(update, context, text=f"✅ Тест «{name}» переміщено до /{rel_dir}")
        return

    await _edit_ctrl_text(update, context, text="ℹ️ Немає активної операції для збереження тут.")

async def vip_create_root(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # зафіксувати control-message
    _set_ctrl_from_query(context, query)
    context.user_data["awaiting_vip_root_folder_name"] = True
    await _edit_ctrl_text(
        update, context,
        text="📁 Введіть назву нового розділу у корені (або «⬅️ Назад» для скасування):"
    )

async def vip_handle_root_folder_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_vip_root_folder_name"):
        return
    text = (update.message.text or "").strip()
    if text in {"⬅️ Назад", "🔙 Назад"}:
        context.user_data.pop("awaiting_vip_root_folder_name", None)
        await _edit_ctrl_text(update, context, text="❎ Скасовано створення розділу.")
        return

    name = (text or "").strip()
    if not name or any(ch in ILLEGAL_WIN_CHARS for ch in name) or name.startswith(("📁 ", "➕ ")):
        await _edit_ctrl_text(
            update, context,
            text="❌ Невірна назва. Заборонені символи: <>:\"/\\|?*\nВведіть іншу, або «⬅️ Назад»."
        )
        return

    abs_dir = os.path.join(TESTS_ROOT, name)
    try:
        os.makedirs(abs_dir, exist_ok=False)
        await _edit_ctrl_text(update, context, text=f"✅ Розділ «{name}» створено у корені.")
    except FileExistsError:
        await _edit_ctrl_text(update, context, text="ℹ️ Така папка вже існує.")
    finally:
        context.user_data.pop("awaiting_vip_root_folder_name", None)
