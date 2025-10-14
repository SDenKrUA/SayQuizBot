from telegram import Update
from telegram.ext import ContextTypes

async def vip_img_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Кнопка «Додати архів...» — вмикає режим очікування ZIP (змішаний).
    """
    query = update.callback_query
    await query.answer()
    if not context.user_data.get("vip_images_dir"):
        await query.message.reply_text("⚠️ Немає цільової теки файлів для тесту. Відкрийте тест у редагуванні або збережіть його.")
        return
    context.user_data["awaiting_vip_images"] = True
    await query.message.reply_text(
        "📦 Надішліть ZIP-архів з файлами (зображення/аудіо/відео/документи). "
        "Файли з цифрами в назві отримають відповідні імена `imageN.* / audioN.* / videoN.* / docN.*`."
    )

async def vip_img_later(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Користувач обрав «Додати архів пізніше» — просто прибираємо прапор очікування."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("awaiting_vip_images", None)
    await query.message.reply_text("🕓 Ок, архів можна додати пізніше з меню редагування тесту.")
