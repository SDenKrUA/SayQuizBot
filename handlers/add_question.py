import os
import io
import json
import asyncio
import aiofiles
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

MAX_TEXT_LEN = 1000
MAX_PHOTO_SIZE = 10 * 1024  # 10 KB
TESTS_DIR = "tests"
QOWNERS_FILE = os.path.join(TESTS_DIR, "_qowners.json")

# Спроба підключити Pillow для стиснення
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception as _e:
    PIL_AVAILABLE = False
    print("[ADD_Q] Pillow (PIL) не встановлено — буду намагатись використати найменший розмір фото з Telegram.")

# ===== VIP: права доступу та запити =====
from handlers.vip_tests.vip_storage import (
    can_edit_vip,
    get_meta_for_rel,
    save_meta_for_rel,
)

def _strip_custom_suffix(name: str) -> str:
    """Повертає базову назву тесту без суфікса ' (custom)' в кінці."""
    if not isinstance(name, str):
        return name
    suffix = " (custom)"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return name

def _is_custom_test(name: str) -> bool:
    return isinstance(name, str) and name.endswith(" (custom)")

def _custom_json_path(base_test_name: str, target_dir: str | None) -> str:
    """Шлях до JSON для кастомних питань конкретного тесту (в тій же теці, що тест)."""
    base = _strip_custom_suffix(base_test_name)
    folder = target_dir or TESTS_DIR
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{base} (custom).json")

def _base_json_path(base_test_name: str, target_dir: str | None) -> str:
    base = _strip_custom_suffix(base_test_name)
    folder = target_dir or TESTS_DIR
    return os.path.join(folder, f"{base}.json")

def _base_media_dir(base_test_name: str, target_dir: str | None) -> str:
    """Папка медіа для базового тесту: <dir>/<base>"""
    base = _strip_custom_suffix(base_test_name)
    folder = target_dir or TESTS_DIR
    return os.path.join(folder, base)

def _custom_media_dir(base_test_name: str, target_dir: str | None) -> str:
    """Папка медіа для кастомного тесту: <dir>/<base> (custom)"""
    base = _strip_custom_suffix(base_test_name)
    folder = target_dir or TESTS_DIR
    return os.path.join(folder, f"{base} (custom)")

# --- Нормалізація тексту питання для анти-дублікатів ---
import re as _re
def _normalize_q(s: str) -> str:
    s = str(s or "")
    s = s.strip()
    s = _re.sub(r"^\s*\d+[\.\)]\s*", "", s)  # прибрати початкову нумерацію "12. " / "12) "
    s = _re.sub(r"\s+", " ", s)              # зжати пробіли
    return s.lower()

def _parse_question_number(qtext: str) -> int | None:
    """
    Витягує номер на початку "NN. ..." або "NN)".
    """
    if not qtext:
        return None
    m = _re.match(r"\s*(\d+)[\.\)]\s*", qtext)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def _rel_test_key(json_path: str) -> str:
    """Ключ для _qowners.json: шлях до тесту відносно tests/ із / як роздільником."""
    return os.path.relpath(json_path, TESTS_DIR).replace("\\", "/")

# ===== QOWNERS HELPERS (синхронні) =====
def _ensure_qowners_file() -> None:
    """Гарантовано створити tests/_qowners.json як {} якщо його немає."""
    try:
        os.makedirs(TESTS_DIR, exist_ok=True)
        if not os.path.exists(QOWNERS_FILE):
            with open(QOWNERS_FILE, "w", encoding="utf-8") as f:
                f.write("{}")
    except Exception as e:
        print(f"[ADD_Q] ensure _qowners error: {e}")

def _load_qowners_sync() -> dict:
    """Синхронно прочитати _qowners.json (dict)."""
    _ensure_qowners_file()
    try:
        with open(QOWNERS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        data = json.loads(content) if content.strip() else {}
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        print(f"[ADD_Q] _qowners load error: {e}")
        return {}

def _save_qowners_sync(data: dict) -> None:
    """Синхронно записати _qowners.json (atomic replace по можливості)."""
    try:
        tmp = QOWNERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, QOWNERS_FILE)
    except Exception as e:
        print(f"[ADD_Q] _qowners save error: {e}")

def _record_qowner_sync(json_path: str, q_index_1based: int, user_id: int, username: str | None) -> None:
    """Додати/оновити власника питання у _qowners.json (синхронно)."""
    qowners = _load_qowners_sync()
    key = _rel_test_key(json_path)
    entry = qowners.get(key)
    if not isinstance(entry, dict):
        entry = {}
    entry[str(q_index_1based)] = {
        "user_id": int(user_id),
        "username": username or ""
    }
    qowners[key] = entry
    _save_qowners_sync(qowners)

# ===== Inline-клавіші для гейту =====
def _addq_gate_kb() -> InlineKeyboardMarkup:
    # Перейменовано згідно з вимогами:
    #  - «Продовжити»
    #  - «Запросити доступ»
    #  - «Скасувати»
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Продовжити", callback_data="addq_req_continue")],
        [InlineKeyboardButton("📨 Запросити доступ", callback_data="addq_req_send")],
        [InlineKeyboardButton("❎ Скасувати", callback_data="addq_req_cancel")],
    ])

# ===== Нове: універсальна інлайн-кнопка «Скасувати» для майстра =====
def _addq_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❎ Скасувати", callback_data="addq_cancel")]
    ])

# ===== Старт сценарію =====
async def handle_add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок сценарію додавання питання з урахуванням прав доступу."""
    user = update.effective_user
    user_id = user.id
    username = user.username

    current_test = context.user_data.get("current_test")
    current_dir = context.user_data.get("current_test_dir")

    if not current_test:
        await update.message.reply_text("❌ Спочатку оберіть тест, до якого хочете додати питання.")
        return

    # 🔑 ВАЖЛИВО: прибираємо режим навчання/тестування, щоб не блокувало введення
    context.user_data.pop("mode", None)

    # ===== ЛОГІКА ГЕЙТУ =====
    # Гейт показується ТІЛЬКИ для базового тесту (без "(custom)") і лише якщо користувач не має прав.
    is_custom = _is_custom_test(current_test)

    if not is_custom:
        # Базовий тест — перевіряємо права
        base_path = _base_json_path(current_test, current_dir)
        # Відносний шлях від tests/
        rel = os.path.relpath(base_path, TESTS_DIR).replace("\\", "/")
        # Якщо файла нема — теж використовуємо теоретичне rel
        allowed = can_edit_vip(rel, user_id, username)
        if not allowed:
            # Показуємо ГЕЙТ з оновленим текстом
            context.user_data["addq_gate"] = {
                "target_test": current_test,
                "target_dir": current_dir or TESTS_DIR,
                "rel": rel
            }
            text = (
                "🔒 Ви намагаєтесь додати питання до приватного тесту.\n\n"
                "▶️ Якщо ви **продовжите**, для вас буде створено тест з такою самою назвою, "
                "в тій самій директорії, але з приміткою **(custom)**. "
                "Ваше питання буде додано саме у цей новий тест.\n\n"
                "📨 Якщо ви хочете мати змогу **редагувати оригінальний тест** та додавати до нього питання і медіа, "
                "натисніть «Запросити доступ» — запит піде власнику. "
                "Коли власник схвалить ваш запит, ви побачите цей тест у розділі **Мій кабінет → Спільні тести**.\n\n"
                "❎ «Скасувати» просто поверне вас до тесту."
            )
            await update.message.reply_text(text, reply_markup=_addq_gate_kb())
            return

    # Якщо це (custom) АБО є права на базовий тест — одразу запускаємо майстер
    await _start_addq_flow(update, context, target_test=current_test, target_dir=current_dir)
    print(f"[ADD_Q] user={user_id} START for test={current_test} dir={current_dir} (base_edit={not is_custom})")

async def _start_addq_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, *, target_test: str, target_dir: str | None):
    """Запускає майстер додавання питання на конкретний тест (базовий або custom)."""
    u = update.effective_user
    context.user_data["add_question"] = {
        "step": "question",
        "data": {
            "answers": [],
            "topics": [],        # нове поле
            "explanation": "",   # нове поле
            "target_test": target_test,
            "target_test_base": _strip_custom_suffix(target_test),
            "target_dir": target_dir or TESTS_DIR,
            # автор питання — для _qowners.json
            "author_id": u.id if u else None,
            "author_username": (u.username if u else "") or "",
        },
    }
    context.user_data["add_question_active"] = True
    await update.message.reply_text(
        f"✍️ Введи текст питання для тесту «{target_test}» (до {MAX_TEXT_LEN} символів):",
        reply_markup=_addq_cancel_kb()
    )

# ===== Callback-и гейту =====
async def addq_req_continue_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продовжити без запиту — одразу стартуємо майстер для (custom)."""
    query = update.callback_query
    await query.answer()

    gate = context.user_data.pop("addq_gate", None)
    if not gate:
        await query.answer("Немає активної операції.", show_alert=False)
        return

    base_name = gate["target_test"]
    target_dir = gate["target_dir"] or TESTS_DIR
    custom_name = f"{_strip_custom_suffix(base_name)} (custom)"

    # Імітуємо текстовий старт
    class _MsgProxy:
        def __init__(self, msg):
            self.chat_id = msg.chat_id
        async def reply_text(self, *args, **kwargs):
            await query.message.reply_text(*args, **kwargs)

    proxy_update = type("ProxyUpdate", (), {"message": _MsgProxy(query.message), "effective_user": query.from_user})()

    await _start_addq_flow(proxy_update, context, target_test=custom_name, target_dir=target_dir)

async def addq_req_send_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запросити доступ — додаємо у meta.pending цього тесту."""
    query = update.callback_query
    await query.answer()

    gate = context.user_data.get("addq_gate")
    if not gate:
        await query.answer("Немає активної операції.", show_alert=False)
        return

    rel = gate["rel"]
    meta = get_meta_for_rel(rel)
    pend = list(meta.get("pending", []))

    u = query.from_user
    req = {
        "user_id": u.id,
        "username": u.username or "",
    }

    # не дублюємо, якщо вже є така заявка
    exists = any((r.get("user_id") == req["user_id"]) for r in pend)
    if not exists:
        pend.append(req)
        meta["pending"] = pend
        save_meta_for_rel(rel, meta)

    await query.message.reply_text("✅ Запит на доступ надіслано власнику тесту.\n"
                                   "Коли власник схвалить запит, тест зʼявиться у «Мій кабінет → Спільні тести».")
    # Приберемо гейт зі стану
    context.user_data.pop("addq_gate", None)

async def addq_req_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасувати — просто закрити і прибрати стан."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("addq_gate", None)
    await query.message.reply_text("❎ Скасовано. Ви можете повернутися до тесту.")

# ====== Основний майстер кроків ======
def _parse_topics_line(text: str) -> list[str]:
    """
    Парсить рядок тем, розділених комами/крапкою з комою/слешем.
    Порожні та крапки відкидаються.
    """
    raw = text.strip()
    if not raw or raw in {"-", "—", "_", "без тем", "без темы", "no", "none", "skip"}:
        return []
    # розділювачі: кома/крапка з комою/слеш/вертикальна риска
    parts = _re.split(r"[;,/|]", raw)
    out = []
    for p in parts:
        v = p.strip()
        if v and v != ".":
            out.append(v)
    return out

async def handle_add_question_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок сценарію додавання питання (текст/варіанти/теми/пояснення/медіа)"""
    # ⛔️ ГАРД: якщо активний флоу «Додати окремий файл», не перехоплюємо ні текст, ні медіа
    vip_single = context.user_data.get("vip_single") or {}
    if vip_single.get("await_index") or vip_single.get("await_file"):
        return

    user_id = update.effective_user.id
    flow = context.user_data.get("add_question")
    if not flow:
        return

    step = flow.get("step")
    text = update.message.text if update.message else None
    photo = update.message.photo if update.message else None
    audio = getattr(update.message, "audio", None)
    document = getattr(update.message, "document", None)
    video = getattr(update.message, "video", None)
    voice = getattr(update.message, "voice", None)
    data = flow["data"]

    # Ігноруємо «Назад» як контент питання/відповіді
    if text and text.strip() in {"🔙 Назад", "⬅️ Назад"}:
        await update.message.reply_text("ℹ️ Спочатку заверши або відмiни додавання питання (натисни «❎ Скасувати» або «Без файлу»).",
                                        reply_markup=_addq_cancel_kb())
        return

    # === КРОК 1: питання ===
    if step == "question":
        if not text or len(text) > MAX_TEXT_LEN:
            await update.message.reply_text(f"❌ Текст питання має бути до {MAX_TEXT_LEN} символів.",
                                            reply_markup=_addq_cancel_kb())
            return

        # --- Перевірка дубліката + підрахунок нумерації ---
        base_name = data.get("target_test_base") or data.get("target_test") or "Custom"
        target_dir = data.get("target_dir") or TESTS_DIR

        # Визначимо, куди зберігатимемо: якщо додаємо у (custom) → працюємо з (custom).json, інакше — з базовим .json
        target_is_custom = _is_custom_test(data.get("target_test"))
        custom_path = _custom_json_path(base_name, target_dir)
        main_path = _base_json_path(base_name, target_dir)
        json_path_for_saving = custom_path if target_is_custom else main_path

        duplicate_found = None
        duplicate_text = None
        total_existing = 0
        needle_norm = _normalize_q(text)

        # Перевіряємо дублікати по місцю збереження (і по другому файлу теж, щоб не плодити дубль)
        paths_to_check = [p for p in [main_path, custom_path] if p]
        seen_norms = set()
        for pth in paths_to_check:
            if os.path.exists(pth):
                try:
                    async with aiofiles.open(pth, "r", encoding="utf-8") as f:
                        content = await f.read()
                        questions = json.loads(content) if content.strip() else []
                        if isinstance(questions, list):
                            total_existing += len(questions)
                            for q in questions:
                                q_text = str(q.get("question", "")).strip()
                                qn = _normalize_q(q_text)
                                if qn in seen_norms:
                                    continue
                                seen_norms.add(qn)
                                if qn == needle_norm:
                                    duplicate_found = "цьому тесті"
                                    duplicate_text = q_text
                                    break
                except Exception:
                    pass
            if duplicate_found:
                break

        if duplicate_found:
            context.user_data.pop("add_question", None)
            context.user_data["add_question_active"] = False
            await update.message.reply_text(
                f"⚠️ Таке питання вже існує у {duplicate_found}:\n\n«{duplicate_text}»"
            )
            return

        # Нумерація
        stripped = text.strip()
        will_prefix_number = True
        if _re.match(r"^\s*\d+\.\s", stripped):
            will_prefix_number = False

        # Рахуємо за основним (база + кастом), щоб порядковість була глобальна для відображення
        next_number = total_existing + 1
        if will_prefix_number:
            text = f"{next_number}. {stripped}"

        data["question"] = text
        data["json_save_path"] = json_path_for_saving  # збережемо, куди писати
        flow["step"] = "answer_1"
        await update.message.reply_text("✍️ Введи варіант відповіді 1 (до 1000 символів):",
                                        reply_markup=_addq_cancel_kb())
        print(f"[ADD_Q] user={user_id} step=question text='{text}' saved question")
        return

    # === КРОК 2–5: відповіді ===
    if step.startswith("answer_"):
        idx = int(step.split("_")[1]) - 1
        if not text or len(text) > MAX_TEXT_LEN:
            await update.message.reply_text(f"❌ Відповідь має бути до {MAX_TEXT_LEN} символів.",
                                            reply_markup=_addq_cancel_kb())
            return
        data["answers"].append({"text": text, "correct": False})
        print(f"[ADD_Q] user={user_id} step={step} saved answer {idx+1}: '{text}'")

        if idx < 3:
            flow["step"] = f"answer_{idx+2}"
            await update.message.reply_text(f"✍️ Введи варіант відповіді {idx+2} (до 1000 символів):",
                                            reply_markup=_addq_cancel_kb())
        else:
            flow["step"] = "correct_answer"
            await update.message.reply_text("✅ Укажіть номер правильної відповіді (1–4):",
                                            reply_markup=_addq_cancel_kb())
        return

    # === КРОК 6: правильна відповідь ===
    if step == "correct_answer":
        if not text or text not in ["1", "2", "3", "4"]:
            await update.message.reply_text("❌ Введіть число від 1 до 4.",
                                            reply_markup=_addq_cancel_kb())
            return
        idx = int(text) - 1
        if idx < len(data["answers"]):
            data["answers"][idx]["correct"] = True
            # 🔹 НОВЕ: після правильного — питаємо теми
            flow["step"] = "topics"
            await update.message.reply_text(
                "🏷 Додайте теми (через кому), або напишіть «-» щоб пропустити.\n"
                "Напр.: `насоси, механіка, змащення`",
                reply_markup=_addq_cancel_kb()
            )
            print(f"[ADD_Q] user={user_id} marked correct={text}")
        return

    # === КРОК 7: TOPICS ===
    if step == "topics":
        topics = _parse_topics_line(text or "")
        data["topics"] = topics
        flow["step"] = "explanation"
        await update.message.reply_text(
            "📝 Введіть пояснення до питання (або «-» щоб пропустити).",
            reply_markup=_addq_cancel_kb()
        )
        print(f"[ADD_Q] user={user_id} topics={topics}")
        return

    # === КРОК 8: EXPLANATION ===
    if step == "explanation":
        expl = (text or "").strip() if text else ""
        if expl in {"-", "—", "_", "без пояснення", "без объяснения", "no", "none", "skip"}:
            expl = ""
        if len(expl) > MAX_TEXT_LEN:
            await update.message.reply_text(f"❌ Пояснення має бути до {MAX_TEXT_LEN} символів.",
                                            reply_markup=_addq_cancel_kb())
            return
        data["explanation"] = expl
        flow["step"] = "media"
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Без файлу", callback_data="addq_skip")],
                [InlineKeyboardButton("❎ Скасувати", callback_data="addq_cancel")],
            ]
        )
        await update.message.reply_text(
            "📎 Надішліть **фото/MP3/MP4/PDF/DOC/DOCX/XLSX** або натисніть «Без файлу», щоб завершити.",
            reply_markup=kb
        )
        print(f"[ADD_Q] user={user_id} explanation_set len={len(expl)}")
        return

    # === КРОК 9: МЕДІА (фото/аудіо/відео/документ) або пропуск ===
    if step == "media":
        target_dir = data.get("target_dir") or TESTS_DIR
        target_is_custom = _is_custom_test(data.get("target_test"))
        base_name = data.get("target_test_base") or data.get("target_test") or "Custom"
        media_dir = _custom_media_dir(base_name, target_dir) if target_is_custom else _base_media_dir(base_name, target_dir)
        os.makedirs(media_dir, exist_ok=True)

        # інтерпретація "пропустити"
        if text and text.strip().lower() in {"пропустити", "без зображення", "без изображения", "no image", "skip", "без файлу", "без файла"}:
            print(f"[ADD_Q] user={user_id} skipped media (text)")
            q_index = await _finalize_and_save_question(data, context)  # індекс (1-based)
            from handlers.state_sync import reload_current_test_state
            await reload_current_test_state(context)
            context.user_data.pop("add_question", None)
            context.user_data["add_question_active"] = False
            await update.message.reply_text("✅ Питання збережено без файлу.\n🔄 Каталог оновлено")
            return

        # номер питання -> номер медіа
        qnum = _parse_question_number(data.get("question", "") or "") or 1

        # ==== Фото ====
        if photo:
            photo_size = photo[-1] if PIL_AVAILABLE else photo[0]
            file = await context.bot.get_file(photo_size.file_id)
            image_path = os.path.join(media_dir, f"image{qnum}.jpg")

            if PIL_AVAILABLE:
                ok_img = await _compress_and_save_telegram_file(file, image_path, MAX_PHOTO_SIZE)
                if not ok_img:
                    await file.download_to_drive(image_path)
                    print("[ADD_Q] Compress failed, saved original.")
            else:
                await file.download_to_drive(image_path)

            print(f"[ADD_Q] user={user_id} saved IMAGE {image_path}")
            q_index = await _finalize_and_save_question(data, context)
            from handlers.state_sync import reload_current_test_state
            await reload_current_test_state(context)
            context.user_data.pop("add_question", None)
            context.user_data["add_question_active"] = False
            await update.message.reply_text("✅ Питання збережено з фото.\n🔄 Каталог оновлено")
            return

        # ==== Аудіо (MP3) ====
        if audio:
            fname = (audio.file_name or "").lower()
            mime = (audio.mime_type or "").lower()
            if not (fname.endswith(".mp3") or "mpeg" in mime or "audio/mp3" in mime):
                await update.message.reply_text("❌ Підтримується лише **MP3**. Надішліть .mp3 як файл/аудіо або натисніть «Без файлу».")
                return
            file = await context.bot.get_file(audio.file_id)
            audio_path = os.path.join(media_dir, f"audio{qnum}.mp3")
            await file.download_to_drive(audio_path)
            print(f"[ADD_Q] user={user_id} saved AUDIO {audio_path}")
            q_index = await _finalize_and_save_question(data, context)
            from handlers.state_sync import reload_current_test_state
            await reload_current_test_state(context)
            context.user_data.pop("add_question", None)
            context.user_data["add_question_active"] = False
            await update.message.reply_text("✅ Питання збережено з аудіо.\n🔄 Каталог оновлено")
            return

        # MP3 або MP4 можуть прийти як документ
        if document:
            dfname = (document.file_name or "").lower()
            dmime = (document.mime_type or "").lower()

            # MP3 як документ
            if dfname.endswith(".mp3") or "audio/mpeg" in dmime or "audio/mp3" in dmime:
                file = await context.bot.get_file(document.file_id)
                audio_path = os.path.join(media_dir, f"audio{qnum}.mp3")
                await file.download_to_drive(audio_path)
                print(f"[ADD_Q] user={user_id} saved AUDIO(doc) {audio_path}")
                q_index = await _finalize_and_save_question(data, context)
                from handlers.state_sync import reload_current_test_state
                await reload_current_test_state(context)
                context.user_data.pop("add_question", None)
                context.user_data["add_question_active"] = False
                await update.message.reply_text("✅ Питання збережено з аудіо.\n🔄 Каталог оновлено")
                return

        # ==== Відео (MP4) ====
        if video:
            fname = (video.file_name or "").lower() if video.file_name else ""
            mime = (video.mime_type or "").lower() if video.mime_type else ""
            if not (fname.endswith(".mp4") or "mp4" in mime):
                await update.message.reply_text("❌ Підтримується лише **MP4**. Надішліть .mp4 або натисніть «Без файлу».")
                return
            file = await context.bot.get_file(video.file_id)
            video_path = os.path.join(media_dir, f"video{qnum}.mp4")
            await file.download_to_drive(video_path)
            print(f"[ADD_Q] user={user_id} saved VIDEO {video_path}")
            q_index = await _finalize_and_save_question(data, context)
            from handlers.state_sync import reload_current_test_state
            await reload_current_test_state(context)
            context.user_data.pop("add_question", None)
            context.user_data["add_question_active"] = False
            await update.message.reply_text("✅ Питання збережено з відео.\n🔄 Каталог оновлено")
            return

        # Документ (PDF/DOC/DOCX/XLSX) або MP4 як документ
        if document:
            dfname = (document.file_name or "").lower()
            dmime = (document.mime_type or "").lower()
            if not dfname:
                await update.message.reply_text("❌ Документ повинен мати розширення (.pdf/.doc/.docx/.xlsx/.mp4).")
                return

            # MP4 як документ
            if dfname.endswith(".mp4") or "video/mp4" in dmime:
                file = await context.bot.get_file(document.file_id)
                video_path = os.path.join(media_dir, f"video{qnum}.mp4")
                await file.download_to_drive(video_path)
                print(f"[ADD_Q] user={user_id} saved VIDEO(doc) {video_path}")
                q_index = await _finalize_and_save_question(data, context)
                from handlers.state_sync import reload_current_test_state
                await reload_current_test_state(context)
                context.user_data.pop("add_question", None)
                context.user_data["add_question_active"] = False
                await update.message.reply_text("✅ Питання збережено з відео.\n🔄 Каталог оновлено")
                return

            allowed_doc = (dfname.endswith(".pdf") or dfname.endswith(".doc") or
                           dfname.endswith(".docx") or dfname.endswith(".xlsx"))
            if not allowed_doc:
                await update.message.reply_text("❌ Підтримуються **PDF/DOC/DOCX/XLSX** або **MP3/MP4**. Надішліть один із цих форматів або натисніть «Без файлу».")
                return

            file = await context.bot.get_file(document.file_id)
            ext = os.path.splitext(dfname)[1]
            doc_path = os.path.join(media_dir, f"doc{qnum}{ext}")
            await file.download_to_drive(doc_path)
            print(f"[ADD_Q] user={user_id} saved DOC {doc_path}")
            q_index = await _finalize_and_save_question(data, context)
            from handlers.state_sync import reload_current_test_state
            await reload_current_test_state(context)
            context.user_data.pop("add_question", None)
            context.user_data["add_question_active"] = False
            await update.message.reply_text("✅ Питання збережено з документом.\n🔄 Каталог оновлено")
            return

        # ==== Voice (OGG/OPUS) — не підтримуємо як медіа питання ====
        if voice:
            await update.message.reply_text("ℹ️ Голосові повідомлення (voice) — це OGG/OPUS.\nБудь ласка, надішліть **MP3-файл** (через скріпку) або натисніть «Без файлу».")
            return

        # Якщо сюди дійшли — файлу не було або це непідтримуваний тип
        await update.message.reply_text(
            "❌ Надішліть **фото/MP3/MP4/PDF/DOC/DOCX/XLSX** або натисніть «Без файлу».",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("Без файлу", callback_data="addq_skip")],
                    [InlineKeyboardButton("❎ Скасувати", callback_data="addq_cancel")],
                ]
            )
        )

async def skip_image_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка inline-кнопки 'Без файлу' під час кроку media."""
    query = update.callback_query
    await query.answer()

    flow = context.user_data.get("add_question")
    if not flow or flow.get("step") != "media":
        await query.answer("Немає активного додавання питання.", show_alert=False)
        return

    data = flow["data"]
    print(f"[ADD_Q] user={query.from_user.id} skipped media (button)")
    q_index = await _finalize_and_save_question(data, context)

    from handlers.state_sync import reload_current_test_state
    await reload_current_test_state(context)

    context.user_data.pop("add_question", None)
    context.user_data["add_question_active"] = False

    await query.message.reply_text("✅ Питання збережено без файлу.\n🔄 Каталог оновлено")

# ===== Нове: універсальний cancel для майстра =====
async def addq_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування будь-якого кроку майстра додавання питання (inline '❎ Скасувати')."""
    query = update.callback_query
    await query.answer()

    # Приберемо будь-який стан майстра
    context.user_data.pop("add_question", None)
    context.user_data["add_question_active"] = False

    # Скасуємо також можливий гейт (на випадок, якщо натиснули там)
    context.user_data.pop("addq_gate", None)

    try:
        await query.edit_message_text("❎ Додавання питання скасовано.")
    except Exception:
        await query.message.reply_text("❎ Додавання питання скасовано.")

# ===== ВНУТРІШНЄ ЗБЕРЕЖЕННЯ =====
async def _finalize_and_save_question(data: dict, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Формуємо об'єкт питання та зберігаємо його у визначений для цього flow JSON-файл.
    Повертає 1-базовий індекс створеного питання (для запису у _qowners.json).
    """
    question_text = str(data.get("question", "")).strip()
    answers_list = data.get("answers", [])
    target_dir = data.get("target_dir") or TESTS_DIR
    base_name = data.get("target_test_base") or data.get("target_test") or "Custom"

    # нові поля
    topics_list = data.get("topics") or []
    if not isinstance(topics_list, list):
        topics_list = []
    # фільтр пустих
    topics_list = [str(x).strip() for x in topics_list if str(x).strip()]

    explanation = str(data.get("explanation", "") or "")
    if len(explanation) > MAX_TEXT_LEN:
        explanation = explanation[:MAX_TEXT_LEN]

    sanitized_answers = [
        {"text": str(a.get("text", "")), "correct": bool(a.get("correct", False))}
        for a in answers_list
    ]

    # ⚠️ ВАЖЛИВО: НЕ додаємо у JSON посилань на медіа (за домовленістю)
    question_obj = {
        "question": question_text,
        "answers": sanitized_answers,
        "topics": topics_list,
        "explanation": explanation
    }

    # КУДИ ПИШЕМО:
    json_path = data.get("json_save_path")
    if not json_path:
        # fallback — для сумісності зі старими станами
        target_is_custom = _is_custom_test(data.get("target_test"))
        json_path = _custom_json_path(base_name, target_dir) if target_is_custom else _base_json_path(base_name, target_dir)

    questions = []
    if os.path.exists(json_path):
        try:
            async with aiofiles.open(json_path, "r", encoding="utf-8") as f:
                content = await f.read()
                questions = json.loads(content) if content.strip() else []
                if not isinstance(questions, list):
                    questions = []
        except Exception:
            questions = []

    # Індекс майбутнього питання (1-based) — після додавання буде саме таким
    new_q_index_1based = len(questions) + 1

    questions.append(question_obj)

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    async with aiofiles.open(json_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(questions, ensure_ascii=False, indent=2))

    print(f"[ADD_Q] saved JSON {json_path}, total={len(questions)}")

    # === ЗАПИС У _qowners.json (синхронно/надійно) ===
    try:
        author_id = data.get("author_id")
        author_username = data.get("author_username") or ""
        if author_id:
            _record_qowner_sync(json_path, new_q_index_1based, int(author_id), author_username)
            print(f"[ADD_Q] qowner recorded: key={_rel_test_key(json_path)} idx={new_q_index_1based} user={author_id}")
        else:
            print("[ADD_Q] author_id missing — skip qowner record")
    except Exception as e:
        print(f"[ADD_Q] failed to record qowner: {e}")

    from utils.loader import discover_tests, discover_tests_hierarchy
    try:
        context.bot_data["tests_catalog"] = discover_tests(TESTS_DIR)
        context.bot_data["tests_tree"] = discover_tests_hierarchy(TESTS_DIR)
        print("[ADD_Q] Catalog & tree reloaded after adding question")
    except Exception as e:
        print(f"[ADD_Q] Failed to reload catalog/tree: {e}")

    return new_q_index_1based

# ====== Компресія зображення ======
def _compress_image_file_to_limit_sync(src_path: str, dest_path: str, limit_bytes: int) -> bool:
    try:
        img = Image.open(src_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        max_side = max(img.size)
        if max_side > 1000:
            scale = 1000.0 / max_side
            new_size = (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale)))
            img = img.resize(new_size, Image.LANCZOS)

        qualities = [85, 75, 65, 55, 45, 35, 30, 25, 20, 18, 16, 14, 12, 10]
        best_buf = None
        best_size = None
        cur_img = img
        width, height = cur_img.size

        while True:
            for q in qualities:
                buf = io.BytesIO()
                cur_img.save(buf, format="JPEG", quality=q, optimize=True, progressive=True)
                data = buf.getvalue()
                size = len(data)

                if best_size is None or size < best_size:
                    best_size = size
                    best_buf = data

                if size <= limit_bytes:
                    with open(dest_path, "wb") as f:
                        f.write(data)
                    return True

            if width <= 60 or height <= 60:
                break
            width = max(1, int(width * 0.85))
            height = max(1, int(height * 0.85))
            cur_img = cur_img.resize((width, height), Image.LANCZOS)

        if best_buf:
            with open(dest_path, "wb") as f:
                f.write(best_buf)
            return len(best_buf) <= limit_bytes

        return False
    except Exception as e:
        print(f"[ADD_Q] Image compress error: {e}")
        return False

async def _compress_and_save_telegram_file(file_obj, dest_path: str, limit_bytes: int) -> bool:
    tmp_path = dest_path + ".tmp"
    try:
        await file_obj.download_to_drive(tmp_path)
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(
            None, _compress_image_file_to_limit_sync, tmp_path, dest_path, limit_bytes
        )
        return ok
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
