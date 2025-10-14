from telegram import Update
from telegram.ext import ContextTypes
from utils.i18n import t
from utils.loader import discover_tests_hierarchy, build_listing_for_path, discover_tests
from utils.keyboards import browse_menu, stats_clear_inline_kb, stats_clear_confirm_kb

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — завжди перечитує дерево tests/ і показує корінь через спільний browse_menu()
    """
    # Скидаємо стан користувача
    context.user_data.clear()
    lang = context.bot_data.get("lang", "uk")

    # 🔄 Примусовий рефреш дерева і каталогу перед показом
    tree = discover_tests_hierarchy("tests")
    context.bot_data["tests_tree"] = tree

    catalog = discover_tests("tests")
    context.bot_data["tests_catalog"] = catalog

    # Корінь
    path = []
    context.user_data["browse_path"] = path
    subfolders, tests, _ = build_listing_for_path(tree, path)

    header = "📂 Обери розділ або тест"
    if not subfolders and not tests:
        header += "\n(цей розділ порожній)"

    await update.message.reply_text(
        t(lang, "welcome") + "\n\n" + header,
        reply_markup=browse_menu(path, subfolders, tests)
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /help"""
    lang = context.bot_data.get("lang", "uk")
    await update.message.reply_text(t(lang, "menu_help", test="Загальна", count=0))

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /rules"""
    lang = context.bot_data.get("lang", "uk")
    rules_text = (
        "📚 Правила використання бота:\n\n"
        "1. Оберіть тест зі списку\n"
        "2. Виберіть режим роботи (навчання/тестування)\n"
        "3. Відповідайте на питання\n"
        "4. Переглядайте статистику\n\n"
        "📖 Режим навчання: можна вивчати питання по порядку або випадково.\n"
        "📝 Режим тестування: імітація реального тестування з обмеженим часом.\n"
        "📊 Статистика: відстежуйте ваш прогрес та помилки."
    )
    await update.message.reply_text(rules_text)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /stats"""
    from handlers.statistics_db import get_user_results
    lang = context.bot_data.get("lang", "uk")
    
    user_id = update.effective_user.id
    results = await get_user_results(user_id, limit=10)
    
    if not results:
        await update.message.reply_text(t(lang, "no_stats_yet"), reply_markup=stats_clear_inline_kb())
        return
    
    stats_text = t(lang, "stats_header", test="Усі тести", correct=0, total=0, acc=0, best=0) + "\n\n"
    
    total_correct = 0
    total_answered = 0
    best_streak = 0
    
    for i, result in enumerate(results, 1):
        total_correct += result['score'] or 0
        total_answered += result['total_questions'] or 0
        best_streak = max(best_streak, result.get('current_streak', 0) or 0)
        
        stats_text += (
            f"{i}. {result['test_name']}: {result['score']}/{result['total_questions']} "
            f"({(result['percent'] or 0):.1f}%)\n"
        )
    
    accuracy = (total_correct / total_answered * 100) if total_answered > 0 else 0
    
    stats_text += f"\n📊 Загалом: {total_correct}/{total_answered} ({accuracy:.1f}%)"
    stats_text += f"\n🔥 Найкраща серія: {best_streak}"
    
    await update.message.reply_text(stats_text, reply_markup=stats_clear_inline_kb())

# ====== Інлайн: очистка всієї статистики ======

async def stats_clear_all_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Почати процес очищення всієї статистики: показати підтвердження"""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "🧹 Ви впевнені, що хочете видалити ВСІ результати по всіх тестах? Дію не можна скасувати.",
        reply_markup=stats_clear_confirm_kb()
    )

async def stats_clear_all_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Підтвердити/скасувати очищення всієї статистики"""
    from handlers.statistics_db import delete_all_results
    query = update.callback_query
    await query.answer()

    choice = (query.data.split("|", 1)[1] if "|" in query.data else "no").strip()
    if choice != "yes":
        await query.message.reply_text("❎ Очищення скасовано.")
        return

    user_id = query.from_user.id
    deleted = await delete_all_results(user_id)
    if deleted > 0:
        await query.message.reply_text(f"✅ Видалено записів: {deleted}. Статистику очищено.")
    else:
        await query.message.reply_text("ℹ️ У вас і так немає збережених результатів.")
