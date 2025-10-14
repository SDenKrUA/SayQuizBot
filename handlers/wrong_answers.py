# handlers/wrong_answers.py
import os
import aiosqlite
import logging
from typing import List, Tuple, Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

logger = logging.getLogger("test_bot.wrong")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "stats.db")


# ===================== DB helpers =====================

async def _ensure_table(conn: aiosqlite.Connection):
    """Create table for wrong answers if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS wrong_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            test_name TEXT NOT NULL,
            q_index INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, test_name, q_index) ON CONFLICT IGNORE
        );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_wa_user_test ON wrong_answers(user_id, test_name);")
    await conn.commit()


async def _get_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_PATH)
    await _ensure_table(conn)
    return conn


# ===================== Public API (used by other handlers) =====================

async def record_wrong_answer(user_id: int, test_name: str, q_index: int) -> None:
    """
    Save (deduplicated) wrong question for a user & test.
    Safe to call many times; duplicates are ignored.
    """
    if not test_name or q_index is None:
        return
    try:
        conn = await _get_conn()
        await conn.execute(
            "INSERT OR IGNORE INTO wrong_answers(user_id, test_name, q_index) VALUES(?,?,?)",
            (user_id, test_name, int(q_index))
        )
        await conn.commit()
        await conn.close()
    except Exception as e:
        logger.warning("[WRONG] record failed: %s", e)


async def get_wrong_tests(user_id: int) -> List[Tuple[str, int]]:
    """Return list of (test_name, count_wrong) for the user."""
    try:
        conn = await _get_conn()
        async with conn.execute("""
            SELECT test_name, COUNT(*) AS cnt
            FROM wrong_answers
            WHERE user_id=?
            GROUP BY test_name
            ORDER BY test_name
        """, (user_id,)) as cur:
            rows = await cur.fetchall()
        await conn.close()
        return [(r[0], r[1]) for r in rows]
    except Exception as e:
        logger.warning("[WRONG] get_wrong_tests failed: %s", e)
        return []


async def get_wrong_indices(user_id: int, test_name: str) -> List[int]:
    """Return list of q_index for a user & test (sorted asc)."""
    try:
        conn = await _get_conn()
        async with conn.execute("""
            SELECT q_index
            FROM wrong_answers
            WHERE user_id=? AND test_name=?
            ORDER BY q_index
        """, (user_id, test_name)) as cur:
            rows = await cur.fetchall()
        await conn.close()
        return [int(r[0]) for r in rows]
    except Exception as e:
        logger.warning("[WRONG] get_wrong_indices failed: %s", e)
        return []


async def clear_wrong_for_test(user_id: int, test_name: str) -> int:
    """Delete wrong answers for a test; return deleted count."""
    try:
        conn = await _get_conn()
        cur = await conn.execute(
            "DELETE FROM wrong_answers WHERE user_id=? AND test_name=?",
            (user_id, test_name)
        )
        await conn.commit()
        deleted = cur.rowcount or 0
        await conn.close()
        return max(deleted, 0)
    except Exception as e:
        logger.warning("[WRONG] clear failed: %s", e)
        return 0


# ===================== UI builders =====================

def _kb_tests_with_actions(pairs: List[Tuple[str, int]]) -> InlineKeyboardMarkup:
    """
    Build an inline keyboard that lists tests; for each test:
      Row 1: 📘 <test> (N)
      Row 2: ▶️ Опрацювати | 🧹 Очистити
    """
    rows = []
    for test_name, cnt in pairs:
        title = f"📘 {test_name} ({cnt})"
        rows.append([InlineKeyboardButton(title, callback_data=f"wa_head|{test_name}")])
        rows.append([
            InlineKeyboardButton("▶️ Опрацювати", callback_data=f"wa_work|{test_name}"),
            InlineKeyboardButton("🧹 Очистити", callback_data=f"wa_clear|{test_name}"),
        ])
    if not rows:
        rows = [[InlineKeyboardButton("🔄 Оновити", callback_data="wa_refresh")]]
    return InlineKeyboardMarkup(rows)


def _kb_pick_mode(test_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 Навчання", callback_data=f"wa_mode_learn|{test_name}")],
        [InlineKeyboardButton("📝 Тест", callback_data=f"wa_mode_test|{test_name}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="wa_back")]
    ])


# ===================== Entry command =====================

async def wrong_answers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /wrong_answers — show per-test wrong sets with actions.
    Also used by 'Мої помилки' in Office.
    """
    user_id = update.effective_user.id
    pairs = await get_wrong_tests(user_id)

    if not pairs:
        await update.message.reply_text("ℹ️ Помилок поки немає. Спробуй пройти тестування 😉")
        return

    await update.message.reply_text(
        "❌ Тести з помилками. Обери дію для кожного:",
        reply_markup=_kb_tests_with_actions(pairs)
    )


# ===================== Callback handlers =====================

async def wa_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Single entry for all 'wa_*' callback buttons.
    """
    q = update.callback_query
    await q.answer()
    data = (q.data or "")
    user_id = q.from_user.id

    if data == "wa_refresh":
        pairs = await get_wrong_tests(user_id)
        try:
            await q.message.edit_reply_markup(reply_markup=_kb_tests_with_actions(pairs))
        except Exception:
            await q.message.reply_text("Оновлено.", reply_markup=_kb_tests_with_actions(pairs))
        return

    parts = data.split("|", 1)
    cmd = parts[0]
    arg = parts[1] if len(parts) == 2 else ""

    if cmd == "wa_head":
        # Just acknowledge; nothing to do yet
        return

    if cmd == "wa_work":
        # Show mode picker for that test
        await q.message.reply_text(f"▶️ Опрацювання помилок для «{arg}». Оберіть режим:", reply_markup=_kb_pick_mode(arg))
        return

    if cmd == "wa_clear":
        deleted = await clear_wrong_for_test(user_id, arg)
        if deleted > 0:
            await q.message.reply_text(f"✅ Очищено {deleted} записів для «{arg}».")
        else:
            await q.message.reply_text(f"ℹ️ Для «{arg}» помилок не знайдено.")
        # refresh main keyboard if present
        pairs = await get_wrong_tests(user_id)
        try:
            await q.message.edit_reply_markup(reply_markup=_kb_tests_with_actions(pairs))
        except Exception:
            pass
        return

    if cmd in ("wa_mode_learn", "wa_mode_test"):
        test_name = arg
        # Must be the same as the currently selected test to run sessions correctly
        current_test = context.user_data.get("current_test")
        if current_test != test_name:
            # If the user has another test loaded, we can't start a session without questions.
            await q.message.reply_text(
                "ℹ️ Спочатку оберіть потрібний тест у списку, щоб завантажити його питання, "
                "а потім знову відкрийте «Мої помилки».")
            return

        indices = await get_wrong_indices(user_id, test_name)
        if not indices:
            await q.message.reply_text("ℹ️ Для цього тесту немає помилок.")
            return

        # Start session with only these indices
        if cmd == "wa_mode_learn":
            order = sorted(indices)
            context.user_data["mode"] = "learning"
            context.user_data["order"] = order
            context.user_data["step"] = 0
            context.user_data["score"] = 0
            context.user_data["wrong_pairs"] = []
            context.user_data["current_streak"] = 0

            # reset live message anchors
            context.user_data.pop("question_chat_id", None)
            context.user_data.pop("question_message_id", None)

            from handlers.learning import send_current_question
            await q.message.reply_text("🎓 Починаємо навчання по помилках!", reply_markup=None)
            await send_current_question(q.message.chat_id, context)
            return

        if cmd == "wa_mode_test":
            import random
            order = list(indices)
            random.shuffle(order)

            context.user_data["mode"] = "test"
            context.user_data["order"] = order
            context.user_data["step"] = 0
            context.user_data["score"] = 0
            context.user_data["wrong_pairs"] = []
            context.user_data["current_streak"] = 0

            from datetime import datetime
            context.user_data["start_time"] = datetime.now()

            from handlers.testing import _show_question
            await q.message.reply_text("📝 Стартуємо тест тільки по помилках!", reply_markup=None)
            await _show_question(q, context, order[0])
            return

    if cmd == "wa_back":
        pairs = await get_wrong_tests(user_id)
        await q.message.reply_text("❌ Тести з помилками. Оберіть дію:", reply_markup=_kb_tests_with_actions(pairs))
        return

    # Unknown — ignore silently
    return


# ===================== Optional hook for saving wrongs live =====================

async def hook_record_from_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, q_index: int, is_ok: bool):
    """
    Can be called from handlers.testing.answer_handler after an answer is chosen,
    to persist wrong answers automatically.
    """
    if is_ok:
        return
    user = update.callback_query.from_user if getattr(update, "callback_query", None) else None
    if not user:
        return
    test_name = context.user_data.get("current_test") or ""
    try:
        await record_wrong_answer(user.id, test_name, q_index)
    except Exception as e:
        logger.debug("[WRONG] hook_record_from_answer failed: %s", e)
