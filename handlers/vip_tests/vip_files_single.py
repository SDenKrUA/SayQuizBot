# handlers/vip_tests/vip_files_single.py
import os
import shutil
import logging
from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ApplicationHandlerStop  # ✅

from .vip_constants import TESTS_ROOT
from .vip_storage import _refresh_catalogs
from .vip_utils import (
    IMAGE_EXTS, AUDIO_EXTS, VIDEO_EXTS, DOC_EXTS,
    _compress_image_bytes, _canonical_name, IMG_TARGET_LIMIT
)

logger = logging.getLogger("test_bot.vip_single")

# ------------------- Helpers: single control-message -------------------

def _set_ctrl_from_query(context: ContextTypes.DEFAULT_TYPE, query) -> None:
    context.user_data["vip_ctrl"] = {
        "chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
    }

def _get_ctrl(context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get("vip_ctrl") or {}
    cid = data.get("chat_id")
    mid = data.get("message_id")
    if isinstance(cid, int) and isinstance(mid, int):
        return cid, mid
    return None, None

async def _edit_ctrl_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None) -> bool:
    """
    Прагнемо ОНОВИТИ одне керуюче повідомлення.
    Якщо не вдалося – повертаємо False (щоб виклик коду зміг зробити reply_text).
    """
    query = update.callback_query if update and update.callback_query else None
    chat_id, message_id = _get_ctrl(context)
    # 1) Спроба редагувати відомий ctrl
    if chat_id and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return True
        except Exception:
            pass

    # 2) Спроба редагувати поточне callback-повідомлення
    if query and query.message:
        _set_ctrl_from_query(context, query)
        try:
            await query.message.edit_text(text=text, reply_markup=reply_markup)
            return True
        except Exception:
            # 3) Фолбек — створити нове
            try:
                m = await query.message.reply_text(text=text, reply_markup=reply_markup)
                context.user_data["vip_ctrl"] = {"chat_id": m.chat_id, "message_id": m.message_id}
                return True
            except Exception:
                return False

    # 4) Фолбек для текстових апдейтів (не callback)
    if update and update.message:
        try:
            m = await update.message.reply_text(text=text, reply_markup=reply_markup)
            context.user_data["vip_ctrl"] = {"chat_id": m.chat_id, "message_id": m.message_id}
            return True
        except Exception:
            return False

    return False

# ------------------- Допоміжні -------------------

def _media_dir_for_item(item: dict) -> str:
    return os.path.join(item["abs_dir"], item["name"])

def _detect_kind_and_ext_from_filename(filename: Optional[str], fallback_kind: str = "document") -> tuple[str, str]:
    if not filename:
        return fallback_kind, ".bin"
    name = filename.strip()
    _, ext = os.path.splitext(name)
    ext_low = (ext or "").lower()
    if ext_low in IMAGE_EXTS:
        return "image", ext_low
    if ext_low in AUDIO_EXTS:
        return "audio", ext_low
    if ext_low in VIDEO_EXTS:
        return "video", ext_low
    if ext_low in DOC_EXTS:
        return "document", ext_low
    return fallback_kind, (ext_low or ".bin")

def _detect_kind_and_ext_from_telegram(update: Update) -> tuple[Optional[str], Optional[str], Optional[object]]:
    msg = update.message
    if msg.document:
        kind, ext = _detect_kind_and_ext_from_filename(msg.document.file_name, "document")
        return kind, ext, msg.document
    if msg.photo:
        ps = msg.photo[-1]
        return "image", ".jpg", ps
    if msg.video:
        kind, ext = _detect_kind_and_ext_from_filename(msg.video.file_name, "video")
        return kind, ext, msg.video
    if msg.audio:
        kind, ext = _detect_kind_and_ext_from_filename(msg.audio.file_name, "audio")
        return kind, ext, msg.audio
    if msg.voice:
        return "audio", ".ogg", msg.voice
    return None, None, None

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

# ------------------- ПУБЛІЧНІ ХЕНДЛЕРИ -------------------

async def vip_edit_add_single_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _set_ctrl_from_query(context, query)

    idx_str = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    try:
        idx = int(idx_str)
    except ValueError:
        return

    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await _edit_ctrl_text(update, context, "❌ Тест не знайдено.")
        return

    item = items[idx]
    context.user_data["vip_single"] = {"item": item, "await_index": True, "idx_for_back": idx}
    context.user_data["awaiting_vip_single_index"] = True  # сумісність

    # межі-підказка
    total = 0
    try:
        abs_json = item.get("abs_path")
        if abs_json and os.path.isfile(abs_json):
            import json
            with open(abs_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                total = len(data)
    except Exception:
        total = 0
    hint = f"(від 1 до {total})" if total > 0 else "(від 1 і більше)"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx}"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])
    ok = await _edit_ctrl_text(
        update, context,
        text=(
            f"🔢 Введіть номер питання, до якого належить файл. Лише число {hint}.\n"
            f"Після цього надішліть один файл (зображення/аудіо/відео/документ)."
        ),
        reply_markup=kb
    )
    if not ok:  # ✅ гарантія відповіді
        await update.effective_message.reply_text(
            f"🔢 Введіть номер питання (лише число) {hint}…",
            reply_markup=kb
        )

async def vip_handle_single_index_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.user_data.get("vip_single")
    if not st or not st.get("await_index"):
        return

    # ⛔ Наш сценарій: блокуємо далі
    idx_for_back = st.get("idx_for_back")
    raw = (update.message.text or "").strip()
    try:
        n = int(raw)
        if n <= 0:
            raise ValueError
    except Exception:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
        ])
        ok = await _edit_ctrl_text(update, context, "❌ Невірний формат. Введи ціле додатне число (наприклад 12).", reply_markup=kb)
        if not ok:  # ✅ фолбек
            await update.effective_message.reply_text("❌ Невірний формат. Введи ціле додатне число (наприклад 12).", reply_markup=kb)
        raise ApplicationHandlerStop  # ✅

    st["index"] = n
    st["await_index"] = False
    st["await_file"] = True
    context.user_data["vip_single"] = st

    context.user_data.pop("awaiting_vip_single_index", None)
    context.user_data["awaiting_vip_single_file"] = True

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])
    ok = await _edit_ctrl_text(
        update, context,
        text=(f"✔️ Номер {n} прийнято. Тепер надішліть **один** файл (фото/аудіо/відео/документ)."),
        reply_markup=kb
    )
    if not ok:  # ✅ фолбек
        await update.effective_message.reply_text(
            f"✔️ Номер {n} прийнято. Тепер надішліть **один** файл (фото/аудіо/відео/документ).",
            reply_markup=kb
        )
    raise ApplicationHandlerStop  # ✅

async def vip_handle_single_media_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.user_data.get("vip_single")
    if not st or not st.get("await_file"):
        return

    item = st.get("item")
    if not item:
        context.user_data.pop("vip_single", None)
        context.user_data.pop("awaiting_vip_single_file", None)
        ok = await _edit_ctrl_text(update, context, "⚠️ Немає активного тесту для додавання файлу.")
        if not ok:  # ✅
            await update.effective_message.reply_text("⚠️ Немає активного тесту для додавання файлу.")
        raise ApplicationHandlerStop

    idx = st.get("index")
    if not isinstance(idx, int) or idx <= 0:
        context.user_data.pop("vip_single", None)
        context.user_data.pop("awaiting_vip_single_file", None)
        ok = await _edit_ctrl_text(update, context, "⚠️ Немає коректного номера питання. Почніть заново, будь ласка.")
        if not ok:  # ✅
            await update.effective_message.reply_text("⚠️ Немає коректного номера питання. Почніть заново, будь ласка.")
        raise ApplicationHandlerStop

    kind, ext, media_obj = _detect_kind_and_ext_from_telegram(update)
    if not kind or not ext or not media_obj:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{st.get('idx_for_back')}" if isinstance(st.get("idx_for_back"), int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
        ])
        ok = await _edit_ctrl_text(update, context, "❌ Не бачу підтримуваного файлу. Надішліть фото/аудіо/відео/документ.", reply_markup=kb)
        if not ok:  # ✅
            await update.effective_message.reply_text("❌ Не бачу підтримуваного файлу. Надішліть фото/аудіо/відео/документ.", reply_markup=kb)
        raise ApplicationHandlerStop

    media_dir = _media_dir_for_item(item)
    _ensure_dir(media_dir)

    out_name = _canonical_name(kind, idx, ext)
    out_path = os.path.join(media_dir, out_name)

    try:
        tg_file = await media_obj.get_file()
        raw_bytes = await tg_file.download_as_bytearray()
        if kind == "image":
            raw_bytes = _compress_image_bytes(raw_bytes, IMG_TARGET_LIMIT)
        with open(out_path, "wb") as f:
            f.write(raw_bytes)
    except Exception as e:
        logger.exception("Failed to save single media: %s", e)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{st.get('idx_for_back')}" if isinstance(st.get("idx_for_back"), int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
        ])
        ok = await _edit_ctrl_text(update, context, f"❌ Не вдалося зберегти файл: {e}", reply_markup=kb)
        if not ok:  # ✅
            await update.effective_message.reply_text(f"❌ Не вдалося зберегти файл: {e}", reply_markup=kb)
        raise ApplicationHandlerStop

    # Очистимо стан (і старі, і нові прапори)
    context.user_data.pop("vip_single", None)
    context.user_data.pop("awaiting_vip_single_file", None)

    try:
        _refresh_catalogs(context)
    except Exception:
        pass

    rel = os.path.relpath(out_path, TESTS_ROOT).replace("\\", "/")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{st.get('idx_for_back')}" if isinstance(st.get("idx_for_back"), int) else "vip_cancel"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])
    ok = await _edit_ctrl_text(update, context, f"✅ Файл додано: `/{rel}`", reply_markup=kb)
    if not ok:  # ✅
        await update.effective_message.reply_text(f"✅ Файл додано: `/{rel}`", reply_markup=kb)
    raise ApplicationHandlerStop  # ✅

# ------------------- WIPE (видалити всі файли медіа) -------------------

async def vip_wipe_media_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _set_ctrl_from_query(context, query)

    idx_str = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    try:
        idx = int(idx_str)
    except ValueError:
        return

    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await _edit_ctrl_text(update, context, "❌ Тест не знайдено.")
        return

    item = items[idx]
    media_dir = _media_dir_for_item(item)
    exists = os.path.isdir(media_dir)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Так, видалити всі файли", callback_data="vip_media_wipe_confirm|yes")],
        [InlineKeyboardButton("❎ Ні, скасувати", callback_data="vip_media_wipe_confirm|no")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx}"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])
    context.user_data["vip_wipe_target"] = item
    await _edit_ctrl_text(
        update, context,
        text=(
            f"⚠️ Папка медіа цього тесту: `{media_dir}`\n"
            f"{'Зараз існує і буде повністю видалена.' if exists else 'Папки наразі немає.'}\n\n"
            f"Продовжити?"
        ),
        reply_markup=kb
    )

async def vip_wipe_media_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    answer = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    item = context.user_data.pop("vip_wipe_target", None)
    if answer != "yes":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{item.get('idx')}" if isinstance(item, dict) and 'idx' in item else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
        ])
        await _edit_ctrl_text(update, context, "❎ Скасовано.", reply_markup=kb)
        return

    if not item:
        await _edit_ctrl_text(update, context, "⚠️ Немає активного тесту.")
        return

    media_dir = _media_dir_for_item(item)
    try:
        if os.path.isdir(media_dir):
            shutil.rmtree(media_dir, ignore_errors=True)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{item.get('idx')}" if isinstance(item, dict) and 'idx' in item else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
        ])
        await _edit_ctrl_text(update, context, "🧹 Усі файли медіатеки тесту видалено.", reply_markup=kb)
    except Exception as e:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{item.get('idx')}" if isinstance(item, dict) and 'idx' in item else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
        ])
        await _edit_ctrl_text(update, context, f"❌ Не вдалося видалити: {e}", reply_markup=kb)
        return

    try:
        _refresh_catalogs(context)
    except Exception:
        pass
