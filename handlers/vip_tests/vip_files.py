# handlers/vip_tests/vip_files.py
import os
import shutil
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_constants import TESTS_ROOT
from .vip_utils import IMAGE_EXTS, AUDIO_EXTS, VIDEO_EXTS, DOC_EXTS, _compress_image_bytes

logger = logging.getLogger("test_bot.vip_files")

# Ключі станів:
# - vip_single_media_dir : абсолютний шлях до теки файлів тесту (<abs_dir>/<test_name>)
# - awaiting_vip_single_index : чекаємо номер питання (int > 0)
# - vip_single_index : вибраний номер
# - awaiting_vip_single_file : чекаємо один файл (photo/audio/video/document)
# - vip_media_wipe_target : {"name": str, "abs_dir": str, "idx": int}
# - vip_single_idx_for_back : int (щоб «⬅️ Назад» повертало у vip_edit|{idx})

# ===== Helpers for single control-message UI =====

def _set_ctrl_from_query(context: ContextTypes.DEFAULT_TYPE, query) -> None:
    """Зафіксувати керуюче повідомлення (chat_id, message_id) за поточним callback'ом."""
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
            pass

    if query and query.message:
        _set_ctrl_from_query(context, query)
        try:
            await query.message.edit_text(text=text, reply_markup=reply_markup)
            return
        except Exception:
            m = await query.message.reply_text(text=text, reply_markup=reply_markup)
            context.user_data["vip_ctrl"] = {"chat_id": m.chat_id, "message_id": m.message_id}
            return

    if update and update.message:
        m = await update.message.reply_text(text=text, reply_markup=reply_markup)
        context.user_data["vip_ctrl"] = {"chat_id": m.chat_id, "message_id": m.message_id}

# ---------- Меню: Додати ОКРЕМИЙ файл ----------

async def vip_edit_add_single_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Кнопка з меню редагування: "📄 Додати окремий файл".
    Ставитиме стан: спочатку запитуємо номер питання, потім чекаємо файл.
    """
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
    media_dir = os.path.join(item["abs_dir"], item["name"])
    os.makedirs(media_dir, exist_ok=True)

    # Скидаємо попередні стани single-file
    for k in ("vip_single_media_dir", "awaiting_vip_single_index", "vip_single_index", "awaiting_vip_single_file"):
        context.user_data.pop(k, None)

    context.user_data["vip_single_media_dir"] = media_dir
    context.user_data["awaiting_vip_single_index"] = True
    context.user_data["vip_single_idx_for_back"] = idx  # щоб працював «⬅️ Назад» у будь-якому кроці

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx}"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
    ])
    await _edit_ctrl_text(
        update, context,
        text=(
            "🔢 Введіть номер питання, до якого належить файл (лише число, наприклад 12).\n"
            "Після цього надішліть один файл (зображення/аудіо/відео/документ)."
        ),
        reply_markup=kb
    )

# ---------- Крок 1: Приймаємо номер ----------

async def vip_handle_single_index_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Приймає ТІЛЬКИ коли очікуємо номер питання для single-file.
    """
    if not context.user_data.get("awaiting_vip_single_index"):
        return

    idx_for_back = context.user_data.get("vip_single_idx_for_back")
    text = (update.message.text or "").strip()
    if not text.isdigit():
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
        ])
        await _edit_ctrl_text(update, context, "❌ Введіть лише число (наприклад 7).", reply_markup=kb)
        return

    num = int(text)
    if num <= 0:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
        ])
        await _edit_ctrl_text(update, context, "❌ Номер має бути додатнім числом.", reply_markup=kb)
        return

    context.user_data["vip_single_index"] = num
    context.user_data.pop("awaiting_vip_single_index", None)
    context.user_data["awaiting_vip_single_file"] = True

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
    ])
    await _edit_ctrl_text(
        update, context,
        text=(
            f"✅ Прив’язка до питання №{num} встановлена.\n"
            "Тепер надішліть один файл (фото/аудіо/відео/документ)."
        ),
        reply_markup=kb
    )

# ---------- Крок 2: Приймаємо один файл ----------

def _detect_kind_and_ext(filename: str, fallback_ext: str = "") -> tuple[str|None, str]:
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTS:
        return "image", ext
    if ext in AUDIO_EXTS:
        return "audio", ext
    if ext in VIDEO_EXTS:
        return "video", ext
    if ext in DOC_EXTS:
        return "document", ext
    if fallback_ext:
        return "image", fallback_ext
    return None, ""

def _canonical_name(kind: str, idx: int, ext: str) -> str:
    base = {"image": "image", "audio": "audio", "video": "video", "document": "doc"}.get(kind, "file")
    return f"{base}{idx}{ext}"

async def _download_bytes(file_obj) -> bytes:
    tg_file = await file_obj.get_file()
    return await tg_file.download_as_bytearray()

async def vip_handle_single_media_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Приймає 1 файл у стані awaiting_vip_single_file.
    Підтримує:
      - фото (update.message.photo)
      - документ (update.message.document)
      - аудіо (update.message.audio / voice)
      - відео (update.message.video)
    """
    if not context.user_data.get("awaiting_vip_single_file"):
        return

    idx_for_back = context.user_data.get("vip_single_idx_for_back")
    media_dir = context.user_data.get("vip_single_media_dir")
    idx = context.user_data.get("vip_single_index")
    if not media_dir or not isinstance(idx, int) or idx <= 0:
        # зіб’ємо стани і відпустимо
        for k in ("vip_single_media_dir", "vip_single_index", "awaiting_vip_single_file"):
            context.user_data.pop(k, None)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
        ])
        await _edit_ctrl_text(update, context, "⚠️ Сесія додавання файлу неактивна. Спробуйте ще раз з меню редагування.", reply_markup=kb)
        return

    try:
        # ----- Визначаємо тип вхідного файлу -----
        # 1) Фото
        if update.message.photo:
            photo = update.message.photo[-1]
            raw = await _download_bytes(photo)
            raw = _compress_image_bytes(raw)
            kind, ext = "image", ".jpg"

        # 2) Відео
        elif update.message.video:
            video = update.message.video
            raw = await _download_bytes(video)
            filename = (video.file_name or "video.mp4")
            kind, ext = _detect_kind_and_ext(filename)
            if not kind:
                kind, ext = "video", ".mp4"

        # 3) Аудіо (music)
        elif update.message.audio:
            audio = update.message.audio
            raw = await _download_bytes(audio)
            filename = (audio.file_name or "audio.mp3")
            kind, ext = _detect_kind_and_ext(filename)
            if not kind:
                kind, ext = "audio", ".mp3"

        # 4) Voice (ogg opus) — теж аудіо
        elif update.message.voice:
            voice = update.message.voice
            raw = await _download_bytes(voice)
            kind, ext = "audio", ".ogg"

        # 5) Документ
        elif update.message.document:
            doc = update.message.document
            raw = await _download_bytes(doc)
            filename = (doc.file_name or "").strip()
            kind, ext = _detect_kind_and_ext(filename)
            if not kind:
                kind, ext = "document", (os.path.splitext(filename)[1].lower() or ".bin")

        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
                 InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
            ])
            await _edit_ctrl_text(update, context, "❌ Надішліть саме файл (фото/аудіо/відео/документ).", reply_markup=kb)
            return

        # ----- Збереження -----
        os.makedirs(media_dir, exist_ok=True)
        out_name = _canonical_name(kind, idx, ext)
        out_path = os.path.join(media_dir, out_name)
        with open(out_path, "wb") as f:
            f.write(raw)

        # Скидаємо стани
        for k in ("vip_single_media_dir", "vip_single_index", "awaiting_vip_single_file"):
            context.user_data.pop(k, None)

        from .vip_storage import _relative_to_tests
        rel_media = _relative_to_tests(out_path)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
        ])
        await _edit_ctrl_text(update, context, f"✅ Файл збережено як `/{rel_media}`", reply_markup=kb)

    except Exception as e:
        logger.exception("Single media save failed: %s", e)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
        ])
        await _edit_ctrl_text(update, context, f"❌ Не вдалося зберегти файл: {e}", reply_markup=kb)
        # не чіпаємо стани, щоб можна було повторити відправку

# ---------- Видалити ВСІ файли (теку media) ----------

async def vip_wipe_media_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показує підтвердження видалення усіх файлів (теку <abs_dir>/<name>).
    """
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
    context.user_data["vip_media_wipe_target"] = {"name": item["name"], "abs_dir": item["abs_dir"], "idx": idx}

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Так, видалити", callback_data="vip_media_wipe_confirm|yes"),
            InlineKeyboardButton("❎ Скасувати", callback_data="vip_media_wipe_confirm|no"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx}"),
            InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel"),
        ],
    ])
    await _edit_ctrl_text(
        update, context,
        text=(
            f"⚠️ Ви впевнені, що хочете видалити ВСІ файли тесту «{item['name']}»?\n"
            "Буде видалено всю теку з файлами для цього тесту."
        ),
        reply_markup=kb
    )

async def vip_wipe_media_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    choice = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    tgt = context.user_data.pop("vip_media_wipe_target", None)
    idx_for_back = tgt.get("idx") if isinstance(tgt, dict) else None

    if choice != "yes" or not tgt:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
        ])
        await _edit_ctrl_text(update, context, "❎ Скасовано.", reply_markup=kb)
        return

    media_dir = os.path.join(tgt["abs_dir"], tgt["name"])
    try:
        if os.path.isdir(media_dir):
            shutil.rmtree(media_dir, ignore_errors=True)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
                 InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
            ])
            await _edit_ctrl_text(update, context, "🧹 Усі файли тесту видалено.", reply_markup=kb)
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
                 InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
            ])
            await _edit_ctrl_text(update, context, "ℹ️ Теки з файлами не знайдено — нічого видаляти.", reply_markup=kb)
    except Exception as e:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx_for_back}" if isinstance(idx_for_back, int) else "vip_cancel"),
             InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")]
        ])
        await _edit_ctrl_text(update, context, f"❌ Помилка видалення: {e}", reply_markup=kb)
