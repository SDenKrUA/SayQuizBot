import os
import json
import logging
from typing import Dict, List, Optional, Tuple

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ApplicationHandlerStop

from utils.formatting import format_question_text

logger = logging.getLogger("test_bot")

TESTS_DIR = "tests"
QOWNERS_FILE = os.path.join(TESTS_DIR, "_qowners.json")
IGNORED_JSON_SUFFIXES = (".comments.json", ".docx.meta.json")

MAX_TEXT_LEN = 1000

# Підтримувані розширення
IMG_EXTS = ["jpg", "jpeg", "png", "webp", "gif"]
VIDEO_EXTS = ["mp4", "3gp", "avi", "mkv", "webm", "mpeg", "mpg", "m4v", "mov", "ts", "flv"]
AUDIO_EXTS = ["mp3", "wav", "ogg", "m4a", "aac", "flac"]
DOC_EXTS = ["pdf", "docx", "doc", "xlsx"]


# =========================
# Utils / Helpers
# =========================
def _ensure_qowners_file() -> None:
    try:
        os.makedirs(TESTS_DIR, exist_ok=True)
        if not os.path.exists(QOWNERS_FILE):
            with open(QOWNERS_FILE, "w", encoding="utf-8") as f:
                f.write("{}")
    except Exception as e:
        logger.error("[EDIT_Q] ensure_qowners error: %s", e)


def _load_qowners() -> Dict[str, Dict[str, Dict[str, object]]]:
    _ensure_qowners_file()
    try:
        with open(QOWNERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("[EDIT_Q] load _qowners.json error: %s", e)
        return {}


def _find_json_for_test(test_dir: str, test_name: str) -> Optional[str]:
    exact = os.path.join(test_dir, f"{test_name}.json")
    if os.path.exists(exact):
        return exact
    try:
        jsons = [
            f for f in os.listdir(test_dir)
            if f.lower().endswith(".json") and not any(f.lower().endswith(suf) for suf in IGNORED_JSON_SUFFIXES)
        ]
    except Exception:
        return None
    if not jsons:
        return None
    low = test_name.lower()
    candidates = sorted(jsons, key=lambda n: (0 if n[:-5].lower() == low else 1, len(n)))
    return os.path.join(test_dir, candidates[0])


def _rel_key(json_path: Optional[str]) -> str:
    if not json_path:
        return ""
    return os.path.relpath(json_path, TESTS_DIR).replace("\\", "/")


def _load_json_list(path: Optional[str]) -> List[dict]:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or []
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("[EDIT_Q] failed to load %s: %s", path, e)
        return []


def _save_json_list(path: str, items: List[dict]) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error("[EDIT_Q] failed to save %s: %s", path, e)
        return False


def _combined_questions_and_index_map(
    test_dir: str,
    test_name: str
) -> Tuple[List[dict], int, str, Optional[str], Optional[str], Optional[str]]:
    """
    Повертає:
      - загальний список питань (база + кастом),
      - довжину бази,
      - rel_base,
      - шлях до base.json,
      - шлях до custom.json (якщо існує; інакше None),
      - rel_custom (або None)
    """
    base_json = _find_json_for_test(test_dir, test_name)
    custom_json = os.path.join(test_dir, f"{test_name} (custom).json")

    base_questions = _load_json_list(base_json)
    custom_questions = _load_json_list(custom_json) if os.path.exists(custom_json) else []

    questions = (base_questions or []) + (custom_questions or [])
    base_len = len(base_questions)

    rel_base = _rel_key(base_json)
    rel_custom = _rel_key(custom_json) if os.path.exists(custom_json) else None
    return questions, base_len, rel_base, base_json, custom_json if os.path.exists(custom_json) else None, rel_custom


def _owner_global_indices_for_user(
    user_id: int,
    qowners: Dict[str, Dict[str, Dict[str, object]]],
    rel_base: str,
    base_len: int,
    rel_custom: Optional[str]
) -> List[int]:
    """
    Повертає глобальні індекси (1..N) питань, які належать користувачу.
    """
    result: List[int] = []

    # Базові
    if rel_base and rel_base in qowners:
        for k, v in qowners[rel_base].items():
            try:
                if int(v.get("user_id")) == int(user_id):
                    idx = int(k)
                    if idx > 0:
                        result.append(idx)
            except Exception:
                continue

    # Кастомні (зсув на base_len)
    if rel_custom and rel_custom in qowners:
        for k, v in qowners[rel_custom].items():
            try:
                if int(v.get("user_id")) == int(user_id):
                    idx = int(k)
                    if idx > 0:
                        result.append(base_len + idx)
            except Exception:
                continue

    return sorted(set(result))


def _stop_chain(context: ContextTypes.DEFAULT_TYPE):
    """
    Глушимо інші хендлери для цього апдейту.
    """
    context.user_data["suppress_test_select_once"] = True
    raise ApplicationHandlerStop


def _media_dirs_for(test_dir: str, test_name: str, base_json_path: Optional[str]) -> Tuple[str, str]:
    """
    Повертає (base_media_dir, custom_media_dir)
    base_media_dir: tests/<basename(base_json)>
    custom_media_dir: tests/<test_name> (custom)
    """
    # базова тека медіа — за фактичною основою імені JSON (як у state_sync)
    base_dir_name = test_name
    if base_json_path:
        base_dir_name = os.path.splitext(os.path.basename(base_json_path))[0]
    base_media_dir = os.path.join(test_dir, base_dir_name)
    custom_media_dir = os.path.join(test_dir, f"{test_name} (custom)")
    return base_media_dir, custom_media_dir


def _media_candidates_for_q(num: int) -> List[str]:
    """
    Усі можливі імена файлів для питання num по всіх типах (для видалення/перевірки).
    """
    names = []
    # images
    for pref in ["image", "img", "q"]:
        for ext in IMG_EXTS:
            names.append(f"{pref}{num}.{ext}")
    # video
    for pref in ["video", "vid", "q"]:
        for ext in VIDEO_EXTS:
            names.append(f"{pref}{num}.{ext}")
    # audio
    for pref in ["audio", "aud", "q"]:
        for ext in AUDIO_EXTS:
            names.append(f"{pref}{num}.{ext}")
    # docs
    for pref in ["doc", "document", "q"]:
        for ext in DOC_EXTS:
            names.append(f"{pref}{num}.{ext}")
    return names


def _present_media(media_dir: str, qnum: int) -> List[str]:
    """
    Повертає список знайдених медіа-файлів для питання (повні шляхи).
    """
    found = []
    if not media_dir or not os.path.isdir(media_dir):
        return found
    for name in _media_candidates_for_q(qnum):
        p = os.path.join(media_dir, name)
        if os.path.exists(p):
            found.append(p)
    return found


def _delete_media(media_dir: str, qnum: int) -> int:
    """
    Видаляє всі медіа файли для питання; повертає кількість видалених.
    """
    if not media_dir or not os.path.isdir(media_dir):
        return 0
    removed = 0
    for name in _media_candidates_for_q(qnum):
        p = os.path.join(media_dir, name)
        try:
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except Exception:
            pass
    return removed


def _save_file_to(path: str, file_obj) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return True if file_obj and path else False
    except Exception:
        return False


# =========================
# Клавіатури
# =========================
def _field_menu_kb(idx: int) -> InlineKeyboardMarkup:
    # «Медіа» має бути першою
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📎 Медіа", callback_data=f"editq_field|media|{idx}")],
        [InlineKeyboardButton("📝 Текст питання", callback_data=f"editq_field|question|{idx}")],
        [
            InlineKeyboardButton("A", callback_data=f"editq_field|ansA|{idx}"),
            InlineKeyboardButton("B", callback_data=f"editq_field|ansB|{idx}"),
            InlineKeyboardButton("C", callback_data=f"editq_field|ansC|{idx}"),
            InlineKeyboardButton("D", callback_data=f"editq_field|ansD|{idx}"),
        ],
        [
            InlineKeyboardButton("✅ Правильна (1-4)", callback_data=f"editq_field|correct|{idx}"),
        ],
        [
            InlineKeyboardButton("🏷 Теми", callback_data=f"editq_field|topics|{idx}"),
            InlineKeyboardButton("💡 Пояснення", callback_data=f"editq_field|explanation|{idx}"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="editq_back")],
    ])


def _editq_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 Показати всі питання", callback_data="editq_show_all")],
        [InlineKeyboardButton("✏️ Редагувати", callback_data="editq_edit"),
         InlineKeyboardButton("🗑 Видалити", callback_data="editq_delete")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="editq_back")],
    ])


def _editq_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="editq_back")]])


def _media_edit_kb(gidx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Без медіа", callback_data=f"editq_media_clear|{gidx}")],
        [InlineKeyboardButton("❎ Скасувати", callback_data="editq_back")],
    ])


# =========================
# Public entry: /edit_question
# =========================
async def editq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user = update.effective_user
    current_test = context.user_data.get("current_test")
    current_dir = context.user_data.get("current_test_dir")

    if not current_test or not current_dir:
        await msg.reply_text("❌ Спочатку оберіть тест.")
        return

    # Вимикаємо режими навчання/тесту
    context.user_data.pop("mode", None)

    questions, base_len, rel_base, base_json_path, custom_json_path, rel_custom = _combined_questions_and_index_map(
        current_dir, current_test
    )

    qowners = _load_qowners()
    owned_global = _owner_global_indices_for_user(user.id, qowners, rel_base, base_len, rel_custom)

    if not owned_global:
        await msg.reply_text("ℹ️ У цьому тесті ви ще не додавали власних питань.", reply_markup=_editq_back_kb())
        return

    nums_text = ", ".join(str(i) for i in owned_global)
    await msg.reply_text(
        f"✅ Знайдено ваших питань: {len(owned_global)}\nНомери у цьому тесті: {nums_text}",
        reply_markup=_editq_main_kb()
    )

    context.user_data["editq_state"] = {
        "owned": owned_global,
        "base_len": base_len,
        "base_json_path": base_json_path,
        "custom_json_path": custom_json_path,
        "rel_base": rel_base,
        "rel_custom": rel_custom,
        "questions_cache": questions,
    }


# =========================
# Callbacks: меню / вибір / back / clear media
# =========================
async def editq_buttons_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = (query.data or "")

    st = context.user_data.get("editq_state") or {}
    current_test = context.user_data.get("current_test")
    current_dir = context.user_data.get("current_test_dir")

    # Ледаче відновлення стану
    if not st and current_test and current_dir:
        questions, base_len, rel_base, base_json_path, custom_json_path, rel_custom = _combined_questions_and_index_map(
            current_dir, current_test
        )
        qowners = _load_qowners()
        owned_global = _owner_global_indices_for_user(update.effective_user.id, qowners, rel_base, base_len, rel_custom)
        st = {
            "owned": owned_global,
            "base_len": base_len,
            "base_json_path": base_json_path,
            "custom_json_path": custom_json_path,
            "rel_base": rel_base,
            "rel_custom": rel_custom,
            "questions_cache": questions,
        }
        context.user_data["editq_state"] = st

    if data == "editq_back":
        try:
            await query.edit_message_text("⬅️ Повернулися.")
        except Exception:
            await query.message.reply_text("⬅️ Повернулися.")
        for k in ("editq_mode", "editq_field", "editq_idx"):
            context.user_data.pop(k, None)
        return

    if data == "editq_show_all":
        owned = st.get("owned") or []
        questions = st.get("questions_cache") or []
        if not owned:
            await query.message.reply_text("ℹ️ У вас немає власних питань у цьому тесті.", reply_markup=_editq_back_kb())
            return

        chunks: List[str] = []
        for idx in owned:
            if 1 <= idx <= len(questions):
                q = questions[idx - 1]
                text = f"#{idx}\n" + format_question_text(q, highlight=None, mode="learning", show_topics=True)
                chunks.append(text)

        buf = ""
        for piece in chunks:
            if len(buf) + len(piece) + 2 > 3900:
                await query.message.reply_html(buf, disable_web_page_preview=True)
                buf = ""
            buf += piece + "\n"
        if buf.strip():
            await query.message.reply_html(buf, disable_web_page_preview=True)
        return

    if data == "editq_edit":
        owned = st.get("owned") or []
        if not owned:
            await query.message.reply_text("ℹ️ Спочатку додайте питання, щоб було що редагувати.", reply_markup=_editq_back_kb())
            return
        context.user_data.pop("mode", None)
        context.user_data["editq_mode"] = "await_num_for_edit"
        context.user_data["suppress_test_select_once"] = True
        await query.message.reply_text("✏️ Введіть номер питання у цьому тесті для редагування:", reply_markup=_editq_back_kb())
        return

    if data == "editq_delete":
        owned = st.get("owned") or []
        if not owned:
            await query.message.reply_text("ℹ️ Немає ваших питань для видалення.", reply_markup=_editq_back_kb())
            return
        context.user_data.pop("mode", None)
        context.user_data["editq_mode"] = "await_num_for_delete"
        context.user_data["suppress_test_select_once"] = True
        await query.message.reply_text("🗑 Введіть номер питання у цьому тесті для видалення:", reply_markup=_editq_back_kb())
        return

    # Очистити медіа
    if data.startswith("editq_media_clear|"):
        parts = data.split("|")
        if len(parts) != 2 or not parts[1].isdigit():
            return
        gidx = int(parts[1])
        questions = st.get("questions_cache") or []
        owned = st.get("owned") or []
        base_len = int(st.get("base_len") or 0)
        base_json = st.get("base_json_path")
        current_test = context.user_data.get("current_test")
        current_dir = context.user_data.get("current_test_dir")
        if gidx < 1 or gidx > len(questions) or gidx not in owned:
            await query.message.reply_text("⛔ Це питання не належить вам або номер некоректний.", reply_markup=_editq_back_kb())
            return

        # Локальний індекс та тека
        if gidx <= base_len:
            local_idx = gidx
            target_media_dir, _ = _media_dirs_for(current_dir, current_test, base_json)
        else:
            local_idx = gidx - base_len
            _, target_media_dir = _media_dirs_for(current_dir, current_test, base_json)

        removed = _delete_media(target_media_dir, local_idx)
        await query.message.reply_text(f"🗑 Видалено медіа-файлів: {removed}.")
        return

    # Вибір поля редагування
    if data.startswith("editq_field|"):
        parts = data.split("|")
        if len(parts) != 3:
            return
        field, idx_s = parts[1], parts[2]
        if not idx_s.isdigit():
            return
        gidx = int(idx_s)

        questions = st.get("questions_cache") or []
        owned = st.get("owned") or []

        if gidx < 1 or gidx > len(questions):
            await query.message.reply_text("❌ Невірний номер питання.", reply_markup=_editq_back_kb())
            return
        if gidx not in owned:
            await query.message.reply_text("⛔ Це питання не належить вам.", reply_markup=_editq_back_kb())
            return

        q = questions[gidx - 1]
        pretty = format_question_text(q, highlight=None, mode="learning", show_topics=True)

        # Активуємо режими очікування
        if field == "media":
            # Показати наявне медіа та попросити нове
            base_json = st.get("base_json_path")
            base_len = int(st.get("base_len") or 0)
            current_test = context.user_data.get("current_test")
            current_dir = context.user_data.get("current_test_dir")

            # локальний номер у файлі:
            if gidx <= base_len:
                qnum = gidx
                target_media_dir, _ = _media_dirs_for(current_dir, current_test, base_json)
            else:
                qnum = gidx - base_len
                _, target_media_dir = _media_dirs_for(current_dir, current_test, base_json)

            existing = _present_media(target_media_dir, qnum)
            if existing:
                rels = [os.path.basename(p) for p in existing]
                have_text = "Наявне медіа:\n- " + "\n- ".join(rels)
            else:
                have_text = "Медіа для цього питання відсутнє."

            context.user_data["editq_mode"] = "await_media_input"
            context.user_data["editq_idx"] = gidx
            context.user_data["suppress_test_select_once"] = True

            await query.message.reply_text(
                f"📎 Редагування медіа для питання #{gidx}.\n{have_text}\n\n"
                "Надішліть фото / MP3 / MP4 / PDF / DOC / DOCX / XLSX, або натисніть «Без медіа».",
                reply_markup=_media_edit_kb(gidx)
            )
            return

        # інші поля — текстові
        context.user_data["editq_mode"] = "await_field_input"
        context.user_data["editq_field"] = field
        context.user_data["editq_idx"] = gidx
        context.user_data["suppress_test_select_once"] = True

        if field == "question":
            await query.message.reply_html(
                f"📝 Редагуємо текст питання #{gidx}:\n\n{pretty}\n\nНадішліть новий текст питання (до {MAX_TEXT_LEN} символів).",
                disable_web_page_preview=True
            )
            return
        if field in {"ansA", "ansB", "ansC", "ansD"}:
            label = field[-1]
            await query.message.reply_html(
                f"✏️ Редагуємо відповідь {label}) для питання #{gidx}:\n\n{pretty}\n\nНадішліть новий текст відповіді (до {MAX_TEXT_LEN} символів).",
                disable_web_page_preview=True
            )
            return
        if field == "correct":
            await query.message.reply_text(
                f"✅ Питання #{gidx}. Надішліть номер правильної відповіді (1–4).",
                reply_markup=_editq_back_kb()
            )
            return
        if field == "topics":
            await query.message.reply_text(
                f"🏷 Питання #{gidx}. Надішліть теми через кому (або «-», щоб очистити).",
                reply_markup=_editq_back_kb()
            )
            return
        if field == "explanation":
            await query.message.reply_text(
                f"💡 Питання #{gidx}. Надішліть пояснення (або «-», щоб очистити).",
                reply_markup=_editq_back_kb()
            )
            return


async def editq_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await editq_buttons_cb(update, context)


async def editq_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text("⬅️ Повернулися.")
    except Exception:
        await query.message.reply_text("⬅️ Повернулися.")
    for k in ("editq_mode", "editq_field", "editq_idx"):
        context.user_data.pop(k, None)


async def editq_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    for k in ("editq_mode", "editq_field", "editq_idx", "editq_state"):
        context.user_data.pop(k, None)
    try:
        await query.edit_message_text("❎ Операцію скасовано.")
    except Exception:
        await query.message.reply_text("❎ Операцію скасовано.")


# =========================
# Text & Media flow
# =========================
async def editq_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробляє:
      - введення номера (await_num_for_edit / await_num_for_delete)
      - введення нового вмісту поля (await_field_input)
      - прийом медіа (await_media_input): photo/document/audio/video
    """
    msg = update.message
    if not msg:
        return

    text = (msg.text or "").strip() if msg.text else None
    mode = context.user_data.get("editq_mode")

    if mode not in {"await_num_for_edit", "await_num_for_delete", "await_field_input", "await_media_input"}:
        return

    # Глушимо інші хендлери цієї події
    context.user_data["suppress_test_select_once"] = True

    st = context.user_data.get("editq_state") or {}
    questions = st.get("questions_cache") or []
    owned = st.get("owned") or []
    base_len = int(st.get("base_len") or 0)
    base_json = st.get("base_json_path")
    custom_json = st.get("custom_json_path")

    # ===== Ввід номера для редагування/видалення =====
    if mode in {"await_num_for_edit", "await_num_for_delete"}:
        if text in {"⬅️ Назад", "🔙 Назад"}:
            context.user_data.pop("editq_mode", None)
            await msg.reply_text("❎ Скасовано.", reply_markup=_editq_back_kb())
            _stop_chain(context)

        if not text or not text.isdigit():
            await msg.reply_text("❌ Введіть номер (ціле число).", reply_markup=_editq_back_kb())
            _stop_chain(context)

        gidx = int(text)
        if gidx < 1 or gidx > len(questions):
            await msg.reply_text("❌ Невірний номер питання.", reply_markup=_editq_back_kb())
            _stop_chain(context)

        if gidx not in owned:
            await msg.reply_text("⛔ Це питання не належить вам.", reply_markup=_editq_back_kb())
            _stop_chain(context)

        q = questions[gidx - 1]
        pretty = format_question_text(q, highlight=None, mode="learning", show_topics=True)

        if mode == "await_num_for_edit":
            await msg.reply_html(
                f"✏️ Обрали питання #{gidx} для редагування:\n\n{pretty}\n\nОберіть, що саме редагувати:",
                disable_web_page_preview=True,
                reply_markup=_field_menu_kb(gidx)
            )
            context.user_data["editq_mode"] = "await_field_choice"
            _stop_chain(context)

        if mode == "await_num_for_delete":
            await msg.reply_html(
                f"🗑 Обрано питання #{gidx} для видалення:\n\n{pretty}\n\n(Підтвердження та повне видалення — окремим кроком.)",
                disable_web_page_preview=True
            )
            context.user_data.pop("editq_mode", None)
            _stop_chain(context)

    # ===== Ввід нового значення поля =====
    if mode == "await_field_input":
        field = context.user_data.get("editq_field")
        gidx = int(context.user_data.get("editq_idx") or 0)

        if not field or gidx < 1 or gidx > len(questions) or gidx not in owned:
            await msg.reply_text("⚠️ Стан редагування втрачено або некоректний. Спробуйте знову /edit_question.")
            for k in ("editq_mode", "editq_field", "editq_idx"):
                context.user_data.pop(k, None)
            _stop_chain(context)

        # Файл та локальний індекс у ньому
        if gidx <= base_len:
            target_json = base_json
            local_idx = gidx - 1
        else:
            target_json = custom_json
            local_idx = (gidx - base_len) - 1

        if not target_json or not os.path.exists(target_json):
            await msg.reply_text("❌ Не знайдено файл тесту для редагування.")
            for k in ("editq_mode", "editq_field", "editq_idx"):
                context.user_data.pop(k, None)
            _stop_chain(context)

        items = _load_json_list(target_json)
        if local_idx < 0 or local_idx >= len(items) or not isinstance(items[local_idx], dict):
            await msg.reply_text("❌ Питання не знайдено у файлі.")
            for k in ("editq_mode", "editq_field", "editq_idx"):
                context.user_data.pop(k, None)
            _stop_chain(context)

        qobj = items[local_idx]

        # Зміни
        if field == "question":
            if not text:
                await msg.reply_text("❌ Текст не може бути порожнім.")
                _stop_chain(context)
            if len(text) > MAX_TEXT_LEN:
                await msg.reply_text(f"❌ Текст питання має бути до {MAX_TEXT_LEN} символів.")
                _stop_chain(context)
            qobj["question"] = str(text)

        elif field in {"ansA", "ansB", "ansC", "ansD"}:
            if not text:
                await msg.reply_text("❌ Текст не може бути порожнім.")
                _stop_chain(context)
            if len(text) > MAX_TEXT_LEN:
                await msg.reply_text(f"❌ Текст відповіді має бути до {MAX_TEXT_LEN} символів.")
                _stop_chain(context)
            answers = qobj.get("answers")
            if not isinstance(answers, list) or len(answers) < 4:
                answers = [{"text": "", "correct": False} for _ in range(4)]
            pos = {"ansA": 0, "ansB": 1, "ansC": 2, "ansD": 3}[field]
            if not isinstance(answers[pos], dict):
                answers[pos] = {"text": "", "correct": False}
            answers[pos]["text"] = str(text)
            qobj["answers"] = answers

        elif field == "correct":
            if text not in {"1", "2", "3", "4"}:
                await msg.reply_text("❌ Введіть число 1–4.")
                _stop_chain(context)
            choose = int(text) - 1
            answers = qobj.get("answers")
            if not isinstance(answers, list) or len(answers) < 4:
                answers = [{"text": "", "correct": False} for _ in range(4)]
            for i, a in enumerate(answers[:4]):
                if not isinstance(a, dict):
                    answers[i] = {"text": str(a), "correct": False}
            for i in range(4):
                answers[i]["correct"] = (i == choose)
            qobj["answers"] = answers

        elif field == "topics":
            topics = []
            if text and text.lower() not in {"-", "—", "_"}:
                # розбити за комами/крапками з комою/слешем/|
                import re
                parts = re.split(r"[;,/|]", text)
                for p in parts:
                    v = (p or "").strip()
                    if v:
                        topics.append(v)
            qobj["topics"] = topics

        elif field == "explanation":
            val = (text or "").strip()
            if val.lower() in {"-", "—", "_"}:
                val = ""
            if len(val) > MAX_TEXT_LEN:
                await msg.reply_text(f"❌ Пояснення має бути до {MAX_TEXT_LEN} символів.")
                _stop_chain(context)
            qobj["explanation"] = val

        else:
            await msg.reply_text("⚠️ Невідоме поле редагування.")
            for k in ("editq_mode", "editq_field", "editq_idx"):
                context.user_data.pop(k, None)
            _stop_chain(context)

        # Зберігаємо
        items[local_idx] = qobj
        if not _save_json_list(target_json, items):
            await msg.reply_text("❌ Не вдалося зберегти зміни.")
            _stop_chain(context)

        # Оновлення кешу
        current_test = context.user_data.get("current_test")
        current_dir = context.user_data.get("current_test_dir")
        questions2, base_len2, rel_base2, base_json2, custom_json2, rel_custom2 = _combined_questions_and_index_map(
            current_dir, current_test
        )
        st.update({
            "questions_cache": questions2,
            "base_len": base_len2,
            "base_json_path": base_json2,
            "custom_json_path": custom_json2,
            "rel_base": rel_base2,
            "rel_custom": rel_custom2,
        })
        context.user_data["editq_state"] = st

        q_new = questions2[gidx - 1] if 1 <= gidx <= len(questions2) else qobj
        pretty = format_question_text(q_new, highlight=None, mode="learning", show_topics=True)
        await msg.reply_html(
            f"✅ Зміни збережено для питання #{gidx}.\n\n{pretty}\n\nОбрати інше поле для редагування:",
            disable_web_page_preview=True,
            reply_markup=_field_menu_kb(gidx)
        )

        for k in ("editq_mode", "editq_field"):
            context.user_data.pop(k, None)
        _stop_chain(context)

    # ===== Прийом МЕДІА =====
    if mode == "await_media_input":
        gidx = int(context.user_data.get("editq_idx") or 0)
        if gidx < 1 or gidx > len(questions) or gidx not in owned:
            await msg.reply_text("⚠️ Стан редагування медіа втрачено або некоректний. Спробуйте знову /edit_question.")
            for k in ("editq_mode", "editq_idx"):
                context.user_data.pop(k, None)
            _stop_chain(context)

        # Визначаємо локальний індекс у файлі і теку з медіа
        current_test = context.user_data.get("current_test")
        current_dir = context.user_data.get("current_test_dir")
        base_media_dir, custom_media_dir = _media_dirs_for(current_dir, current_test, base_json)

        if gidx <= base_len:
            qnum = gidx
            media_dir = base_media_dir
        else:
            qnum = gidx - base_len
            media_dir = custom_media_dir

        os.makedirs(media_dir, exist_ok=True)

        # Медіа з повідомлення
        photo = msg.photo if hasattr(msg, "photo") else None
        audio = getattr(msg, "audio", None)
        document = getattr(msg, "document", None)
        video = getattr(msg, "video", None)
        voice = getattr(msg, "voice", None)

        # Голосове — не приймаємо
        if voice:
            await msg.reply_text("ℹ️ Голосові (OGG/OPUS) не підтримуються. Надішліть MP3 як файл/аудіо.")
            _stop_chain(context)

        # Фото
        if photo:
            # Беремо найбільше
            p = photo[-1]
            file = await context.bot.get_file(p.file_id)
            dest = os.path.join(media_dir, f"image{qnum}.jpg")
            await file.download_to_drive(dest)
            await msg.reply_text(f"📷 Фото збережено для #{gidx} як {os.path.basename(dest)}.")
            _stop_chain(context)

        # Відео
        if video:
            fname = (video.file_name or "").lower() if video.file_name else ""
            mime = (video.mime_type or "").lower() if video.mime_type else ""
            if not (fname.endswith(".mp4") or "mp4" in mime):
                await msg.reply_text("❌ Підтримується лише MP4. Надішліть .mp4 або файл-документ MP4.")
                _stop_chain(context)
            file = await context.bot.get_file(video.file_id)
            dest = os.path.join(media_dir, f"video{qnum}.mp4")
            await file.download_to_drive(dest)
            await msg.reply_text(f"🎬 Відео збережено для #{gidx} як {os.path.basename(dest)}.")
            _stop_chain(context)

        # Аудіо
        if audio:
            fname = (audio.file_name or "").lower()
            mime = (audio.mime_type or "").lower()
            if not (fname.endswith(".mp3") or "mpeg" in mime or "audio/mp3" in mime):
                await msg.reply_text("❌ Підтримується лише MP3. Надішліть .mp3.")
                _stop_chain(context)
            file = await context.bot.get_file(audio.file_id)
            dest = os.path.join(media_dir, f"audio{qnum}.mp3")
            await file.download_to_drive(dest)
            await msg.reply_text(f"🎧 Аудіо збережено для #{gidx} як {os.path.basename(dest)}.")
            _stop_chain(context)

        # Документ (MP4 як документ або PDF/DOC/DOCX/XLSX/MP3)
        if document:
            dfname = (document.file_name or "").lower()
            dmime = (document.mime_type or "").lower()
            if not dfname:
                await msg.reply_text("❌ Документ повинен мати розширення.")
                _stop_chain(context)

            file = await context.bot.get_file(document.file_id)

            # mp4 як документ
            if dfname.endswith(".mp4") or "video/mp4" in dmime:
                dest = os.path.join(media_dir, f"video{qnum}.mp4")
                await file.download_to_drive(dest)
                await msg.reply_text(f"🎬 Відео (документ) збережено для #{gidx} як {os.path.basename(dest)}.")
                _stop_chain(context)

            # mp3 як документ
            if dfname.endswith(".mp3") or "audio/mpeg" in dmime or "audio/mp3" in dmime:
                dest = os.path.join(media_dir, f"audio{qnum}.mp3")
                await file.download_to_drive(dest)
                await msg.reply_text(f"🎧 Аудіо (документ) збережено для #{gidx} як {os.path.basename(dest)}.")
                _stop_chain(context)

            # інші документи
            allowed_doc = any(dfname.endswith(f".{ext}") for ext in DOC_EXTS)
            if not allowed_doc:
                await msg.reply_text("❌ Підтримуються PDF/DOC/DOCX/XLSX або MP3/MP4.")
                _stop_chain(context)

            ext = os.path.splitext(dfname)[1]
            dest = os.path.join(media_dir, f"doc{qnum}{ext}")
            await file.download_to_drive(dest)
            await msg.reply_text(f"📄 Документ збережено для #{gidx} як {os.path.basename(dest)}.")
            _stop_chain(context)

        # Якщо це текст під час очікування медіа
        if text:
            await msg.reply_text("ℹ️ Надішліть фото/аудіо/відео/документ або натисніть «Без медіа».", reply_markup=_media_edit_kb(gidx))
            _stop_chain(context)


async def editq_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await editq_text_reply(update, context)
