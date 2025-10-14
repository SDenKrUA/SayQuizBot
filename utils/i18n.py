from typing import Dict, Any

STRINGS = {
    "uk": {
        "welcome": "🎯 Вітаю в системі підготовки до тестів!\n\nОберіть тест для опрацювання:",
        "choose_test": "Оберіть тест для опрацювання:",
        "test_selected": "✅ Обрано тест: {test}\n📊 Доступно питань: {count}\n\nОберіть режим роботи:",
        "menu_main": "🎯 Обери режим для тесту '{test}':",
        "menu_help": (
            "ℹ️ Довідка для тесту '{test}':\n\n"
            "🎓 Режим навчання — питання по порядку / в роздріб\n"
            "📝 Режим тестування — випадкові питання\n"
            "📊 Статистика — перегляд результатів\n\n"
            "🔢 У режимі навчання можна вказати власний діапазон (3-30)\n"
            "🔢 У режимі тестування — власну кількість питань\n\n"
            "📚 Всього доступно питань: {count}"
        ),
        "learning_pick_range": "📚 Обери діапазон питань для навчання:\n\n📊 Доступно питань: {count}",
        "learning_set_custom": "🔢 Введи власний діапазон у форматі 'start-end' (наприклад, 3-30):\n\n📊 Доступний діапазон: 1-{count}",
        "learning_range_set": "🔢 Діапазон встановлено: {start}-{end}\n\nОбери порядок питань:",
        "learning_order_wrong": "Невірний вибір. Спробуй ще раз.",
        "testing_pick_count": "📝 Обери кількість питань для тесту:\n\n📊 Доступно питань: {count}",
        "testing_count_custom": "🔢 Введи кількість питань для тесту (від 1 до {count}):",
        "testing_start": "📝 Починаємо тест '{test}'!\nПитань: {count}",
        "learning_start": "🎓 Починаємо навчання! Питань: {count}\nПитання йдуть {order}.",
        "stats_header": "📊 Твоя статистика для '{test}':\n\n✅ Правильних відповідей: {correct}\n📝 Всього відповідей: {total}\n🎯 Точність: {acc}%\n🔥 Найкраща серія: {best}",
        "results_header": "🏁 {mode} '{test}' завершено!\n\n✅ Правильних: {score}/{total} ({percent}%)\n⏱ Час: {mins} хв {secs} сек\n",
        "no_wrong_to_retry": "Немає помилок для повторення.",
        "retry_start": "🔁 Повторюємо {count} помилок...",
        "detailed_stats_title": "📊 Детальна статистика помилок для '{test}':\n\n",
        "back_to_menu": "🎯 Обери режим для тесту '{test}':",
        "range_invalid": "❌ Невірний формат діапазону. Спробуй ще раз.",
        "range_bounds": "❌ Діапазон повинен бути в межах 1-{count}. Спробуй ще раз:",
        "count_invalid": "❌ Невірний формат. Введи число (від 1 до {count}):",
        "test_not_found": "❌ Обраний тест не знайдено. Спробуйте ще раз:",
        "test_load_error": "❌ Помилка завантаження питань для обраного тесту. Спробуйте пізніше.",
        "download_not_found": "❌ Файл для тесту '{test}' не знайдено в теці extracts/.",
        "download_success": "📥 Завантажено файл для тесту '{test}'.",
        "download_error": "❌ Помилка при завантаженні файлу для тесту '{test}': {error}",
        "no_stats_yet": "📊 У вас ще немає статистики. Пройдіть хоча б один тест!",

        # ⭐ Улюблені — рядки для очищення всіх
        "favorites_clear_prompt": "🧹 Видалити ВСІ позначки \"Улюблене\" для всіх тестів? Це не можна скасувати.",
        "favorites_cleared": "✅ Готово! Видалено {n} позначок улюблених.",
        "favorites_clear_cancel": "❎ Скасовано. Нічого не змінював.",
        "favorites_empty": "ℹ️ У тебе ще немає улюблених питань.",
        "favorites_list_title": "⭐ Твої улюблені питання:\n",
    },
    "en": {
        "welcome": "🎯 Welcome!\n\nChoose a test to start:",
        "choose_test": "Choose a test:",
        "test_selected": "✅ Selected test: {test}\n📊 Questions available: {count}\n\nChoose a mode:",
        "menu_main": "🎯 Choose a mode for '{test}':",
        "menu_help": (
            "ℹ️ Help for '{test}':\n\n"
            "🎓 Learning — questions in order / shuffled\n"
            "📝 Testing — random questions\n"
            "📊 Stats — view your results\n\n"
            "🔢 In Learning you can set a custom range (3-30)\n"
            "🔢 In Testing you can set a custom count\n\n"
            "📚 Total questions: {count}"
        ),
        "learning_pick_range": "📚 Pick range for learning:\n\n📊 Available: {count}",
        "learning_set_custom": "🔢 Enter custom range 'start-end' (e.g., 3-30):\n\n📊 Valid range: 1-{count}",
        "learning_range_set": "🔢 Range set: {start}-{end}\n\nChoose order:",
        "learning_order_wrong": "Invalid choice. Try again.",
        "testing_pick_count": "📝 Choose number of questions:\n\n📊 Available: {count}",
        "testing_count_custom": "🔢 Enter number of questions (1 to {count}):",
        "testing_start": "📝 Starting test '{test}'!\nQuestions: {count}",
        "learning_start": "🎓 Starting learning! Questions: {count}\nOrder: {order}.",
        "stats_header": "📊 Your stats for '{test}':\n\n✅ Correct: {correct}\n📝 Total: {total}\n🎯 Accuracy: {acc}%\n🔥 Best streak: {best}",
        "results_header": "🏁 {mode} '{test}' finished!\n\n✅ Correct: {score}/{total} ({percent}%)\n⏱ Time: {mins} min {secs} sec\n",
        "no_wrong_to_retry": "No mistakes to retry.",
        "retry_start": "🔁 Retrying {count} mistakes...",
        "detailed_stats_title": "📊 Detailed mistakes for '{test}':\n\n",
        "back_to_menu": "🎯 Choose a mode for '{test}':",
        "range_invalid": "❌ Invalid range format. Try again.",
        "range_bounds": "❌ Range must be within 1-{count}. Try again:",
        "count_invalid": "❌ Invalid number. Enter (1 to {count}):",
        "test_not_found": "❌ Selected test not found. Try again:",
        "test_load_error": "❌ Failed to load questions. Try later.",
        "download_not_found": "❌ File for test '{test}' not found in extracts/ folder.",
        "download_success": "📥 Downloaded file for test '{test}'.",
        "download_error": "❌ Error downloading file for test '{test}': {error}",
        "no_stats_yet": "📊 You don't have any statistics yet. Complete at least one test!",

        # ⭐ Favorites — strings for clearing all
        "favorites_clear_prompt": "🧹 Remove ALL favorites across all tests? This cannot be undone.",
        "favorites_cleared": "✅ Done! Removed {n} favorite marks.",
        "favorites_clear_cancel": "❎ Cancelled. No changes made.",
        "favorites_empty": "ℹ️ You don't have any favorite questions yet.",
        "favorites_list_title": "⭐ Your favorite questions:\n",
    }
}

def t(lang: str, key: str, **kwargs) -> str:
    """
    Функція локалізації
    
    Args:
        lang: Мова ('uk', 'en')
        key: Ключ рядка
        **kwargs: Параметри для форматування
        
    Returns:
        Локалізований рядок
    """
    # Вибираємо таблицю перекладів
    table = STRINGS.get(lang, STRINGS["uk"])
    
    # Отримуємо рядок
    template = table.get(key, key)
    
    # Якщо немає параметрів для форматування
    if not kwargs:
        return template
    
    try:
        # Форматуємо рядок
        return template.format(**kwargs)
    except (KeyError, ValueError) as e:
        # Обробка помилок форматування
        print(f"Format error for key '{key}': {e}")
        return template
