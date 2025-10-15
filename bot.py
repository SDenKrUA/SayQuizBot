import os
import re
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram import BotCommand
from telegram.request import HTTPXRequest

load_dotenv()

from utils.logger import setup_logger
from utils.loader import discover_tests

# --- Старт/довідка/статистика ---
from handlers.start import cmd_start, cmd_help, cmd_rules, cmd_stats, stats_clear_all_start, stats_clear_all_confirm

# --- Меню, пошук, відкриття питання з пошуку ---
from handlers.menu import (
    handle_home_menu,
    handle_main_menu,
    handle_download_test,
    handle_search_query,
    open_question_from_search,
    stop_search_cb,
)

# --- Learning/Test режими ---
from handlers.learning import (
    handle_learning_range,
    handle_custom_range,
    handle_learning_order,
)
from handlers.testing import (
    handle_test_settings,
    handle_custom_test_count,
    answer_handler,
    next_handler,
    retry_wrong_handler,
    detailed_stats_handler,
    back_to_menu_handler,
    cancel_session_handler,
    back_text_handler,
)

# --- Статистика в БД ---
from handlers.statistics_db import initialize_database, close_db_connection

# --- Вибір тесту та дерево ---
from handlers.test_selection import handle_test_selection, add_cancel_cb

# --- Майстер додавання питання ---
from handlers.add_question import (
    handle_add_question,
    handle_add_question_step,
    skip_image_button_handler,
    addq_req_continue_cb,
    addq_req_send_cb,
    addq_req_cancel_cb,
    addq_cancel_cb,
)

# --- Коментарі ---
from handlers.comments import (
    handle_comment_flow,
    comment_entry_handler,
    comment_write_handler,
    comment_view_handler,
    comment_back_handler,
)

# --- Улюблені ---
from handlers.favorites import (
    favorite_handler,
    show_favorites,
    show_favorites_for_current_test,
    start_favorites_learning,
    start_favorites_test,
    clear_all_favorites_start,
    clear_all_favorites_confirm,
)

# --- Мій кабінет ---
from handlers.office import (
    office_open,
    office_buttons_handler,
    office_my_questions,
)

# --- ❌ Мої помилки (нове) ---
from handlers.wrong_answers import (
    wrong_answers_cmd,
    wa_buttons_handler,
)

# --- VIP пакет ---
import handlers.vip_tests as vip

# --- Адмін-панель власника бота ---
from handlers.owner_panel import (
    owner_entry,          # /owner або кнопка з кабінету
    owner_router_cb,      # CallbackQueryHandler для всіх own|...
    owner_text_entry,     # введення нової назви теки (тільки reply)
)

logger = setup_logger()

# --- Регекси для меню/ввідних форматів ---
MAIN_MENU_REGEX = re.compile(r"^(🎓 Режим навчання|📝 Режим тестування|⭐ Улюблені|🔎 Пошук)$")
CUSTOM_RANGE_REGEX = re.compile(r"^\d+-\d+$")
NUMBER_REGEX = re.compile(r"^\d+$")
USERNAME_REGEX = re.compile(r"^@[A-Za-z0-9_]{3,32}$")


async def set_commands(application):
    commands = [
        BotCommand("start", "Почати"),
        BotCommand("help", "Допомога"),
        BotCommand("rules", "Правила"),
        BotCommand("stats", "Моя статистика"),
        BotCommand("favorites", "Улюблені"),
        BotCommand("office", "Мій кабінет"),
        BotCommand("wrong_answers", "Мої помилки"),
        BotCommand("owner", "Адмін-панель (власник)"),
    ]
    await application.bot.set_my_commands(commands)


async def error_handler(update, context):
    logger.error("Exception while handling an update:", exc_info=context.error)


async def post_init(application):
    await set_commands(application)
    await initialize_database()
    catalog = discover_tests("tests")
    application.bot_data["tests_catalog"] = catalog
    logger.info(f"✅ Бот ініціалізовано. Завантажено {len(catalog)} тестів")


async def post_shutdown(application):
    await close_db_connection()
    logger.info("✅ Бот зупинено, з'єднання закрито")


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.critical("BOT_TOKEN not set. Put BOT_TOKEN in .env")
        return

    lang = os.getenv("LANG", "uk")
    request = HTTPXRequest(
        connect_timeout=30.0, read_timeout=60.0, write_timeout=30.0, pool_timeout=30.0
    )
    app = Application.builder().token(token).request(request).build()
    app.post_init = post_init
    app.post_shutdown = post_shutdown
    app.add_error_handler(error_handler)
    app.bot_data["lang"] = lang

    g = lambda name: getattr(vip, name, None)

    # =======================
    # === COMMANDS ===
    # =======================
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("favorites", show_favorites))
    app.add_handler(CommandHandler("office", office_open))
    app.add_handler(CommandHandler("wrong_answers", wrong_answers_cmd))
    app.add_handler(CommandHandler("owner", owner_entry))

    # =======================
    # Group 0: ВУЗЬКІ/ПРІОРИТЕТНІ
    # =======================
    # ⚠️ ВАЖЛИВО: VIP single-file спершу (щоб не перехоплював майстер додавання питання)
    if g("vip_edit_add_single_file_start"):
        app.add_handler(CallbackQueryHandler(g("vip_edit_add_single_file_start"), pattern=r"^vip_edit_addfile\|\d+$"), group=0)
    if g("vip_handle_single_index_text"):
        app.add_handler(
            MessageHandler(
                (filters.TEXT & ~filters.COMMAND) & ~filters.Regex(r"^➕ Додати питання$"),
                g("vip_handle_single_index_text")
            ),
            group=0
        )
    if g("vip_handle_single_media_file"):
        app.add_handler(
            MessageHandler(
                filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO,
                g("vip_handle_single_media_file")
            ),
            group=0
        )

    # Далі — майстер додавання питання
    app.add_handler(MessageHandler(filters.Regex(r"^➕ Додати питання$"), handle_add_question), group=0)
    app.add_handler(
        MessageHandler(
            (filters.TEXT & ~filters.COMMAND & ~filters.Regex(USERNAME_REGEX)),
            handle_add_question_step
        ),
        group=0
    )
    app.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO, handle_add_question_step),
        group=0
    )
    app.add_handler(CallbackQueryHandler(skip_image_button_handler, pattern=r"^addq_skip$"), group=0)
    app.add_handler(CallbackQueryHandler(addq_req_continue_cb, pattern=r"^addq_req_continue$"), group=0)
    app.add_handler(CallbackQueryHandler(addq_req_send_cb, pattern=r"^addq_req_send$"), group=0)
    app.add_handler(CallbackQueryHandler(addq_req_cancel_cb, pattern=r"^addq_req_cancel$"), group=0)
    app.add_handler(CallbackQueryHandler(addq_cancel_cb, pattern=r"^addq_cancel$"), group=0)

    # Інші VIP і службові (залишаємо, як були)
    if g("vip_trusted_handle_username_text"):
        app.add_handler(MessageHandler(filters.Regex(USERNAME_REGEX), g("vip_trusted_handle_username_text")), group=0)
    if g("vip_wipe_media_start"):
        app.add_handler(CallbackQueryHandler(g("vip_wipe_media_start"), pattern=r"^vip_media_wipe\|\d+$"), group=0)
    if g("vip_wipe_media_confirm"):
        app.add_handler(CallbackQueryHandler(g("vip_wipe_media_confirm"), pattern=r"^vip_media_wipe_confirm\|(yes|no)$"), group=0)
    app.add_handler(CallbackQueryHandler(stats_clear_all_start, pattern=r"^stats_clear_all$"), group=0)
    app.add_handler(CallbackQueryHandler(stats_clear_all_confirm, pattern=r"^stats_clear_confirm\|(yes|no)$"), group=0)

    # =======================
    # Group 1: ОФІС, VIP, МЕНЮ, СПЕЦ. ТЕКСТОВІ
    # =======================
    app.add_handler(MessageHandler(filters.Regex(r"^(🔎 Пошук)$"), handle_home_menu), group=1)
    app.add_handler(CallbackQueryHandler(stop_search_cb, pattern=r"^stop_search$"), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^👤 Мій кабінет$"), office_open), group=1)

    # кнопка Адмін-панель з «Мій кабінет»
    app.add_handler(MessageHandler(filters.Regex(r"^👑 Адмін-панель$"), owner_entry), group=1)

    app.add_handler(CallbackQueryHandler(add_cancel_cb, pattern=r"^add_cancel\|(folder|test)$"), group=1)
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^(Моя статистика|Мої улюблені|Мої тести|Спільні тести|Мої питання|⬅️ Назад)$"),
            office_buttons_handler
        ),
        group=1
    )
    app.add_handler(MessageHandler(filters.Regex(r"^Мої питання$"), office_my_questions), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^Мої помилки$"), wrong_answers_cmd), group=1)

    # ⛔ ВАЖЛИВО: перейменування тек — тільки reply-відповідь (не блокує інші тексти)
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, owner_text_entry), group=1)

    if g("vip_img_upload"):
        app.add_handler(CallbackQueryHandler(g("vip_img_upload"), pattern=r"^vip_img_upload$"), group=1)
    if g("vip_send_template"):
        app.add_handler(CallbackQueryHandler(g("vip_send_template"), pattern=r"^vip_template$"), group=1)
    if g("vip_start_upload"):
        app.add_handler(CallbackQueryHandler(g("vip_start_upload"), pattern=r"^vip_upload_full$"), group=1)
    if g("vip_handle_document"):
        app.add_handler(MessageHandler(filters.Document.ALL, g("vip_handle_document")), group=1)

    if g("vip_dup_view"):
        app.add_handler(CallbackQueryHandler(g("vip_dup_view"), pattern=r"^vip_dup_view$"), group=1)
    if g("vip_dup_replace"):
        app.add_handler(CallbackQueryHandler(g("vip_dup_replace"), pattern=r"^vip_dup_replace$"), group=1)
    if g("vip_replace_same"):
        app.add_handler(CallbackQueryHandler(g("vip_replace_same"), pattern=r"^vip_replace_same$"), group=1)
    if g("vip_replace_other"):
        app.add_handler(CallbackQueryHandler(g("vip_replace_other"), pattern=r"^vip_replace_other$"), group=1)
    if g("vip_rewrite_select"):
        app.add_handler(CallbackQueryHandler(g("vip_rewrite_select"), pattern=r"^vip_rewrite\|\d+$"), group=1)
    if g("vip_delete_select"):
        app.add_handler(CallbackQueryHandler(g("vip_delete_select"), pattern=r"^vip_delete\|\d+$"), group=1)
    if g("vip_delete_confirm"):
        app.add_handler(CallbackQueryHandler(g("vip_delete_confirm"), pattern=r"^vip_delete_confirm\|(yes|no)$"), group=1)

    if g("vip_choose_folder"):
        app.add_handler(CallbackQueryHandler(g("vip_choose_folder"), pattern=r"^vip_choose_folder$"), group=1)
    if g("vip_nav_open"):
        app.add_handler(CallbackQueryHandler(g("vip_nav_open"), pattern=r"^vip_open\|"), group=1)
    if g("vip_nav_up"):
        app.add_handler(CallbackQueryHandler(g("vip_nav_up"), pattern=r"^vip_up$"), group=1)
    if g("vip_choose_here"):
        app.add_handler(CallbackQueryHandler(g("vip_choose_here"), pattern=r"^vip_choose_here$"), group=1)
    if g("vip_create_root"):
        app.add_handler(CallbackQueryHandler(g("vip_create_root"), pattern=r"^vip_create_root$"), group=1)
    if g("vip_cancel"):
        app.add_handler(CallbackQueryHandler(g("vip_cancel"), pattern=r"^vip_cancel$"), group=1)
    if g("vip_img_later"):
        app.add_handler(CallbackQueryHandler(g("vip_img_later"), pattern=r"^vip_img_later$"), group=1)

    if g("vip_edit_open"):
        app.add_handler(CallbackQueryHandler(g("vip_edit_open"), pattern=r"^vip_edit\|\d+$"), group=1)
    if g("vip_edit_rewrite_from_menu"):
        app.add_handler(CallbackQueryHandler(g("vip_edit_rewrite_from_menu"), pattern=r"^vip_edit_rewrite\|\d+$"), group=1)
    if g("vip_edit_add_images_from_menu"):
        app.add_handler(CallbackQueryHandler(g("vip_edit_add_images_from_menu"), pattern=r"^vip_edit_addimgs\|\d+$"), group=1)

    # 🔹 Перейти до тесту
    if g("vip_go_to_test"):
        app.add_handler(CallbackQueryHandler(g("vip_go_to_test"), pattern=r"^vip_go\|\d+$"), group=1)

    # 🔹 ЗМІНИТИ РОЗДІЛ (move flow)
    if g("vip_edit_move_open"):
        app.add_handler(CallbackQueryHandler(g("vip_edit_move_open"), pattern=r"^vip_edit_move\|\d+$"), group=1)
    if g("vip_move_open"):
        app.add_handler(CallbackQueryHandler(g("vip_move_open"), pattern=r"^vip_move_open\|"), group=1)
    if g("vip_move_up"):
        app.add_handler(CallbackQueryHandler(g("vip_move_up"), pattern=r"^vip_move_up$"), group=1)
    if g("vip_move_choose_here"):
        app.add_handler(CallbackQueryHandler(g("vip_move_choose_here"), pattern=r"^vip_move_choose_here$"), group=1)
    if g("vip_move_pick"):
        app.add_handler(CallbackQueryHandler(g("vip_move_pick"), pattern=r"^vip_move_pick\|"), group=1)

    if g("vip_trusted_open"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_open"), pattern=r"^vip_trusted\|\d+$"), group=1)
    if g("vip_trusted_add_start"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_add_start"), pattern=r"^vip_trusted_add\|\d+$"), group=1)
    if g("vip_trusted_remove_open"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_remove_open"), pattern=r"^vip_trusted_remove\|\d+$"), group=1)
    if g("vip_trusted_remove_do"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_remove_do"), pattern=r"^vip_trusted_remove_do\|\d+\|.+$"), group=1)
    if g("vip_trusted_pick_target"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_pick_target"), pattern=r"^vip_trusted_pick\|\d+\|.+$"), group=1)

    if g("vip_trusted_requests_open"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_requests_open"), pattern=r"^vip_trusted_requests\|\d+$"), group=1)
    if g("vip_trusted_requests_accept_one"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_requests_accept_one"), pattern=r"^vip_tr_req_accept\|\d+\|\d+$"), group=1)
    if g("vip_trusted_requests_decline_one"):
        app.add_handler(CallbackQueryHandler(g("vip_trusted_requests_decline_one"), pattern=r"^vip_tr_req_decline\|\d+\|\d+$"), group=1)
    if g("vip_trusted_requests_accept_all"):
        app.add_handler(CallbackQueryHandler(g("vip_tr_req_accept_all\|\d+$"), pattern=r"^vip_tr_req_accept_all\|\d+$"), group=1)
    if g("vip_trusted_requests_decline_all"):
        app.add_handler(CallbackQueryHandler(g("vip_tr_req_decline_all\|\d+$"), pattern=r"^vip_tr_req_decline_all\|\d+$"), group=1)

    app.add_handler(MessageHandler(filters.Regex(r"^(📥 Завантажити весь тест)$"), handle_download_test), group=1)
    app.add_handler(MessageHandler(filters.Regex(MAIN_MENU_REGEX), handle_main_menu), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^🎓 Навчання з улюблених$"), start_favorites_learning), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^📝 Тест з улюблених$"), start_favorites_test), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^(🔙 Назад|⬅️ Назад)$"), back_text_handler), group=1)

    # 3) Learning
    app.add_handler(MessageHandler(filters.Regex(r"^(\d+-\d+)$"), handle_learning_range), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^🔢 Власний діапазон$"), handle_learning_range), group=1)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(CUSTOM_RANGE_REGEX), handle_custom_range), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^(🔢 По порядку|🎲 В роздріб|🔙 Назад|⬅️ Назад)$"), handle_learning_order), group=1)

    # 4) Testing
    app.add_handler(MessageHandler(filters.Regex(r"^(🔟 10 питань|5️⃣0️⃣ 50 питань|💯 100 питань|🔢 Власна кількість|🔙 Назад)$"), handle_test_settings), group=1)
    app.add_handler(
        MessageHandler(
            (filters.TEXT & filters.Regex(NUMBER_REGEX)),
            handle_custom_test_count
        ),
        group=1
    )

    # 5) /start через кнопку
    app.add_handler(MessageHandler(filters.Regex(r"^🔙 Обрати інший тест$"), cmd_start), group=2)

    # 6) Динамічний вибір тесту (останній) — ВАЖЛИВО: block=False
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_test_selection, block=False), group=2)

    # --- Callback handlers (квіз) ---
    app.add_handler(CallbackQueryHandler(answer_handler, pattern=r"^ans\|\d+\|\d+$"))
    app.add_handler(CallbackQueryHandler(next_handler, pattern=r"^next$"))
    app.add_handler(CallbackQueryHandler(retry_wrong_handler, pattern=r"^retry_wrong$"))
    app.add_handler(CallbackQueryHandler(detailed_stats_handler, pattern=r"^detailed_stats$"))
    app.add_handler(CallbackQueryHandler(back_to_menu_handler, pattern=r"^back_to_menu$"))

    # ⭐ Улюблені
    app.add_handler(CallbackQueryHandler(clear_all_favorites_start, pattern=r"^fav_clear_all$"))
    app.add_handler(CallbackQueryHandler(clear_all_favorites_confirm, pattern=r"^fav_clear_confirm\|(yes|no)$"))
    app.add_handler(CallbackQueryHandler(favorite_handler, pattern=r"^fav\|\d+$"))

    # ❌ Мої помилки — всі inline-кнопки
    app.add_handler(CallbackQueryHandler(wa_buttons_handler, pattern=r"^wa_"))

    # Коментарі (inline)
    app.add_handler(CallbackQueryHandler(comment_entry_handler, pattern=r"^comment\|\d+$"))
    app.add_handler(CallbackQueryHandler(comment_write_handler, pattern=r"^comment_write\|\d+$"))
    app.add_handler(CallbackQueryHandler(comment_view_handler, pattern=r"^comment_view\|\d+$"))
    app.add_handler(CallbackQueryHandler(comment_back_handler, pattern=r"^comment_back\|\d+$"))

    # ⛔ Скасування навчання/тестування
    app.add_handler(CallbackQueryHandler(cancel_session_handler, pattern=r"^cancel$"))

    # ⛔ Усі колбеки адмін-панелі
    app.add_handler(CallbackQueryHandler(owner_router_cb, pattern=r"^own\|"))

    logger.info("✅ Бот запущений!")
    logger.info("⏹ Натисни CTRL+C щоб зупинити.")

    app.run_polling(poll_interval=0.1, drop_pending_updates=True)


if __name__ == "__main__":
    main()
