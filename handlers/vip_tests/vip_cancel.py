from telegram import Update
from telegram.ext import ContextTypes

async def vip_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальне скасування станів VIP-потоків."""
    query = update.callback_query
    await query.answer()
    for k in ("vip_pending", "awaiting_vip_json", "vip_browse_path",
              "awaiting_root_folder_name", "awaiting_vip_newname",
              "vip_dup", "vip_replace_move", "vip_rewrite_target",
              "awaiting_vip_rewrite", "vip_delete_idx", "vip_mytests",
              "awaiting_vip_images", "vip_images_dir"):
        context.user_data.pop(k, None)

    # Оновлене повідомлення згідно з вимогами
    await query.message.reply_text(
        "❎ Дію скасовано. Спочатку створіть розділ/підрозділ, а потім знов почніть створювати тест, "
        "щоб покласти його у потрібне місце."
    )
