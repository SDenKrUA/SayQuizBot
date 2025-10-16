# handlers/vip_tests/vip_edit_menu.py
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_ui import _images_prompt_kb

# ===== Helpers for single control-message UI =====

def _set_ctrl_from_query(context: ContextTypes.DEFAULT_TYPE, query) -> None:
    """
    Запам'ятати керуюче повідомлення (chat_id, message_id) на базі поточного callback'а.
    """
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


def _images_prompt_kb_for_edit(idx: int) -> InlineKeyboardMarkup:
    """
    Варіант клавіатури для додавання архіву з картинками, коли прийшли з меню редагування.
    «⬅️ Назад» → назад у меню редагування цього тесту.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Додати архів з картинками", callback_data="vip_img_upload")],
        [InlineKeyboardButton("⏭️ Додати архів пізніше", callback_data="vip_img_later")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx}"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])


async def vip_edit_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Відкриває меню редагування обраного VIP-тесту:
    - Перезапис тесту (JSON)
    - Додати архів з картинками (ZIP)
    - Додати окремий файл (image/audio/video/doc) → попросимо номер питання
    - Видалити всі файли медіатеки тесту (image*/audio*/video*/doc*)
    - Довірені користувачі
    - Змінити розділ (перемістити тест цілком)
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
        await _edit_ctrl_text(update, context, "❌ Тест не знайдено.")
        return

    name = items[idx]["name"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Перезапис тесту", callback_data=f"vip_edit_rewrite|{idx}")],
        [InlineKeyboardButton("🖼 Додати архів з картинками (ZIP)", callback_data=f"vip_edit_addimgs|{idx}")],
        [InlineKeyboardButton("📄 Додати окремий файл", callback_data=f"vip_edit_addfile|{idx}")],
        [InlineKeyboardButton("🧹 Видалити всі файли", callback_data=f"vip_media_wipe|{idx}")],
        [InlineKeyboardButton("👥 Довірені користувачі", callback_data=f"vip_trusted|{idx}")],
        [InlineKeyboardButton("📂 Змінити розділ", callback_data=f"vip_edit_move|{idx}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_go|{idx}"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])
    await _edit_ctrl_text(update, context, f"⚙️ Редагування тесту «{name}». Оберіть дію:", reply_markup=kb)


async def vip_edit_rewrite_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Стартує сценарій перезапису (аналог vip_rewrite|idx)."""
    query = update.callback_query
    await query.answer()

    idx_str = (query.data.split("|", 1)[1] if "|" in query.data else "").strip()
    try:
        idx = int(idx_str)
    except ValueError:
        return

    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        await _edit_ctrl_text(update, context, "❌ Тест не знайдено.")
        return

    target = items[idx]
    context.user_data["vip_rewrite_target"] = target
    context.user_data["awaiting_vip_rewrite"] = True

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"vip_edit|{idx}"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])

    await _edit_ctrl_text(
        update, context,
        text=(
            f"✏️ Перезапис тесту «{target['name']}».\n"
            "Надішліть новий файл JSON для цього тесту."
        ),
        reply_markup=kb
    )


async def vip_edit_add_images_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вмикає режим очікування ZIP-архіву з картинками для обраного тесту."""
    query = update.callback_query
    await query.answer()

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
    name = item["name"]
    abs_dir = item["abs_dir"]

    context.user_data["vip_images_dir"] = os.path.join(abs_dir, name)
    context.user_data["awaiting_vip_images"] = True

    await _edit_ctrl_text(
        update, context,
        text=(
            "📦 Надішліть архів картинок у форматі ZIP (*.zip).\n"
            "Імена мають містити номер питання (наприклад, image12.jpg, 12.png)."
        ),
        reply_markup=_images_prompt_kb_for_edit(idx)
    )
