from telegram import Update
from telegram.ext import ContextTypes

from .vip_utils import _sanitize_test_name
from .vip_storage import _test_name_exists
from .vip_ui import _placement_kb

async def vip_handle_newname_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ВАЖЛИВО: цей хендлер у group=0
    if not context.user_data.get("awaiting_vip_newname"):
        return

    raw = (update.message.text or "").strip()
    new_name = _sanitize_test_name(raw)
    if not new_name:
        await update.message.reply_text("❌ Некоректна назва. Заборонені символи: <>:\"/\\|?* . Спробуйте ще.")
        return
    if _test_name_exists(context, new_name):
        await update.message.reply_text("⚠️ Така назва вже зайнята. Введіть іншу:")
        return

    pending = context.user_data.get("vip_pending") or {}
    pending["name"] = new_name
    context.user_data["vip_pending"] = pending
    context.user_data.pop("awaiting_vip_newname", None)

    await update.message.reply_text(
        f"✅ Назву змінено на **{new_name}**.\nКуди додати тест?",
        reply_markup=_placement_kb()
    )
