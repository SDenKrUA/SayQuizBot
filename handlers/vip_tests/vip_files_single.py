# handlers/vip_tests/vip_files_single.py
import os
import shutil
import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from .vip_constants import TESTS_ROOT
from .vip_storage import _refresh_catalogs
from .vip_utils import (
    IMAGE_EXTS, AUDIO_EXTS, VIDEO_EXTS, DOC_EXTS,
    _compress_image_bytes, _canonical_name, IMG_TARGET_LIMIT
)

logger = logging.getLogger("test_bot.vip_single")

# ------------------- Допоміжні -------------------

def _media_dir_for_item(item: dict) -> str:
    """
    Папка з медіа для тесту: <abs_dir>/<name>
    """
    return os.path.join(item["abs_dir"], item["name"])

def _detect_kind_and_ext_from_filename(filename: Optional[str], fallback_kind: str = "document") -> tuple[str, str]:
    """
    За file_name/mime (де можливо) визначаємо тип (image/audio/video/document) та розширення (з крапкою).
    Якщо не вдається — повертаємо (fallback_kind, ".bin")
    """
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

    # невідоме — трактуємо як документ
    return fallback_kind, (ext_low or ".bin")

def _detect_kind_and_ext_from_telegram(update: Update) -> tuple[Optional[str], Optional[str], Optional[object]]:
    """
    Повертає (kind, ext, file_obj_or_photo_size) де:
      - kind ∈ {"image","audio","video","document"} або None
      - ext — строка з крапкою
      - file_obj_or_photo_size — об'єкт, у якого є get_file() (за винятком photo: там повернемо PhotoSize)
    Підтримує: document, photo, video, audio, voice.
    """
    msg = update.message

    # Документ
    if msg.document:
        kind, ext = _detect_kind_and_ext_from_filename(msg.document.file_name, "document")
        return kind, ext, msg.document

    # Фото (список PhotoSize) — беремо найвище за розміром
    if msg.photo:
        ps = msg.photo[-1]  # найбільше
        # Telegram для фото не гарантує ім'я: призначимо .jpg
        return "image", ".jpg", ps

    # Відео
    if msg.video:
        kind, ext = _detect_kind_and_ext_from_filename(msg.video.file_name, "video")
        return kind, ext, msg.video

    # Аудіо (музика)
    if msg.audio:
        kind, ext = _detect_kind_and_ext_from_filename(msg.audio.file_name, "audio")
        return kind, ext, msg.audio

    # Голосове повідомлення (voice) — зазвичай .ogg
    if msg.voice:
        return "audio", ".ogg", msg.voice

    return None, None, None


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

# ------------------- ПУБЛІЧНІ ХЕНДЛЕРИ -------------------

async def vip_edit_add_single_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Клік по "📄 Додати окремий файл".
    Зберігаємо item у vip_single.item і чекаємо номер питання.
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
    context.user_data["vip_single"] = {"item": item, "await_index": True}

    # Спробуємо по можливості дістати кількість запитань, щоб красиво підказати межу
    total = 0
    try:
        # item має містити 'abs_path' на JSON
        abs_json = item.get("abs_path")
        if abs_json and os.path.isfile(abs_json):
            import json
            with open(abs_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                total = len(data)
    except Exception:
        total = 0

    if total > 0:
        hint = f"(від 1 до {total})"
    else:
        hint = "(від 1 і більше)"

    await query.message.reply_text(
        f"🔢 Введіть номер питання, до якого належить файл. Лише число {hint}.\n"
        f"Після цього надішліть один файл (зображення/аудіо/відео/документ)."
    )

async def vip_handle_single_index_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Приймає номер питання у відповідь на vip_edit_add_single_file_start.
    Далі чекає 1 файл медіа.
    """
    st = context.user_data.get("vip_single")
    if not st or not st.get("await_index"):
        return

    raw = (update.message.text or "").strip()
    try:
        n = int(raw)
    except ValueError:
        await update.message.reply_text("❌ Невірний формат. Введи ціле додатне число (наприклад 12).")
        return

    if n <= 0:
        await update.message.reply_text("❌ Номер має бути додатнім. Спробуй ще.")
        return

    st["index"] = n
    st["await_index"] = False
    st["await_file"] = True
    context.user_data["vip_single"] = st

    await update.message.reply_text(
        f"✔️ Номер {n} прийнято. Тепер надішліть **один** файл "
        f"(фото/аудіо/відео/документ) у відповідь."
    )

async def vip_handle_single_media_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Приймає 1 файл після введення номера.
    Визначає тип → зберігає як image{N}.* / audio{N}.* / video{N}.* / doc{N}.* у папку медіа тесту.
    Картинку стискає (за наявності Pillow).
    """
    st = context.user_data.get("vip_single")
    if not st or not st.get("await_file"):
        return

    item = st.get("item")
    if not item:
        context.user_data.pop("vip_single", None)
        await update.message.reply_text("⚠️ Немає активного тесту для додавання файлу.")
        return

    idx = st.get("index")
    if not isinstance(idx, int) or idx <= 0:
        context.user_data.pop("vip_single", None)
        await update.message.reply_text("⚠️ Немає коректного номера питання. Почніть заново, будь ласка.")
        return

    kind, ext, media_obj = _detect_kind_and_ext_from_telegram(update)
    if not kind or not ext or not media_obj:
        await update.message.reply_text("❌ Не бачу підтримуваного файлу. Надішліть фото/аудіо/відео/документ.")
        return

    media_dir = _media_dir_for_item(item)
    _ensure_dir(media_dir)

    # Уточнимо canonical name (за заданим індексом)
    out_name = _canonical_name(kind, idx, ext)
    out_path = os.path.join(media_dir, out_name)

    try:
        tg_file = await media_obj.get_file()
        # Фото (PhotoSize) → немає file_name, але є .get_file()
        raw_bytes = await tg_file.download_as_bytearray()

        if kind == "image":
            raw_bytes = _compress_image_bytes(raw_bytes, IMG_TARGET_LIMIT)

        with open(out_path, "wb") as f:
            f.write(raw_bytes)
    except Exception as e:
        logger.exception("Failed to save single media: %s", e)
        await update.message.reply_text(f"❌ Не вдалося зберегти файл: {e}")
        return

    # Очистимо стан
    context.user_data.pop("vip_single", None)

    # Оновимо каталоги (на випадок, якщо десь залежать прев'юшки/підрахунки)
    try:
        _refresh_catalogs(context)
    except Exception:
        pass

    rel = os.path.relpath(out_path, TESTS_ROOT).replace("\\", "/")
    await update.message.reply_text(f"✅ Файл додано: `/{rel}`")

# ------------------- WIPE (видалити всі файли медіа) -------------------

async def vip_wipe_media_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Кнопка “🧹 Видалити всі файли” → підтвердження.
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
    media_dir = _media_dir_for_item(item)
    exists = os.path.isdir(media_dir)

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Так, видалити всі файли", callback_data="vip_media_wipe_confirm|yes")],
        [InlineKeyboardButton("❎ Ні, скасувати", callback_data="vip_media_wipe_confirm|no")],
    ])
    context.user_data["vip_wipe_target"] = item
    await query.message.reply_text(
        f"⚠️ Папка медіа цього тесту: `{media_dir}`\n"
        f"{'Зараз існує і буде повністю видалена.' if exists else 'Папки наразі немає.'}\n\n"
        f"Продовжити?",
        reply_markup=kb
    )

async def vip_wipe_media_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Підтвердження видалення.
    """
    query = update.callback_query
    await query.answer()

    answer = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    item = context.user_data.pop("vip_wipe_target", None)
    if answer != "yes":
        await query.message.reply_text("❎ Скасовано.")
        return

    if not item:
        await query.message.reply_text("⚠️ Немає активного тесту.")
        return

    media_dir = _media_dir_for_item(item)
    try:
        if os.path.isdir(media_dir):
            shutil.rmtree(media_dir, ignore_errors=True)
        await query.message.reply_text("🧹 Усі файли медіатеки тесту видалено.")
    except Exception as e:
        await query.message.reply_text(f"❌ Не вдалося видалити: {e}")
        return

    # Оновити каталоги
    try:
        _refresh_catalogs(context)
    except Exception:
        pass
