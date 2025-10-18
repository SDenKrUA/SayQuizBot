import os
import io
import random
import logging
import base64
import re
from datetime import datetime
from typing import Optional, Tuple, Any, List

from telegram import (
    Update,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaAnimation,
)
from telegram.ext import ContextTypes

from utils.keyboards import (
    build_options_markup,
    get_progress_bar,
    main_menu,
    get_retry_keyboard,
    learning_range_keyboard,
)
from utils.formatting import format_question_text
from handlers.statistics_db import save_user_result_db
from utils.i18n import t

from utils.keyboards import browse_menu
from utils.loader import discover_tests_hierarchy, build_listing_for_path

from handlers.office import office_buttons_handler
from handlers.statistics_db import add_wrong_answer

logger = logging.getLogger("test_bot.testing")

_IMG_EXT_PHOTO = {".jpg", ".jpeg", ".png", ".webp"}
_IMG_EXT_ANIM = {".gif"}
_AUDIO_EXTS    = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
_VIDEO_INLINE  = {".mp4"}

def _get_chat_id(src: Any) -> int:
    if isinstance(src, Update) and src.effective_chat:
        return src.effective_chat.id
    if getattr(src, "message", None) and getattr(src.message, "chat", None):
        return src.message.chat.id
    if getattr(src, "chat", None):
        return src.chat.id
    raise RuntimeError("Cannot resolve chat_id for this source")

def _get_user_from_source(src: Any):
    if hasattr(src, "from_user") and getattr(src, "from_user") is not None:
        u = src.from_user
        return getattr(u, "id", None), getattr(u, "username", None)
    if isinstance(src, Update) and src.effective_user:
        return src.effective_user.id, src.effective_user.username
    if hasattr(src, "from_user") and getattr(src, "from_user") is not None:
        u = src.from_user
        return getattr(u, "id", None), getattr(u, "username", None)
    return None, None

def _detect_media(q: dict, base_dir: Optional[str]) -> Tuple[str, Optional[str]]:
    path = None
    mtype = "none"
    for key, t in (("image", "photo"), ("photo", "photo"),
                   ("video", "video"), ("audio", "audio"),
                   ("document", "doc"), ("doc", "doc")):
        p = q.get(key)
        if p:
            path = p
            mtype = t
            break
    if not path:
        return "none", None
    if base_dir and not os.path.isabs(path):
        return mtype, os.path.join(base_dir, path)
    return mtype, path

def _placeholder_png_bytes() -> bytes:
    b64 = (
        b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAA'
        b'AAC0lEQVR42mP8/x8AAwMCAO+XU2sAAAAASUVORK5CYII='
    )
    return base64.b64decode(b64)

def _bio_with_name(data: bytes, filename: str) -> io.BytesIO:
    bio = io.BytesIO(data)
    bio.name = filename
    return bio

# --- «Повітря» та відступи ---

def _ensure_question_answers_gap(body: str) -> str:
    if not body:
        return body
    # нормалізуємо перенос
    i = body.find("\n")
    if i == -1:
        return body + "\n"
    if i + 1 < len(body) and body[i + 1] == "\n":
        return body if body.endswith("\n") else (body + "\n")
    out = body[: i + 1] + "\n" + body[i + 1 :]
    return out if out.endswith("\n") else (out + "\n")

def _is_option_line(s: str) -> bool:
    """
    Рядок вважається варіантом відповіді, якщо (після очистки префіксів)
    має формат 'A) ', 'B) ', 'C) ', 'D) ' або числовий '1) ' тощо.

    Підтримує:
      - провідні пробіли,
      - емодзі ✅/❌,
      - початкові HTML-теги <b> або <strong> перед префіксом.
    """
    if not s:
        return False

    # Приберемо пробіли зліва/справа
    s = s.strip()

    # Приберемо провідні емодзі з пробілами
    s = re.sub(r'^(?:✅|❌)\s*', '', s)

    # Приберемо початкові жирні теги, якщо вони стоять перед префіксом
    s = re.sub(r'^(?:<b>|<strong>)', '', s, flags=re.IGNORECASE)

    if len(s) < 3:
        return False

    # Пряма перевірка префікса A)/B)/... або 1)/2)/...
    return bool(re.match(r'^[A-DАБВГ1-4][\.\)]\s', s))

def _add_spacing_between_options(body: str) -> str:
    if not body:
        return body
    lines = body.splitlines()
    out: List[str] = []
    for i, line in enumerate(lines):
        out.append(line)
        if _is_option_line(line):
            if i + 1 < len(lines) and _is_option_line(lines[i + 1]):
                out.append("")
    return "\n".join(out) + ("\n" if not body.endswith("\n") else "")

def _with_spacing(body: str) -> str:
    """Працює і з \n, і з <br> — зберігає відступи після виділення відповіді."""
    if not body:
        return body
    s = body.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)  # <br> → \n
    s = _ensure_question_answers_gap(s)
    s = _add_spacing_between_options(s)
    return s

def _compose_caption_testing(
    q: dict,
    step_idx: int,
    total_in_session: int,
    highlight: Optional[Tuple[int, bool]] = None,
    hide_correct_on_wrong: bool = True
) -> str:
    bar = get_progress_bar(step_idx + 1, total_in_session)
    progress = f"{step_idx + 1}/{total_in_session}"
    body = format_question_text(
        q, highlight=highlight, hide_correct_on_wrong=hide_correct_on_wrong, mode="testing"
    )
    body = _with_spacing(body)
    return f"{bar}\n{progress}\n\n{body}"

def _compose_caption_learning(
    q: dict,
    step_idx: int,
    total_in_session: int,
    highlight: Optional[Tuple[int, bool]] = None
) -> str:
    bar = get_progress_bar(step_idx + 1, total_in_session)
    body = format_question_text(
        q, highlight=highlight, hide_correct_on_wrong=False, mode="learning"
    )
    body = _with_spacing(body)
    return f"{bar}\n\n{body}"

def _open_media_bio(path: str, filename: str) -> io.BytesIO:
    with open(path, "rb") as f:
        data = f.read()
    return _bio_with_name(data, filename)

def _decide_inline_kind_and_filename(media_type: str, media_path: str) -> Tuple[str, str]:
    base = os.path.basename(media_path)
    stem, ext = os.path.splitext(base)
    ext_low = (ext or "").lower()

    if media_type == "photo":
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

def _build_input_media(media_type: str, media_path: str, caption: str):
    kind, fname = _decide_inline_kind_and_filename(media_type, media_path)
    try:
        if kind == "photo":
            return InputMediaPhoto(media=_open_media_bio(media_path, fname), caption=caption, parse_mode="HTML")
        if kind == "animation":
            return InputMediaAnimation(media=_open_media_bio(media_path, fname), caption=caption, parse_mode="HTML")
        if kind == "video":
            return InputMediaVideo(media=_open_media_bio(media_path, fname), caption=caption, parse_mode="HTML")
        if kind == "audio":
            return InputMediaAudio(media=_open_media_bio(media_path, fname), caption=caption, parse_mode="HTML")
        return InputMediaDocument(media=_open_media_bio(media_path, fname), caption=caption, parse_mode="HTML")
    except Exception as e:
        logger.warning("[TESTING] _build_input_media failed: %s", e)
    return None

# ========= Рендер питання =========

async def _send_new_question_message(chat_id: int, bot, media_type: str, media_path: Optional[str], caption: str, kb):
    sent = None
    try:
        if media_type != "none" and media_path and os.path.exists(media_path):
            kind, fname = _decide_inline_kind_and_filename(media_type, media_path)
            with open(media_path, "rb") as f:
                bio = _bio_with_name(f.read(), fname)
            if kind == "photo":
                sent = await bot.send_photo(chat_id=chat_id, photo=bio, caption=caption, reply_markup=kb, parse_mode="HTML")
            elif kind == "animation":
                sent = await bot.send_animation(chat_id=chat_id, animation=bio, caption=caption, reply_markup=kb, parse_mode="HTML")
            elif kind == "video":
                sent = await bot.send_video(chat_id=chat_id, video=bio, caption=caption, reply_markup=kb, parse_mode="HTML")
            elif kind == "audio":
                sent = await bot.send_audio(chat_id=chat_id, audio=bio, caption=caption, reply_markup=kb, parse_mode="HTML")
            else:
                sent = await bot.send_document(chat_id=chat_id, document=bio, caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            ph = _bio_with_name(_placeholder_png_bytes(), "q.png")
            sent = await bot.send_photo(chat_id=chat_id, photo=ph, caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.exception("[TESTING] send new message failed: %s", e)
        sent = await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb, parse_mode="HTML")
    return sent

async def _render_question_on_existing_message(message, media_type: str, media_path: Optional[str], caption: str, kb) -> bool:
    try:
        if media_type == "none":
            if getattr(message, "caption", None) is not None or getattr(message, "photo", None) or getattr(message, "video", None) or getattr(message, "audio", None) or getattr(message, "document", None):
                ph = _bio_with_name(_placeholder_png_bytes(), "q.png")
                im = InputMediaPhoto(media=ph, caption=caption, parse_mode="HTML")
                await message.edit_media(media=im, reply_markup=kb)
                return True
            return False

        if not media_path or not os.path.exists(media_path):
            return False

        im = _build_input_media(media_type, media_path, caption)
        if im is None:
            return False

        await message.edit_media(media=im, reply_markup=kb)
        return True
    except Exception as e:
        logger.warning("[TESTING] render on existing message failed: %s", e)
        return False

async def _show_question(source, context: ContextTypes.DEFAULT_TYPE, q_index: int) -> None:
    questions = context.user_data.get("questions", [])
    if not questions or not (0 <= q_index < len(questions)):
        return

    order = context.user_data.get("order", []) or []
    total_in_session = len(order) if order else len(questions)
    step_idx = context.user_data.get("step", 0)

    q = questions[q_index]
    test_dir = context.user_data.get("current_test_dir")
    media_type, media_path = _detect_media(q, test_dir)

    caption = _compose_caption_testing(q, step_idx, total_in_session, highlight=None, hide_correct_on_wrong=True)
    kb = build_options_markup(q_index, highlight=False, two_columns=True)

    chat_id = _get_chat_id(source)
    bot = context.bot

    msg = getattr(source, "message", None) if not isinstance(source, Update) else None

    if msg:
        ok = await _render_question_on_existing_message(msg, media_type, media_path, caption, kb)
        if ok:
            kind, _ = _decide_inline_kind_and_filename(media_type, media_path) if (media_type != "none" and media_path) else ("photo", None)
            context.user_data["last_media_type"] = kind
            context.user_data["last_msg_id"] = msg.message_id
            return
        try:
            await msg.delete()
        except Exception:
            pass

    sent = await _send_new_question_message(chat_id, bot, media_type, media_path, caption, kb)
    if sent:
        kind, _ = _decide_inline_kind_and_filename(media_type, media_path) if (media_type != "none" and media_path) else ("photo", None)
        context.user_data["last_media_type"] = kind
        context.user_data["last_msg_id"] = sent.message_id
    else:
        context.user_data["last_media_type"] = "none"
        context.user_data.pop("last_msg_id", None)

# ========= Скорами/результати =========

def _save_answer_and_score(context: ContextTypes.DEFAULT_TYPE, q_index: int, choice: int) -> Tuple[bool, Optional[int]]:
    questions = context.user_data.get("questions", [])
    if not questions or not (0 <= q_index < len(questions)):
        return False, None
    q = questions[q_index]
    answers = q.get("answers")
    if isinstance(answers, list) and answers:
        correct = next((i for i, a in enumerate(answers[:4]) if a.get("correct")), None)
    else:
        correct = q.get("answer")
    is_ok = (choice == correct)
    if is_ok:
        context.user_data["score"] = context.user_data.get("score", 0) + 1
        context.user_data["current_streak"] = context.user_data.get("current_streak", 0) + 1
    else:
        wrong = context.user_data.get("wrong_pairs", [])
        wrong.append((q_index, choice))
        context.user_data["wrong_pairs"] = wrong
        context.user_data["current_streak"] = 0
    return is_ok, correct

def _letter(idx: Optional[int]) -> str:
    return "ABCD"[idx] if isinstance(idx, int) and 0 <= idx < 4 else "?"

def _extract_answer_text(ans_item: Any) -> str:
    if isinstance(ans_item, dict):
        for key in ("text", "answer", "value", "content"):
            if key in ans_item and isinstance(ans_item[key], str):
                return ans_item[key]
        for v in ans_item.values():
            if isinstance(v, str):
                return v
        return str(ans_item)
    if isinstance(ans_item, str):
        return ans_item
    return str(ans_item)

def _build_wrong_details_text(questions: List[dict], wrong_pairs: List[Tuple[int, int]]) -> List[str]:
    if not wrong_pairs:
        return []

    LMT = 3800
    chunks: List[str] = []
    buf = []

    def flush():
        if buf:
            chunks.append("\n".join(buf).strip())
            buf.clear()

    for idx, (q_index, chosen_idx) in enumerate(wrong_pairs, start=1):
        if not (0 <= q_index < len(questions)):
            continue
        q = questions[q_index]
        q_text = q.get("question", "").strip()

        answers = q.get("answers", [])
        if isinstance(answers, list) and answers:
            correct_idx = next((i for i, a in enumerate(answers[:4]) if isinstance(a, dict) and a.get("correct")), None)
        else:
            correct_idx = q.get("answer")

        chosen_text = ""
        correct_text = ""

        if isinstance(answers, list) and len(answers) >= 1:
            if isinstance(chosen_idx, int) and 0 <= chosen_idx < len(answers):
                chosen_text = _extract_answer_text(answers[chosen_idx])
            if isinstance(correct_idx, int) and 0 <= correct_idx < len(answers):
                correct_text = _extract_answer_text(answers[correct_idx])
        else:
            chosen_text = str(chosen_idx) if chosen_idx is not None else "-"
            correct_text = str(correct_idx) if correct_idx is not None else "-"

        block = [
            f"№{q_index + 1}",
            f"Питання: {q_text}",
            f"Ваша відповідь: {_letter(chosen_idx)}) {chosen_text}",
            f"Правильна відповідь: {_letter(correct_idx)}) {correct_text}",
            "-" * 24,
        ]

        prospective = ("\n".join(buf + block)).strip()
        if len(prospective) > LMT:
            flush()
        buf.extend(block)

    flush()
    return chunks

async def show_results(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    save: bool = False,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
) -> None:
    test_name = context.user_data.get("current_test", "Невідомий тест")
    order = context.user_data.get("order", []) or []
    total = len(order)
    score = context.user_data.get("score", 0)
    start_time: datetime = context.user_data.get("start_time") or datetime.now()
    duration = (datetime.now() - start_time).total_seconds()
    percent = (score / total * 100.0) if total else 0.0
    current_streak = context.user_data.get("current_streak", 0)
    wrong_pairs = list(context.user_data.get("wrong_pairs", []))

    if save and user_id:
        try:
            await save_user_result_db(
                user_id=user_id,
                test_name=test_name,
                mode="test",
                score=score,
                total_questions=total,
                duration=duration,
                percent=percent,
                username=username or None,
                current_streak=current_streak
            )
        except Exception as e:
            logger.warning("[TESTING] save_user_result_db failed: %s", e)

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Результат: {score}/{total} ({percent:.1f}%)",
            reply_markup=get_retry_keyboard()
        )
    except Exception as e:
        logger.warning("[TESTING] result send failed: %s", e)

    context.user_data["last_result"] = {
        "test_name": test_name,
        "score": score,
        "total": total,
        "percent": percent,
        "wrong_pairs": wrong_pairs,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }

    for k in ("mode", "order", "step", "score", "wrong_pairs", "start_time", "current_streak", "last_msg_id", "last_media_type"):
        context.user_data.pop(k, None)

async def _finish_test_and_save(source, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id = _get_chat_id(source)
        uid, uname = _get_user_from_source(source)
        await show_results(chat_id, context, save=True, user_id=uid, username=uname)
    except Exception as e:
        logger.warning("[TESTING] _finish_test_and_save wrapper failed: %s", e)

# ========= Публічні хендлери (ТЕСТ) =========

def _match_topic_filter(q: dict, topic: str) -> bool:
    if not topic:
        return True
    tps = q.get("topics")
    if not isinstance(tps, list):
        return False
    return any(isinstance(tp, str) and tp.strip().lower() == topic.strip().lower() for tp in tps)

async def handle_test_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = (update.message.text or "").strip()
    total_questions = context.user_data.get("total_questions", 0)
    if choice == "🔙 Назад":
        context.user_data["suppress_test_select_once"] = True
        context.user_data.pop("mode", None)
        context.user_data.pop("awaiting_custom_count", None)
        lang = context.bot_data.get("lang", "uk")
        await update.message.reply_text(
            t(lang, "menu_main", test=context.user_data.get("current_test", "Тест")),
            reply_markup=main_menu()
        )
        return

    # Формуємо пул із урахуванням topic_filter
    topic = context.user_data.get("topic_filter")
    questions = context.user_data.get("questions", [])
    pool = [i for i in range(total_questions) if 0 <= i < len(questions) and _match_topic_filter(questions[i], topic)] if topic else list(range(total_questions))
    if not pool:
        pool = list(range(total_questions))

    # IMPORTANT: чистимо флаг custom-count якщо обрали фіксований варіант
    context.user_data.pop("awaiting_custom_count", None)

    if choice.startswith("🔟"):
        count = 10
    elif choice.startswith("5️⃣0️⃣"):
        count = 50
    elif choice.startswith("💯"):
        count = 100
    elif choice.startswith("🔢"):
        await update.message.reply_text(
            "🔢 Введи власну кількість для опрацювання. "
            "Питання будуть обрані в роздріб по всім питанням з тесту"
        )
        context.user_data["awaiting_custom_count"] = True
        # Збережемо останній підрахований pool, щоб не рахувати двічі
        context.user_data["__pool_cache"] = pool
        return
    else:
        return

    count = max(1, min(count, len(pool)))
    if count >= len(pool):
        order = pool[:]
        random.shuffle(order)
    else:
        order = random.sample(pool, count)

    context.user_data["mode"] = "test"
    context.user_data["order"] = order
    context.user_data["step"] = 0
    context.user_data["score"] = 0
    context.user_data["wrong_pairs"] = []
    context.user_data["current_streak"] = 0
    context.user_data["start_time"] = datetime.now()
    context.user_data.pop("__pool_cache", None)

    await _show_question(update, context, order[0])

async def handle_custom_test_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Раніше цей хендлер реагував на ЛЮБЕ число і міг випадково запускати тест,
    коли користувач вводив цифри в інших режимах (додавання/редагування).
    Виправлено: працюємо тільки якщо явно чекаємо власну кількість.
    """
    # ✅ ГОЛОВНЕ ОБМЕЖЕННЯ:
    if not context.user_data.get("awaiting_custom_count"):
        # не наш випадок — ігноруємо, щоб не заважати іншим сценаріям
        return

    text = (update.message.text or "").strip()
    try:
        n = int(text)
    except ValueError:
        await update.message.reply_text("Введіть число — кількість питань.", reply_markup=main_menu())
        return

    total_questions = context.user_data.get("total_questions", 0)
    questions = context.user_data.get("questions", [])
    topic = context.user_data.get("topic_filter")

    pool = context.user_data.pop("__pool_cache", None)
    if not isinstance(pool, list):
        pool = [i for i in range(total_questions) if 0 <= i < len(questions) and _match_topic_filter(questions[i], topic)] if topic else list(range(total_questions))
        if not pool:
            pool = list(range(total_questions))

    n = max(1, min(n, len(pool)))

    if n >= len(pool):
        order = pool[:]
        random.shuffle(order)
    else:
        order = random.sample(pool, n)

    # остаточно прибираємо прапор очікування custom-count
    context.user_data.pop("awaiting_custom_count", None)

    context.user_data["mode"] = "test"
    context.user_data["order"] = order
    context.user_data["step"] = 0
    context.user_data["score"] = 0
    context.user_data["wrong_pairs"] = []
    context.user_data["current_streak"] = 0
    context.user_data["start_time"] = datetime.now()

    await _show_question(update, context, order[0])

async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split("|")
    if len(parts) != 3 or parts[0] != "ans":
        try:
            await query.answer()
        except Exception:
            pass
        return
    try:
        q_index = int(parts[1]); choice = int(parts[2])
    except ValueError:
        try:
            await query.answer()
        except Exception:
            pass
        return

    is_ok, _correct_idx = _save_answer_and_score(context, q_index, choice)

    if not is_ok:
        try:
            test_name = context.user_data.get("current_test")
            uid, _uname = _get_user_from_source(query)
            if uid and test_name is not None:
                await add_wrong_answer(uid, test_name, q_index)
        except Exception as e:
            logger.debug("[TESTING] add_wrong_answer failed: %s", e)

    try:
        await query.answer()
    except Exception:
        pass

    questions = context.user_data.get("questions", [])
    if not questions or not (0 <= q_index < len(questions)):
        return
    q = questions[q_index]

    order = context.user_data.get("order", []) or []
    total_in_session = max(1, len(order))
    step_idx = context.user_data.get("step", 0)

    mode = context.user_data.get("mode")

    if mode == "learning":
        caption = _compose_caption_learning(q, step_idx, total_in_session, highlight=(choice, is_ok))
    else:
        caption = _compose_caption_testing(q, step_idx, total_in_session, highlight=(choice, is_ok), hide_correct_on_wrong=True)

    fav_set = context.user_data.get("fav_set") or set()
    is_fav = q_index in fav_set if isinstance(fav_set, set) else False
    comments_count = q.get("comments_count", 0)
    kb = build_options_markup(q_index, highlight=True, is_favorited=is_fav, comments_count=comments_count)

    try:
        if getattr(query.message, "text", None) and not getattr(query.message, "caption", None):
            await query.message.edit_text(text=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await query.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.warning("[TESTING] edit after answer failed: %s", e)

async def next_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    order = context.user_data.get("order", [])
    step = context.user_data.get("step", 0)
    if not order:
        return

    step += 1
    if step >= len(order):
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _finish_test_and_save(query, context)
        return

    context.user_data["step"] = step
    next_q_index = order[step]
    await _show_question(query, context, next_q_index)

async def retry_wrong_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    wrong_pairs = context.user_data.get("wrong_pairs", [])
    if not wrong_pairs:
        last = context.user_data.get("last_result") or {}
        wrong_pairs = list(last.get("wrong_pairs") or [])

    if not wrong_pairs:
        await query.message.reply_text("Помилок немає — повторювати нічого 🙂", reply_markup=main_menu())
        return

    order = [i for (i, _) in wrong_pairs]
    context.user_data["mode"] = "test"
    context.user_data["order"] = order
    context.user_data["step"] = 0
    context.user_data["score"] = 0
    context.user_data["wrong_pairs"] = []
    context.user_data["current_streak"] = 0
    context.user_data["start_time"] = datetime.now()

    await _show_question(query, context, order[0])

async def detailed_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    live_total = len(context.user_data.get("order", []) or [])
    wrong_pairs = None
    title = None

    if live_total:
        live_score = context.user_data.get("score", 0)
        title = f"Детальна статистика (поточна сесія):\nПравильних: {live_score}\nУсього: {live_total}\n"
        wrong_pairs = list(context.user_data.get("wrong_pairs", []))
    else:
        last = context.user_data.get("last_result")
        if not last:
            await query.message.reply_text("Поки що немає статистики для показу.", reply_markup=main_menu())
            return
        title = (
            "Детальна статистика (останній тест):\n"
            f"Тест: {last.get('test_name','-')}\n"
            f"Правильних: {last.get('score',0)}\n"
            f"Усього: {last.get('total',0)}\n"
            f"Точність: {last.get('percent',0):.1f}%\n"
            f"Час: {last.get('finished_at','-')}\n"
        )
        wrong_pairs = list(last.get("wrong_pairs", []))

    questions = context.user_data.get("questions", []) or []
    chunks = _build_wrong_details_text(questions, wrong_pairs or [])

    if not chunks:
        await query.message.reply_text(title + "\n❌ Немає неправильних відповідей.", parse_mode=None)
        return

    first = f"{title}\n❌ Неправильні відповіді (розбір):\n\n{chunks[0]}"
    try:
        await query.message.reply_text(first)
    except Exception as e:
        logger.warning("[TESTING] send detailed first failed: %s", e)

    for chunk in chunks[1:]:
        try:
            await query.message.reply_text("Продовження розбору помилок:\n\n" + chunk)
        except Exception as e:
            logger.warning("[TESTING] send detailed chunk failed: %s", e)

async def back_to_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    for k in ("mode", "order", "step", "score", "wrong_pairs", "start_time", "current_streak", "last_msg_id", "last_media_type"):
        context.user_data.pop(k, None)
    await query.message.reply_text("Повернення до меню тесту.", reply_markup=main_menu())

async def cancel_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    keys_to_clear = {
        "mode", "order", "step", "score", "wrong_pairs", "start_time",
        "current_streak", "last_msg_id", "last_media_type",
        "learning_range", "awaiting_custom_range"
    }
    for k in keys_to_clear:
        context.user_data.pop(k, None)

    lang = context.bot_data.get("lang", "uk")
    try:
        await query.message.reply_text(
            t(lang, "menu_main", test=context.user_data.get("current_test", "Тест")),
            reply_markup=main_menu()
        )
    except Exception:
        await query.message.reply_text("Повернення до меню.", reply_markup=main_menu())

async def back_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt not in {"🔙 Назад", "⬅️ Назад"}:
        return

    if context.user_data.get("in_office"):
        context.user_data["suppress_test_select_once"] = True
        await office_buttons_handler(update, context)
        return

    mode = context.user_data.get("mode")
    order = context.user_data.get("order") or []

    if mode == "test" and not order:
        context.user_data.pop("awaiting_custom_count", None)
        context.user_data.pop("mode", None)
        context.user_data["suppress_test_select_once"] = True
        lang = context.bot_data.get("lang", "uk")
        await update.message.reply_text(
            t(lang, "menu_main", test=context.user_data.get("current_test", "Тест")),
            reply_markup=main_menu()
        )
        return

    if mode == "test" and order:
        for k in ("mode", "order", "step", "score", "wrong_pairs", "start_time", "current_streak", "last_msg_id", "last_media_type"):
            context.user_data.pop(k, None)
        context.user_data["suppress_test_select_once"] = True
        lang = context.bot_data.get("lang", "uk")
        await update.message.reply_text(
            t(lang, "menu_main", test=context.user_data.get("current_test", "Тест")),
            reply_markup=main_menu()
        )
        return

    if mode == "learning":
        context.user_data["suppress_test_select_once"] = True
        lang = context.bot_data.get("lang", "uk")
        await update.message.reply_text(
            t(lang, "menu_main", test=context.user_data.get("current_test", "Тест")),
            reply_markup=main_menu()
        )
        return

    path = context.user_data.get("browse_path")
    if isinstance(path, list):
        if path:
            path.pop()
            context.user_data["browse_path"] = path
        tree = context.bot_data.get("tests_tree")
        if not tree:
            tree = discover_tests_hierarchy("tests")
            context.bot_data["tests_tree"] = tree
        subfolders, tests, _ = build_listing_for_path(tree, path or [])
        header = "📂 Оберіть розділ або тест"
        if not subfolders and not tests:
            header += "\n(цей розділ порожній)"
        context.user_data["suppress_test_select_once"] = True
        await update.message.reply_text(
            header,
            reply_markup=browse_menu(path or [], subfolders, tests)
        )
        return

    return
