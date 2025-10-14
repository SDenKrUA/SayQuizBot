import json
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .vip_validation import _validate_test_json
from .vip_utils import _process_media_zip
from .vip_storage import (
    _relative_to_tests, _refresh_catalogs, _load_owners, _save_owners,
    _catalog_entry, _find_json_in_dir, _test_name_exists
)
from .vip_ui import _placement_kb, _dup_owner_kb
from .vip_constants import TESTS_ROOT

logger = logging.getLogger("test_bot")


async def vip_handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Приймає:
      - ZIP архів (коли увімкнено очікування медіа): розпаковує змішані файли (image/audio/video/doc)
        у вже визначену теку media для тесту.
      - JSON тест: валідатор + гілка «перезапис» (якщо очікується) або стандартне додавання з вибором місця.
    """
    doc = update.message.document
    if not doc:
        return

    filename = (doc.file_name or "").strip()

    # ---------- ZIP: медіа архів для ТЕСТУ (коли очікуємо) ----------
    if filename.lower().endswith(".zip"):
        if not context.user_data.get("awaiting_vip_images"):
            # Якщо ми не у режимі очікування архіву — ігноруємо.
            return

        images_dir = context.user_data.get("vip_images_dir")
        if not images_dir:
            await update.message.reply_text("⚠️ Не визначено теку для файлів. Збережіть тест і спробуйте ще раз.")
            return

        try:
            tg_file = await doc.get_file()
            zip_bytes = await tg_file.download_as_bytearray()
        except Exception as e:
            await update.message.reply_text(f"❌ Не вдалося завантажити архів: {e}")
            return

        try:
            stats = _process_media_zip(zip_bytes, images_dir)
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка обробки архіву: {e}")
            return
        finally:
            # Завжди скидаємо прапор очікування архіву
            context.user_data.pop("awaiting_vip_images", None)

        await update.message.reply_text(
            "📦 Обробка архіву завершена.\n"
            f"• Усього файлів у архіві: {stats.get('total', 0)}\n"
            f"• Опрацьовано: {stats.get('processed', 0)}\n"
            f"• Зображень: {stats.get('images', 0)}\n"
            f"• Аудіо: {stats.get('audio', 0)}\n"
            f"• Відео: {stats.get('video', 0)}\n"
            f"• Документів: {stats.get('docs', 0)}\n"
            f"• Пропущено (не медіа): {stats.get('skipped_nonmedia', 0)}\n"
            f"• Помилок: {stats.get('errors', 0)}\n\n"
            f"Папка: `/{_relative_to_tests(images_dir)}`",
            parse_mode="Markdown"
        )
        return

    # ---------- JSON: файл тесту ----------
    if not filename.lower().endswith(".json"):
        # інші типи документів у цьому хендлері не опрацьовуємо
        return

    # зчитуємо JSON
    try:
        tg_file = await doc.get_file()
        file_bytes = await tg_file.download_as_bytearray()
        data = json.loads(file_bytes.decode("utf-8"))
    except Exception as e:
        await update.message.reply_text(f"❌ Не вдалося прочитати JSON: {e}")
        return

    ok, msg = _validate_test_json(data)
    if not ok:
        await update.message.reply_text(f"⚠️ Файл не відповідає структурі: {msg}")
        return

    # --- ГІЛКА 1: перезапис існуючого тесту (користувач відкрив «Перезаписати» й тепер надсилає JSON)
    if context.user_data.get("awaiting_vip_rewrite"):
        target = context.user_data.get("vip_rewrite_target")
        if not target:
            context.user_data.pop("awaiting_vip_rewrite", None)
        else:
            name = target["name"]
            old_path = target["abs_path"]
            old_dir = target["abs_dir"]

            context.user_data["vip_dup"] = {
                "name": name,
                "data": data,
                "old_dir": old_dir,
                "old_path": old_path,
                "rel": target["rel"],
            }
            # скидаємо прапори rewrite
            context.user_data.pop("awaiting_vip_rewrite", None)
            context.user_data.pop("vip_rewrite_target", None)

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Та сама директорія", callback_data="vip_replace_same")],
                [InlineKeyboardButton("🗂 Обрати інший розділ", callback_data="vip_replace_other")],
                [InlineKeyboardButton("❌ Скасувати", callback_data="vip_cancel")],
            ])
            await update.message.reply_text("Де зберегти нову версію тесту?", reply_markup=kb)
            return

    # --- ГІЛКА 2: стандартне VIP-завантаження нового тесту ---
    if not context.user_data.get("awaiting_vip_json"):
        context.user_data["awaiting_vip_json"] = True

    safe_name = filename[:-5]  # без .json
    context.user_data["vip_pending"] = {"name": safe_name, "data": data}

    # Перевірка дубліката по всьому дереву
    if _test_name_exists(context, safe_name):
        entry = _catalog_entry(context, safe_name)
        owner_info = None
        abs_json = None
        if entry:
            test_dir = entry.get("dir")
            abs_json = _find_json_in_dir(test_dir, safe_name) if test_dir else None
            if abs_json:
                owners = _load_owners()
                rel = _relative_to_tests(abs_json)
                owner_info = owners.get(rel)

        # Якщо існуючий тест належить поточному користувачу — покажемо меню «замінити/перемістити»
        if owner_info and owner_info.get("owner_id") == update.effective_user.id:
            context.user_data["vip_dup"] = {
                "name": safe_name,
                "data": data,
                "old_dir": entry.get("dir") if entry else None,
                "old_path": abs_json,
                "rel": _relative_to_tests(abs_json) if abs_json else None,
            }
            await update.message.reply_text(
                f"ℹ️ Тест **{safe_name}** уже існує.\n"
                f"📁 Поточний шлях: `/{_relative_to_tests(abs_json)}`\n\n"
                "Що зробити?",
                reply_markup=_dup_owner_kb()
            )
            return
        else:
            # Попросимо унікальну назву
            context.user_data["awaiting_vip_newname"] = True
            await update.message.reply_text(
                f"⚠️ Тест з назвою **{safe_name}** вже існує.\n"
                "Введіть нову унікальну назву тесту:"
            )
            return

    # Немає дубліката — пропонуємо місце розміщення
    await update.message.reply_text(
        f"Файл прийнято: **{safe_name}.json** ✅\n\nКуди додати тест?",
        reply_markup=_placement_kb()
    )
