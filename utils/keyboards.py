from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional

# Кеш для статичних клавіатур
_main_menu_kb = None
_learning_order_kb = None
_test_settings_kb = None
_back_button_kb = None

def tests_menu(test_names: List[str]) -> ReplyKeyboardMarkup:
    """Клавіатура вибору тесту (плоска) — залишається для сумісності"""
    keyboard = [[KeyboardButton(name)] for name in test_names]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def browse_menu(path: List[str], subfolders: List[str], tests: List[str]) -> ReplyKeyboardMarkup:
    """Клавіатура навігації по розділах/папках і тестах, з кнопками додавання."""
    rows: List[List[KeyboardButton]] = []
    # Папки
    for name in subfolders:
        rows.append([KeyboardButton(f"📁 {name}")])
    # Тести
    for name in tests:
        rows.append([KeyboardButton(name)])
    # Додавання
    rows.append([KeyboardButton("➕ Додати розділ"), KeyboardButton("➕ Додати тест")])
    # Контрольні кнопки
    ctrl: List[KeyboardButton] = []
    if path:
        ctrl.append(KeyboardButton("🔙 Назад"))
    ctrl.append(KeyboardButton("🔎 Пошук"))
    ctrl.append(KeyboardButton("👤 Мій кабінет"))
    rows.append(ctrl)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def main_menu() -> ReplyKeyboardMarkup:
    """Головне меню (з кешуванням)"""
    global _main_menu_kb
    if _main_menu_kb is None:
        _main_menu_kb = ReplyKeyboardMarkup([
            [KeyboardButton("🎓 Режим навчання"), KeyboardButton("📝 Режим тестування")],
            [KeyboardButton("⭐ Улюблені"), KeyboardButton("🔎 Пошук")],
            [KeyboardButton("📥 Завантажити весь тест"), KeyboardButton("🔙 Обрати інший тест")],
            [KeyboardButton("➕ Додати питання")]
        ], resize_keyboard=True)
    return _main_menu_kb

def learning_range_keyboard(total_questions: int) -> ReplyKeyboardMarkup:
    """Клавіатура вибору діапазону для навчання"""
    if total_questions <= 0:
        return get_back_button()
    
    ranges = []
    start = 1
    
    range_buttons = []
    while start <= total_questions:
        end = min(start + 49, total_questions)
        range_buttons.append(f"{start}-{end}")
        start = end + 1
    
    for i in range(0, len(range_buttons), 2):
        row = []
        if i < len(range_buttons):
            row.append(range_buttons[i])
        if i + 1 < len(range_buttons):
            row.append(range_buttons[i + 1])
        if row:
            ranges.append(row)
    
    if len(range_buttons) % 2 != 0:
        ranges.append(["🔢 Власний діапазон"])
        ranges.append(["🔙 Назад"])
    else:
        ranges.append(["🔢 Власний діапазон", "🔙 Назад"])
    
    return ReplyKeyboardMarkup(ranges, resize_keyboard=True)

def learning_order_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура вибору порядку навчання (з кешуванням)"""
    global _learning_order_kb
    if _learning_order_kb is None:
        _learning_order_kb = ReplyKeyboardMarkup([
            [KeyboardButton("🔢 По порядку"), KeyboardButton("🎲 В роздріб")],
            [KeyboardButton("🔙 Назад")]
        ], resize_keyboard=True)
    return _learning_order_kb

def test_settings_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура налаштувань тесту (з кешуванням)"""
    global _test_settings_kb
    if _test_settings_kb is None:
        _test_settings_kb = ReplyKeyboardMarkup([
            [KeyboardButton("🔟 10 питань"), KeyboardButton("5️⃣0️⃣ 50 питань")],
            [KeyboardButton("💯 100 питань"), KeyboardButton("🔢 Власна кількість")],
            [KeyboardButton("🔙 Назад")]
        ], resize_keyboard=True)
    return _test_settings_kb

def build_options_markup(
    q_index: int,
    highlight: Optional[bool] = None,
    two_columns: bool = False,
    is_favorited: bool = False,
    comments_count: int = 0,
    include_cancel: bool = True
) -> InlineKeyboardMarkup:
    """
    Побудова inline клавіатури з варіантами відповідей + «⛔ Скасувати».
    """
    letters = ["A", "B", "C", "D"]

    # Після відповіді: "Далі", "Улюблене", "Коментарі (N)"
    if highlight:
        star_text = f"{'✅ ' if is_favorited else ''}⭐ Улюблене"
        comment_text = f"Коментарі ({comments_count})"
        kb = [[
            InlineKeyboardButton("➡️ Далі", callback_data="next"),
            InlineKeyboardButton(star_text, callback_data=f"fav|{q_index}"),
            InlineKeyboardButton(comment_text, callback_data=f"comment|{q_index}")
        ]]
        if include_cancel:
            kb.append([InlineKeyboardButton("⛔ Скасувати", callback_data="cancel")])
        return InlineKeyboardMarkup(kb)
    
    # До відповіді — лише A/B/C/D (+ окремо «⛔ Скасувати» нижнім рядом)
    kb = []
    if two_columns:
        for i in range(0, len(letters), 2):
            row = []
            for j in range(2):
                if i + j < len(letters):
                    callback_data = f"ans|{q_index}|{i + j}"
                    row.append(InlineKeyboardButton(letters[i + j], callback_data=callback_data))
            if row:
                kb.append(row)
    else:
        for i, letter in enumerate(letters):
            callback_data = f"ans|{q_index}|{i}"
            kb.append([InlineKeyboardButton(letter, callback_data=callback_data)])

    if include_cancel:
        kb.append([InlineKeyboardButton("⛔ Скасувати", callback_data="cancel")])

    return InlineKeyboardMarkup(kb)

def get_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Генерація прогресс-бару"""
    if total <= 0:
        return "0/0"
    
    filled = min(int(length * current / total), length)
    empty = length - filled
    return f"{'🟩' * filled}{'⬜' * empty} {current}/{total}"

def get_back_button() -> ReplyKeyboardMarkup:
    """Проста клавіатура з кнопкою 'Назад'"""
    global _back_button_kb
    if _back_button_kb is None:
        _back_button_kb = ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
    return _back_button_kb

def get_retry_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура для результатів тесту"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Повторити помилки", callback_data="retry_wrong")],
        [InlineKeyboardButton("📊 Детальна статистика", callback_data="detailed_stats")],
        [InlineKeyboardButton("🏠 До меню", callback_data="back_to_menu")]
    ])

def comment_menu(q_index: int) -> InlineKeyboardMarkup:
    """Inline меню для коментарів (окреме повідомлення)"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Написати коментар", callback_data=f"comment_write|{q_index}")],
        [InlineKeyboardButton("📖 Переглянути коментарі", callback_data=f"comment_view|{q_index}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"comment_back|{q_index}")]
    ])

# === Нове: інлайн-кнопки для очищення улюблених ===
def favorites_clear_inline_kb() -> InlineKeyboardMarkup:
    """Одна кнопка — почати очищення всіх улюблених"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Очистити всі Улюблені", callback_data="fav_clear_all")]
    ])

def favorites_clear_confirm_kb() -> InlineKeyboardMarkup:
    """Підтвердження очищення"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Так, очистити", callback_data="fav_clear_confirm|yes"),
            InlineKeyboardButton("❎ Скасувати", callback_data="fav_clear_confirm|no"),
        ]
    ])

# === Нове: інлайн-кнопки для очищення статистики ===
def stats_clear_inline_kb() -> InlineKeyboardMarkup:
    """Одна кнопка — почати очищення всієї статистики"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Очистити всю статистику", callback_data="stats_clear_all")]
    ])

def stats_clear_confirm_kb() -> InlineKeyboardMarkup:
    """Підтвердження очищення статистики"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Так, очистити", callback_data="stats_clear_confirm|yes"),
            InlineKeyboardButton("❎ Скасувати", callback_data="stats_clear_confirm|no"),
        ]
    ])

# === Нове: інлайн «❎ Скасувати» для додавання розділу/тесту ===
def add_cancel_kb(kind: str) -> InlineKeyboardMarkup:
    """
    Кнопка для скасування режимів додавання.
    kind: "folder" або "test"
    """
    safe_kind = "folder" if kind == "folder" else "test"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❎ Скасувати", callback_data=f"add_cancel|{safe_kind}")]
    ])

# === НОВЕ: інлайн «⛔ Зупинити пошук питань» ===
def search_stop_kb() -> InlineKeyboardMarkup:
    """Кнопка для завершення режиму пошуку питань."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛔ Зупинити пошук тестів", callback_data="stop_search")]
    ])
