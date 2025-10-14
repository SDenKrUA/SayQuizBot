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
# - vip_media_wipe_target : {"name": str, "abs_dir": str}
# - очікування підтвердження: callback vip_media_wipe_confirm|(yes|no)

def _media_dir_for_item(item: dict) -> str:
    """Повертає теку з файлами тесту: <abs_dir>/<name>."""
    return os.path.join(item["abs_dir"], item["name"])

# ---------- Меню: Додати ОКРЕМИЙ файл ----------

async def vip_edit_add_single_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Кнопка з меню редагування: "📄 Додати окремий файл".
    Ставитиме стан: спочатку запитуємо номер питання, потім чекаємо файл.
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
    os.makedirs(media_dir, exist_ok=True)

    # Скидаємо попередні стани single-file (на всяк випадок)
    for k in ("vip_single_media_dir", "awaiting_vip_single_index", "vip_single_index", "awaiting_vip_single_file"):
        context.user_data.pop(k, None)

    context.user_data["vip_single_media_dir"] = media_dir
    context.user_data["awaiting_vip_single_index"] = True

    await query.message.reply_text(
        "🔢 Введіть номер питання, до якого належить файл (лише число, наприклад 12).\n"
        "Після цього надішліть один файл (зображення/аудіо/відео/документ)."
    )

# ---------- Крок 1: Приймаємо номер ----------

async def vip_handle_single_index_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Приймає ТІЛЬКИ коли очікуємо номер питання для single-file.
    """
    if not context.user_data.get("awaiting_vip_single_index"):
        return

    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Введіть лише число (наприклад 7).")
        return

    num = int(text)
    if num <= 0:
        await update.message.reply_text("❌ Номер має бути додатнім числом.")
        return

    context.user_data["vip_single_index"] = num
    context.user_data.pop("awaiting_vip_single_index", None)
    context.user_data["awaiting_vip_single_file"] = True

    await update.message.reply_text(
        f"✅ Прив’язка до питання №{num} встановлена.\n"
        "Тепер надішліть один файл (фото/аудіо/відео/документ)."
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
        # використаємо фолбек (для фото без імені, наприклад)
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

    media_dir = context.user_data.get("vip_single_media_dir")
    idx = context.user_data.get("vip_single_index")
    if not media_dir or not isinstance(idx, int) or idx <= 0:
        # зіб’ємо стани і відпустимо
        for k in ("vip_single_media_dir", "vip_single_index", "awaiting_vip_single_file"):
            context.user_data.pop(k, None)
        await update.message.reply_text("⚠️ Сесія додавання файлу неактивна. Спробуйте ще раз з меню редагування.")
        return

    # ----- Визначаємо тип вхідного файлу -----
    try:
        # 1) Фото
        if update.message.photo:
            # беремо найбільше за розміром
            photo = update.message.photo[-1]
            raw = await _download_bytes(photo)
            # зберігаємо як JPEG (узгоджено для сумісності)
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
                # якщо раптом не розпізнали — вважатимемо документом
                kind, ext = "document", (os.path.splitext(filename)[1].lower() or ".bin")

        else:
            await update.message.reply_text("❌ Надішліть саме файл (фото/аудіо/відео/документ).")
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
        await update.message.reply_text(f"✅ Файл збережено як `/{rel_media}`", parse_mode="Markdown")

    except Exception as e:
        logger.exception("Single media save failed: %s", e)
        await update.message.reply_text(f"❌ Не вдалося зберегти файл: {e}")
        # не чіпаємо стани, щоб можна було повторити відправку

# ---------- Видалити ВСІ файли (теку media) ----------

async def vip_wipe_media_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показує підтвердження видалення усіх файлів (теку <abs_dir>/<name>).
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
    context.user_data["vip_media_wipe_target"] = {"name": item["name"], "abs_dir": item["abs_dir"]}

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Так, видалити", callback_data="vip_media_wipe_confirm|yes"),
            InlineKeyboardButton("❎ Скасувати", callback_data="vip_media_wipe_confirm|no"),
        ]
    ])
    await query.message.reply_text(
        f"⚠️ Ви впевнені, що хочете видалити ВСІ файли тесту «{item['name']}»? "
        "Буде видалено всю теку з файлами для цього тесту.",
        reply_markup=kb
    )

async def vip_wipe_media_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    choice = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    tgt = context.user_data.pop("vip_media_wipe_target", None)

    if choice != "yes" or not tgt:
        await query.message.reply_text("❎ Скасовано.")
        return

    media_dir = os.path.join(tgt["abs_dir"], tgt["name"])
    try:
        if os.path.isdir(media_dir):
            shutil.rmtree(media_dir, ignore_errors=True)
            await query.message.reply_text("🧹 Усі файли тесту видалено.")
        else:
            await query.message.reply_text("ℹ️ Теки з файлами не знайдено — нічого видаляти.")
    except Exception as e:
        await query.message.reply_text(f"❌ Помилка видалення: {e}")
