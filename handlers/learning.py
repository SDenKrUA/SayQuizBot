# handlers/learning.py
import random
import aiofiles
import logging
import io
import os
import base64
from datetime import datetime
from telegram import (
    Update,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaAnimation,   # додано для GIF
)
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from utils.keyboards import (
    learning_range_keyboard, learning_order_keyboard,
    build_options_markup, get_progress_bar
)
from utils.formatting import format_question_text
from utils.i18n import t

logger = logging.getLogger("test_bot.learning")

ENABLE_MEDIA = os.getenv("ENABLE_MEDIA", "1") == "1"

# ===== Нові правила відправки медіа =====
# Зображення inline: .jpg .jpeg .png .webp → як фото; .gif → як анімація
# Відео inline: тільки .mp4 → відео; інші відео → документ
# Аудіо inline: .mp3 .wav .ogg .m4a .aac .flac → як аудіо
_IMG_EXT_PHOTO = {".jpg", ".jpeg", ".png", ".webp"}
_IMG_EXT_ANIM = {".gif"}
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
_VIDEO_INLINE = {".mp4"}

def _placeholder_png_bytes() -> bytes:
    """Повертає байти PNG-заглушки (1x1)."""
    b64 = (
        b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAA'
        b'AAC0lEQVR42mP8/x8AAwMCAO+XU2sAAAAASUVORK5CYII='
    )
    return base64.b64decode(b64)

async def _load_file_bytes(path: str | None) -> bytes | None:
    """Читає файл у пам’ять. Якщо немає/помилка — None."""
    if not path:
        return None
    try:
        async with aiofiles.open(path, "rb") as f:
            return await f.read()
    except Exception as e:
        logger.debug("[LEARN][MEDIA] read failed %s: %s", path, e)
        return None

def _bio_with_name(data: bytes, filename: str) -> io.BytesIO:
    """BytesIO з іменем — Telegram любить мати filename для медіа."""
    bio = io.BytesIO(data)
    bio.name = filename
    return bio

def _pick_media_for_question(q: dict) -> tuple[str, str | None]:
    """
    Визначає тип медіа питання.
    За наявності ENABLE_MEDIA=True пріоритет: video > image > audio > document.
    При ENABLE_MEDIA=False використовуємо тільки image (або none).
    Повертає (media_type, abs_path_or_None) де media_type ∈ {image, video, audio, document, none}.
    """
    if ENABLE_MEDIA:
        if q.get("video"):
            return "video", q["video"]
        if q.get("image"):
            return "image", q["image"]
        if q.get("audio"):
            return "audio", q["audio"]
        if q.get("document"):
            return "document", q["document"]
        return "none", None
    else:
        if q.get("image"):
            return "image", q["image"]
        return "none", None

# ===================== ГВАРДИ СТАНУ =====================

def _is_learning_flow(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Ми у флоуі навчання, коли користувач щойно зайшов у «Режим навчання»
    та обирає діапазон/порядок, або вже проходить питання.
    """
    mode = context.user_data.get("mode")
    return mode == "learning"

def _is_waiting_custom_range(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get("awaiting_custom_range"))

# ===================== Обробники вибору діапазону/порядку =====================

async def handle_learning_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробник кліків по діапазону та «Назад» у МОДІ навчання.
    ІГНОРУЄ «Назад» та будь-який ввід, якщо ми НЕ у навчальному флоуі — щоб не дублювати відповіді
    з браузером розділів чи іншими екранами.
    """
    text = (update.message.text or "").strip()

    # Якщо це «Назад», але ми не у навчанні — ігноруємо (даємо іншим хендлерам обробити)
    if text in {"🔙 Назад", "⬅️ Назад"} and not _is_learning_flow(context):
        logger.info("[LEARN] Back pressed outside learning flow — ignore")
        return

    # Клік по діапазону або «Власний діапазон» ми приймаємо лише у навчальному флоуі
    if not _is_learning_flow(context) and not _is_waiting_custom_range(context):
        logger.info("[LEARN] Ignored input outside learning flow: %r", text)
        return

    if "add_question" in context.user_data:
        logger.info(f"[LEARN] Skip: add_question active for user={update.effective_user.id}")
        return

    lang = context.bot_data.get("lang", "uk")
    range_text = text
    total_questions = context.user_data.get("total_questions", 0)

    logger.info(f"[LEARN] handle_learning_range user={update.effective_user.id} text='{range_text}' total={total_questions}")

    if range_text in {"🔙 Назад", "⬅️ Назад"}:
        from utils.keyboards import main_menu
        await update.message.reply_text(
            t(lang, "menu_main", test=context.user_data.get("current_test", "Тест")),
            reply_markup=main_menu()
        )
        logger.info(f"[LEARN] Back to main menu")
        return

    if range_text == "🔢 Власний діапазон":
        context.user_data["awaiting_custom_range"] = True
        from telegram import ReplyKeyboardMarkup, KeyboardButton
        await update.message.reply_text(
            t(lang, "learning_set_custom", count=total_questions),
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
        )
        logger.info(f"[LEARN] Awaiting custom range")
        return

    try:
        parts = range_text.split("-")
        if len(parts) != 2:
            raise ValueError("bad format")
        start, end = map(int, parts)
        start = max(1, min(start, total_questions))
        end = max(1, min(end, total_questions))
        if start > end:
            start, end = end, start

        context.user_data["learning_range"] = (start, end)
        context.user_data["mode"] = "learning"

        await update.message.reply_text(
            t(lang, "learning_range_set", start=start, end=end),
            reply_markup=learning_order_keyboard()
        )
        logger.info(f"[LEARN] Range set {start}-{end} (mode=learning)")
    except Exception as e:
        logger.warning(f"[LEARN] Range parse error: '{range_text}' err={e}")
        await update.message.reply_text(t(lang, "range_invalid"))

async def handle_custom_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Приймаємо «кастомний» діапазон лише коли ми справді ЙОГО очікуємо.
    Інакше — ігноруємо (щоб не перехоплювати довільний текст та «Назад» поза флоу).
    """
    if not _is_waiting_custom_range(context):
        logger.info("[LEARN] custom range text outside waiting state — ignore")
        return

    if "add_question" in context.user_data:
        logger.info(f"[LEARN] Skip custom range: add_question active user={update.effective_user.id}")
        return

    lang = context.bot_data.get("lang", "uk")
    txt = (update.message.text or "").strip()
    total_questions = context.user_data.get("total_questions", 0)

    logger.info(f"[LEARN] handle_custom_range user={update.effective_user.id} text='{txt}' total={total_questions}")

    if txt in {"🔙 Назад", "⬅️ Назад"}:
        context.user_data.pop("awaiting_custom_range", None)
        await update.message.reply_text(
            "Обери діапазон:",
            reply_markup=learning_range_keyboard(total_questions)
        )
        logger.info("[LEARN] Back to range keyboard")
        return

    try:
        parts = txt.split("-")
        if len(parts) != 2:
            raise ValueError("bad format")
        start, end = map(int, parts)
        if start < 1 or end > total_questions:
            await update.message.reply_text(t(lang, "range_bounds", count=total_questions))
            logger.info(f"[LEARN] Out of bounds: {start}-{end} of {total_questions}")
            return
        if start > end:
            start, end = end, start

        context.user_data["learning_range"] = (start, end)
        context.user_data.pop("awaiting_custom_range", None)
        context.user_data["mode"] = "learning"

        await update.message.reply_text(
            t(lang, "learning_range_set", start=start, end=end),
            reply_markup=learning_order_keyboard()
        )
        logger.info(f"[LEARN] Custom range set {start}-{end} (mode=learning)")
    except Exception as e:
        logger.warning(f"[LEARN] Custom range parse error '{txt}' err={e}")
        await update.message.reply_text(t(lang, "learning_set_custom", count=total_questions))

async def handle_learning_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обираємо порядок лише коли ми у навчальному флоуі і ВЖЕ вибраний діапазон.
    """
    if not _is_learning_flow(context) or "learning_range" not in context.user_data:
        logger.info("[LEARN] order choice outside learning flow — ignore")
        return

    if "add_question" in context.user_data:
        logger.info(f"[LEARN] Skip order: add_question active user={update.effective_user.id}")
        return

    lang = context.bot_data.get("lang", "uk")
    choice = (update.message.text or "").strip()
    total_questions = context.user_data.get("total_questions", 0)

    logger.info(f"[LEARN] handle_learning_order user={update.effective_user.id} choice='{choice}' total={total_questions}")

    if choice in {"🔙 Назад", "⬅️ Назад"}:
        await update.message.reply_text(
            "Обери діапазон:",
            reply_markup=learning_range_keyboard(total_questions)
        )
        logger.info("[LEARN] Back to range keyboard")
        return

    start, end = context.user_data.get("learning_range", (1, min(50, total_questions if total_questions else 1)))
    question_range = list(range(start - 1, end))

    if choice == "🔢 По порядку":
        context.user_data["order"] = question_range
        order_type = "по порядку"
    elif choice == "🎲 В роздріб":
        shuffled = question_range.copy()
        random.shuffle(shuffled)
        context.user_data["order"] = shuffled
        order_type = "в роздріб"
    else:
        await update.message.reply_text(t(lang, "learning_order_wrong"))
        logger.info("[LEARN] Wrong order choice")
        return

    # Стан сесії
    context.user_data["mode"] = "learning"
    context.user_data["step"] = 0
    context.user_data["score"] = 0
    context.user_data["wrong_pairs"] = []
    context.user_data["current_streak"] = 0
    context.user_data["start_time"] = datetime.now()

    # Скидаємо «живе» повідомлення попередніх сесій
    context.user_data.pop("question_chat_id", None)
    context.user_data.pop("question_message_id", None)
    context.user_data.pop("question_message_type", None)

    await update.message.reply_text(
        t(lang, "learning_start", count=len(question_range), order=order_type),
        reply_markup=None
    )
    logger.info(f"[LEARN] Start learning: count={len(question_range)} order={order_type}")

    await send_current_question(update.effective_chat.id, context)

# ===================== Допоміжне: визначення способу відправки =====================

def _decide_inline_kind_and_filename(media_type: str, path: str) -> tuple[str, str]:
    """
    На основі типу/розширення повертає:
      kind ∈ {'photo','animation','video','audio','document'}
      filename — узгоджене ім’я файлу з правильним розширенням
    """
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    ext_low = (ext or "").lower()

    if media_type == "image":
        if ext_low in _IMG_EXT_PHOTO:
            return "photo", f"{stem or 'img'}{ext_low or '.jpg'}"
        if ext_low in _IMG_EXT_ANIM:
            return "animation", f"{stem or 'anim'}{ext_low or '.gif'}"
        return "document", f"{stem or 'image'}{ext_low or '.bin'}"

    if media_type == "video":
        if ext_low in _VIDEO_INLINE:
            return "video", f"{stem or 'video'}{ext_low or '.mp4'}"
        return "document", f"{stem or 'video'}{ext_low or '.bin'}"

    if media_type == "audio":
        use_ext = ext_low if ext_low in _AUDIO_EXTS else ".mp3"
        return "audio", f"{stem or 'audio'}{use_ext}"

    return "document", f"{stem or 'file'}{ext_low or '.bin'}"

# ===================== Рендер питань =====================

async def send_current_question(chat_id, context, edit_from_query=None):
    """
    Показує поточне питання, з урахуванням правил відправки:
    - .mp4 → video; інші відео → document
    - .jpg/.jpeg/.png/.webp → photo; .gif → animation
    - audio (.mp3/.wav/.ogg/.m4a/.aac/.flac) → audio
    - якщо медіа немає/не читається — placeholder як photo
    """
    step = context.user_data.get("step", 0)
    order = context.user_data.get("order", [])
    questions = context.user_data.get("questions", [])

    logger.info(f"[LEARN] send_current_question step={step} total_steps={len(order)}")

    if step >= len(order):
        from .testing import show_results  # спільний підсумок
        logger.info("[LEARN] Finished learning session -> show_results")
        await show_results(chat_id, context)
        return

    q_index = order[step]
    context.user_data["current_q_index"] = q_index
    q = questions[q_index]

    progress = get_progress_bar(step + 1, len(order))
    caption = f"{progress}\n\n" + format_question_text(q)

    markup = build_options_markup(q_index, two_columns=True)

    media_type, path = _pick_media_for_question(q)

    # Якщо немає медіа — плейсхолдер
    if media_type == "none" or not path:
        data = _placeholder_png_bytes()
        bio = _bio_with_name(data, f"q{q_index+1}.png")
        new_kind = "photo"
        saved_kind = context.user_data.get("question_message_type")

        if edit_from_query is not None and saved_kind == new_kind:
            try:
                await edit_from_query.edit_message_media(
                    media=InputMediaPhoto(media=bio, caption=caption, parse_mode="HTML"),
                    reply_markup=markup
                )
                context.user_data["question_message_type"] = "photo"
                context.user_data["question_chat_id"] = edit_from_query.message.chat_id
                context.user_data["question_message_id"] = edit_from_query.message.message_id
                logger.info("[LEARN] Edited placeholder photo in-place")
                return
            except Exception as e:
                logger.debug("[LEARN] edit placeholder failed: %s", e)

        sent = await context.bot.send_photo(
            chat_id=chat_id, photo=bio, caption=caption, reply_markup=markup, parse_mode="HTML"
        )
        context.user_data["question_message_type"] = "photo"
        context.user_data["question_chat_id"] = sent.chat_id
        context.user_data["question_message_id"] = sent.message_id
        logger.info("[LEARN] Sent placeholder photo (new message)")
        return

    # Є медіа — читаємо
    data = await _load_file_bytes(path)
    if not data:
        data = _placeholder_png_bytes()
        bio = _bio_with_name(data, f"q{q_index+1}.png")
        sent = await context.bot.send_photo(
            chat_id=chat_id, photo=bio, caption=caption, reply_markup=markup, parse_mode="HTML"
        )
        context.user_data["question_message_type"] = "photo"
        context.user_data["question_chat_id"] = sent.chat_id
        context.user_data["question_message_id"] = sent.message_id
        logger.info("[LEARN] Media missing -> sent placeholder photo")
        return

    new_kind, fname = _decide_inline_kind_and_filename(
        "image" if media_type == "image" else media_type, path
    )
    saved_kind = context.user_data.get("question_message_type")

    # Спроба відредагувати існуюче повідомлення, якщо тип збігається
    if new_kind == saved_kind and edit_from_query is not None:
        try:
            if new_kind == "photo":
                media = InputMediaPhoto(_bio_with_name(data, fname), caption=caption, parse_mode="HTML")
            elif new_kind == "animation":
                media = InputMediaAnimation(_bio_with_name(data, fname), caption=caption, parse_mode="HTML")
            elif new_kind == "video":
                media = InputMediaVideo(_bio_with_name(data, fname), caption=caption, parse_mode="HTML")
            elif new_kind == "audio":
                media = InputMediaAudio(_bio_with_name(data, fname), caption=caption, parse_mode="HTML")
            else:
                media = InputMediaDocument(_bio_with_name(data, fname), caption=caption, parse_mode="HTML")

            await edit_from_query.edit_message_media(media=media, reply_markup=markup)
            context.user_data["question_message_type"] = new_kind
            context.user_data["question_chat_id"] = edit_from_query.message.chat_id
            context.user_data["question_message_id"] = edit_from_query.message.message_id
            logger.info("[LEARN] Edited media in-place (same type)")
            return
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.debug("[LEARN] message not modified, ignore")
                return
            logger.debug("[LEARN] edit same-type failed: %s", e)
        except Exception as e:
            logger.debug("[LEARN] edit same-type failed: %s", e)

    # Надсилаємо нове повідомлення відповідного типу
    bio = _bio_with_name(data, fname)
    if new_kind == "photo":
        sent = await context.bot.send_photo(
            chat_id, bio, caption=caption, reply_markup=markup, parse_mode="HTML"
        )
    elif new_kind == "animation":
        sent = await context.bot.send_animation(
            chat_id, bio, caption=caption, reply_markup=markup, parse_mode="HTML"
        )
    elif new_kind == "video":
        sent = await context.bot.send_video(
            chat_id, bio, caption=caption, reply_markup=markup, parse_mode="HTML"
        )
    elif new_kind == "audio":
        sent = await context.bot.send_audio(
            chat_id, bio, caption=caption, reply_markup=markup, parse_mode="HTML"
        )
    else:
        sent = await context.bot.send_document(
            chat_id, bio, caption=caption, reply_markup=markup, parse_mode="HTML"
        )

    context.user_data["question_message_type"] = new_kind
    context.user_data["question_chat_id"] = sent.chat_id
    context.user_data["question_message_id"] = sent.message_id
    logger.info("[LEARN] Sent new message with kind=%s", new_kind)
