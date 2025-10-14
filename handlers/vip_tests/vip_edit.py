# handlers/vip_tests/vip_edit_menu.py
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_ui import _images_prompt_kb

async def vip_edit_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Відкриває меню редагування обраного VIP-тесту:
    - Перезапис тесту
    - Додати архів з картинками
    - Додати окремий файл (image/audio/video/doc) за номером питання
    - Видалити всі файли (тека медіа)
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
        await query.message.reply_text("❌ Тест не знайдено.")
        return

    name = items[idx]["name"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Перезапис тесту", callback_data=f"vip_edit_rewrite|{idx}")],
        [InlineKeyboardButton("📦 Додати архів з картинками/файлами", callback_data=f"vip_edit_addimgs|{idx}")],
        [InlineKeyboardButton("📄 Додати окремий файл", callback_data=f"vip_edit_addfile|{idx}")],
        [InlineKeyboardButton("🧹 Видалити всі файли", callback_data=f"vip_media_wipe|{idx}")],
        [InlineKeyboardButton("👥 Довірені користувачі", callback_data=f"vip_trusted|{idx}")],
        [InlineKeyboardButton("📂 Змінити розділ", callback_data=f"vip_edit_move|{idx}")],
        [InlineKeyboardButton("❌ Закрити", callback_data="vip_cancel")],
    ])
    await query.message.reply_text(f"⚙️ Редагування тесту «{name}». Оберіть дію:", reply_markup=kb)

async def vip_edit_rewrite_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    target = items[idx]
    context.user_data["vip_rewrite_target"] = target
    context.user_data["awaiting_vip_rewrite"] = True
    await query.message.reply_text(
        f"✏️ Перезапис тесту **{target['name']}**.\n"
        "Надішліть новий файл JSON для цього тесту."
    )

async def vip_edit_add_images_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Вмикає режим очікування ZIP-архіву з медіа для обраного тесту.
    Тепер архів може містити змішаний контент (image/audio/video/doc).
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
    name = item["name"]
    abs_dir = item["abs_dir"]

    context.user_data["vip_images_dir"] = os.path.join(abs_dir, name)
    context.user_data["awaiting_vip_images"] = True

    await query.message.reply_text(
        "📦 Надішліть ZIP-архів з файлами (зображення/аудіо/відео/документи).\n"
        "Файл іменуватиметься як image{N}.*, audio{N}.*, video{N}.*, doc{N}.* (N — номер з назви або авто).\n"
        "Зображення буде стиснено для швидкої відправки.",
        reply_markup=_images_prompt_kb()
    )
