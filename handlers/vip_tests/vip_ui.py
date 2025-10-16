from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import os
from typing import List

from .vip_constants import TESTS_ROOT

# ----- helpers -----

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_IGNORABLE_FILES = {"thumbs.db", "desktop.ini", ".ds_store"}

def _list_parent_stems(dir_path: str) -> set:
    """
    Повертає множину стемів (імен без розширення) для файлів у теці,
    що сигналізують про тест:
      - *.json
      - *.docx
      - *.docx.meta.json  -> стем = ім'я до першої крапки (тобто 'Name' для 'Name.docx.meta.json')
    """
    stems = set()
    try:
        for fname in os.listdir(dir_path):
            low = fname.lower()
            # .json
            if low.endswith(".json"):
                stem = fname[: -len(".json")]
                stems.add(stem)
                if stem.endswith(" (custom)"):
                    stems.add(stem[:-9].rstrip())
                continue

            # .docx
            if low.endswith(".docx"):
                stem = fname[: -len(".docx")]
                stems.add(stem)
                continue

            # .docx.meta.json
            if low.endswith(".docx.meta.json"):
                stem = fname[: -len(".docx.meta.json")]
                stems.add(stem)
                continue
    except Exception:
        pass
    return stems


def _dir_is_image_bucket(abs_dir: str) -> bool:
    """
    True, якщо папка:
      - не містить підпапок
      - і складається ТІЛЬКИ з картинок (ігноруючи службові файли)
      - або «переважно з картинок»: >=3 картинки і всі інші файли — службові.
    """
    try:
        entries = os.listdir(abs_dir)
    except Exception:
        return False

    if not entries:
        return False

    image_count = 0
    non_image_non_ignorable = 0

    for name in entries:
        p = os.path.join(abs_dir, name)
        if os.path.isdir(p):
            return False  # є підпапки — це не «кошик картинок»

        low = name.lower()
        if low in _IGNORABLE_FILES:
            continue

        ext = os.path.splitext(name)[1].lower()
        if ext in _IMG_EXTS:
            image_count += 1
        else:
            non_image_non_ignorable += 1

    # чисто з картинок
    if image_count > 0 and non_image_non_ignorable == 0:
        return True

    # «переважно картинки» — >=3 картинки, інше тільки службове
    if image_count >= 3 and non_image_non_ignorable == 0:
        return True

    return False


def _should_hide_subdir(abs_parent: str, subdir_name: str) -> bool:
    """
    Правила приховування папок-зображень у браузері:
      - якщо у батьківській теці є файл-тест зі стемом, що дорівнює назві папки
        (Name.json / Name.docx / Name.docx.meta.json) — ховаємо Name/
      - якщо назва починається з '#' або '_' і після префіксу збігається зі стемом тесту — ховаємо
      - якщо закінчується на '.comments' — ховаємо
      - якщо сама тека виглядає як «кошик картинок» — ховаємо
    """
    stems = _list_parent_stems(abs_parent)

    # 1) Збіг зі стемом тестового файлу
    if subdir_name in stems:
        return True

    # 2) Варіанти з префіксом
    if subdir_name.startswith("#") or subdir_name.startswith("_"):
        core = subdir_name[1:]
        if core in stems:
            return True

    # 3) Папка коментарів
    if subdir_name.endswith(".comments"):
        return True

    # 4) Папка з (переважно) картинок
    abs_candidate = os.path.join(abs_parent, subdir_name)
    if _dir_is_image_bucket(abs_candidate):
        return True

    return False


# ----- UI builders -----

def _placement_kb() -> InlineKeyboardMarkup:
    """
    Початковий вибір місця розміщення тесту.
    Додаємо уніфікований футер «⛔ Скасувати».
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗂 Додати в наявний розділ", callback_data="vip_choose_folder")],
        [InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])


def _dup_owner_kb() -> InlineKeyboardMarkup:
    """
    Клавіатура для випадку дубля тесту.
    Додаємо уніфікований футер «⛔ Скасувати».
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("♻️ Замінити тест", callback_data="vip_dup_replace")],
        [InlineKeyboardButton("👁️ Переглянути тест", callback_data="vip_dup_view")],
        [InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ])


def _folder_browser_kb(path: List[str]) -> InlineKeyboardMarkup:
    """
    Браузер вибору розділів із фільтром службових тек (картинки для тестів тощо).
    Не показує:
      - папки, що відповідають стему існуючих у цій теці *.json/*.docx/*.docx.meta.json;
      - '#Name', '_Name', '*.comments';
      - папки, які «кошики картинок» (тільки/переважно зображення, без підпапок).

    Додаємо футер:
      - якщо є шлях — «⬅️ Назад» (vip_up)
      - завжди — «⛔ Скасувати» (vip_cancel)
    """
    abs_dir = os.path.join(TESTS_ROOT, *path) if path else TESTS_ROOT
    try:
        items = os.listdir(abs_dir)
    except FileNotFoundError:
        items = []

    raw_subdirs = [n for n in items if os.path.isdir(os.path.join(abs_dir, n))]

    subdirs = []
    for name in raw_subdirs:
        try:
            if _should_hide_subdir(abs_dir, name):
                continue
            subdirs.append(name)
        except Exception:
            subdirs.append(name)

    subdirs.sort(key=lambda s: s.lower())

    rows = [[InlineKeyboardButton(f"📁 {name}", callback_data=f"vip_open|{name}")] for name in subdirs]

    # Контрольний ряд
    ctrl_row = []
    if path:
        ctrl_row.append(InlineKeyboardButton("⬅️ Назад", callback_data="vip_up"))
    ctrl_row.append(InlineKeyboardButton("✅ Обрати тут", callback_data="vip_choose_here"))
    rows.append(ctrl_row)

    # Футер: Скасувати
    rows.append([InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")])

    return InlineKeyboardMarkup(rows)


def _images_prompt_kb() -> InlineKeyboardMarkup:
    """
    Підказка після створення/вибору тесту: завантажити архів картинок зараз чи пізніше.
    Додаємо уніфікований футер «⬅️ Назад» (повернення до вибору розділів) і «⛔ Скасувати».
    """
    rows = [
        [InlineKeyboardButton("📦 Додати архів з картинками", callback_data="vip_img_upload")],
        [InlineKeyboardButton("⏭️ Додати архів пізніше", callback_data="vip_img_later")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="vip_choose_folder"),
         InlineKeyboardButton("⛔ Скасувати", callback_data="vip_cancel")],
    ]
    return InlineKeyboardMarkup(rows)
