import os
import json
import glob
import aiofiles
import html
import logging
from datetime import datetime
from telegram import Update, ForceReply
from telegram.ext import ContextTypes
from utils.keyboards import comment_menu, build_options_markup

logger = logging.getLogger("test_bot")

# ---------- ВНУТРІШНІ УТИЛІТИ ----------

def _test_comments_path(test_name: str, test_dir: str) -> str:
    """
    Шлях до файлу коментарів для тесту у тій же теці, де лежить сам тест.
    """
    safe = test_name  # можна додати санацію
    return os.path.join(test_dir, f"{safe}.comments.json")

async def _load_comments_dict(test_name: str, test_dir: str) -> dict:
    """
    Завантажити словник коментарів для тесту:
    { "q_index(str)": [ {user_id, username, text, ts}, ... ] }.
    Підтримка легасі-файлів <test>_q<idx>.json.
    """
    path = _test_comments_path(test_name, test_dir)
    data: dict = {}

    if os.path.exists(path):
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                raw = await f.read()
                data = json.loads(raw) if raw.strip() else {}
                if not isinstance(data, dict):
                    data = {}
        except Exception:
            data = {}

    # Легасі: <test>_q*.json
    legacy_pattern = os.path.join(test_dir, f"{test_name}_q*.json")
    legacy_files = glob.glob(legacy_pattern)
    if legacy_files:
        for lf in legacy_files:
            try:
                async with aiofiles.open(lf, "r", encoding="utf-8") as f:
                    raw = await f.read()
                    items = json.loads(raw) if raw.strip() else []
                    if not isinstance(items, list):
                        items = []
                base = os.path.basename(lf)
                try:
                    qidx_part = base.split("_q", 1)[1].split(".json", 1)[0]
                    qidx = int(qidx_part)
                    key = str(qidx)
                    data.setdefault(key, [])
                    for c in items:
                        text = c.get("text") if isinstance(c, dict) else str(c)
                        data[key].append({
                            "user_id": c.get("user_id") if isinstance(c, dict) else None,
                            "username": c.get("username") if isinstance(c, dict) else None,
                            "text": text,
                            "ts": c.get("ts") if isinstance(c, dict) else None
                        })
                except Exception:
                    pass
            except Exception:
                pass

    return data

async def _save_comments_dict(test_name: str, test_dir: str, data: dict):
    """Зберегти агрегований словник коментарів для тесту."""
    path = _test_comments_path(test_name, test_dir)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))

# ---------- ПУБЛІЧНИЙ ХЕЛПЕР ----------

async def get_comments_count(test_name: str, q_index: int, test_dir: str) -> int:
    """
    Повертає кількість коментарів для питання.
    """
    data = await _load_comments_dict(test_name, test_dir)
    return len(data.get(str(q_index), []))

# ---------- ХЕНДЛЕРИ ----------

async def handle_comment_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка введення тексту коментаря."""
    if not context.user_data.get("awaiting_comment"):
        return

    msg = update.message
    if not msg or not msg.text:
        return

    # Не записувати у коментар «Назад/Cancel»
    if msg.text.strip() in {"🔙 Назад", "⬅️ Назад", "/cancel", "Відміна", "Скасувати"}:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username
    text = msg.text.strip()

    test_name = context.user_data.get("current_test")
    test_dir = context.user_data.get("current_test_dir")
    q_index = context.user_data.get("comment_q_index", context.user_data.get("current_q_index"))

    if not test_name or not test_dir or q_index is None:
        context.user_data.pop("awaiting_comment", None)
        await msg.reply_text("❓ Немає активного питання для коментаря.")
        return

    if not text:
        await msg.reply_text("❌ Порожній коментар не збережено. Напишіть текст")
        return

    data = await _load_comments_dict(test_name, test_dir)
    key = str(q_index)
    data.setdefault(key, [])

    data[key].append({
        "user_id": user_id,
        "username": username,
        "text": text[:1000],
        "ts": datetime.utcnow().isoformat() + "Z"
    })

    await _save_comments_dict(test_name, test_dir, data)

    context.user_data.pop("awaiting_comment", None)
    context.user_data.pop("comment_q_index", None)

    await msg.reply_text("💾 Коментар збережено.")

    # Оновлення клавіатури під питанням
    try:
        comments_count = len(data.get(key, []))
        is_fav = q_index in context.user_data.get("fav_set", set())

        chat_id = context.user_data.get("question_chat_id")
        msg_id = context.user_data.get("question_message_id")
        if chat_id and msg_id:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=build_options_markup(
                    q_index,
                    highlight=True,
                    is_favorited=is_fav,
                    comments_count=comments_count
                )
            )
    except Exception as e:
        logger.error(f"[COMMENTS] Failed to update question keyboard: {e}")

async def comment_entry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вхід у меню коментарів."""
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    if len(data) != 2:
        await query.answer("⚠️ Невірні дані.", show_alert=False)
        return

    try:
        q_index = int(data[1])
    except ValueError:
        await query.answer("⚠️ Невірний індекс.", show_alert=False)
        return

    test_name = context.user_data.get("current_test")
    if not test_name:
        await query.answer("❓ Спочатку оберіть тест.", show_alert=True)
        return

    context.user_data["comment_q_index"] = q_index
    context.user_data["awaiting_comment"] = False

    await query.message.reply_text("💬 Оберіть дію з коментарями:", reply_markup=comment_menu(q_index))

async def comment_write_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✍️ Написати коментар."""
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    if len(data) != 2:
        await query.answer("⚠️ Невірні дані.", show_alert=False)
        return

    try:
        q_index = int(data[1])
    except ValueError:
        await query.answer("⚠️ Невірний індекс.", show_alert=False)
        return

    test_name = context.user_data.get("current_test")
    if not test_name:
        await query.answer("❓ Спочатку оберіть тест.", show_alert=True)
        return

    context.user_data["comment_q_index"] = q_index
    context.user_data["awaiting_comment"] = True

    await query.message.reply_text(
        "✍️ Введіть текст коментаря (до 1000 символів):",
        reply_markup=ForceReply(selective=True, input_field_placeholder="Твій коментар…")
    )

async def comment_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """👀 Переглянути коментарі."""
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    if len(data) != 2:
        await query.answer("⚠️ Невірні дані.", show_alert=False)
        return

    try:
        q_index = int(data[1])
    except ValueError:
        await query.answer("⚠️ Невірний індекс.", show_alert=False)
        return

    test_name = context.user_data.get("current_test")
    test_dir = context.user_data.get("current_test_dir")
    if not test_name or not test_dir:
        await query.answer("❓ Спочатку оберіть тест.", show_alert=True)
        return

    comments_dict = await _load_comments_dict(test_name, test_dir)
    comments = comments_dict.get(str(q_index), [])

    if not comments:
        await query.message.reply_text("ℹ️ Для цього питання ще немає коментарів.", reply_markup=comment_menu(q_index))
        return

    body = [f"💬 Коментарі до питання {q_index + 1}:\n"]
    for i, c in enumerate(comments, 1):
        uname = c.get("username") or f"id{c.get('user_id', '')}"
        txt = c.get("text", "")
        body.append(f"{i}. <b>{html.escape(uname)}</b>: {html.escape(txt)}")

    msg = "\n\n".join(body)
    await query.message.reply_text(msg[:4000], parse_mode="HTML", reply_markup=comment_menu(q_index))

async def comment_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⬅️/🔙 Назад з меню коментарів — просто скидаємо стан."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("awaiting_comment", None)
    context.user_data.pop("comment_q_index", None)
    await query.message.reply_text("✅ Готово. Можна продовжувати.")
