import os
import shutil
import stat
from typing import List, Tuple, Optional

TESTS_ROOT = "tests"

# ------ PATH utils ------
def _safe_join(root: str, *parts: str) -> str:
    """
    Безпечно будує абсолютний шлях всередині root. Повертає abs_path.
    Кидає ValueError, якщо шлях виходить за межі root.
    """
    root_abs = os.path.abspath(root)
    path = os.path.abspath(os.path.join(root_abs, *parts))
    if not path.startswith(root_abs):
        raise ValueError("Path traversal detected")
    return path

# ------ Service files / effective emptiness ------

_SERVICE_FILENAMES = {
    "desktop.ini",
    "thumbs.db",
    ".ds_store",
}
_SERVICE_EXTS = {".tmp", ".part", ".lnk"}  # тимчасові/ярлики тощо

def _is_service_file(name: str) -> bool:
    lower = name.lower()
    if lower in _SERVICE_FILENAMES:
        return True
    _, ext = os.path.splitext(lower)
    if ext in _SERVICE_EXTS:
        return True
    # OneDrive інколи створює приховані файли без розширення, починаються з "~$"
    if lower.startswith("~$"):
        return True
    # приховані файли типу .sync, .one drive кеші
    if lower.startswith(".sync") or lower.startswith(".onedrive"):
        return True
    return False

def _is_effectively_empty(abs_dir: str) -> bool:
    """
    Вважаємо теку порожньою, якщо:
      - у ній немає підпапок
      - файли відсутні або складаються лише з службових/прихованих
    """
    try:
        entries = os.listdir(abs_dir)
    except FileNotFoundError:
        return True
    except PermissionError:
        # Якщо під забороною, спробуємо видалення через rmtree далі
        return False

    subdirs = 0
    real_files = 0
    for name in entries:
        p = os.path.join(abs_dir, name)
        if os.path.isdir(p):
            subdirs += 1
        else:
            if not _is_service_file(name):
                real_files += 1
    return subdirs == 0 and real_files == 0

def is_dir_empty(abs_dir: str) -> bool:
    """
    Сувора перевірка: повністю порожня (жодних файлів/папок).
    """
    try:
        return len(os.listdir(abs_dir)) == 0
    except FileNotFoundError:
        return True

# ------ Robust removal helpers ------

def _on_rm_error(func, path, exc_info):
    """
    onerror для shutil.rmtree: знімає readonly-атрибут та пробує ще раз.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        pass
    try:
        func(path)
    except Exception:
        # остання спроба — ігноруємо, нехай підніметься зовнішній виняток
        raise

# ------ Sections (folders) ------

def list_sections(root: str = TESTS_ROOT) -> List[str]:
    """
    Список відносних шляхів підпапок (усі рівні), крім прихованих (# _ . початок)
    """
    res: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # фільтр прихованих/службових тек
        dirnames[:] = [d for d in dirnames if not d.startswith(("#", "_", "."))]
        if dirpath == root:
            continue
        rel = os.path.relpath(dirpath, root)
        res.append(rel)
    res.sort()
    return res

def find_empty_sections(root: str = TESTS_ROOT) -> List[str]:
    """
    Повертає відносні шляхи тек, які ефективно порожні (див. _is_effectively_empty).
    """
    empties: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(("#", "_", "."))]
        if dirpath == root:
            continue
        if not os.path.isdir(dirpath):
            continue
        if _is_effectively_empty(dirpath):
            empties.append(os.path.relpath(dirpath, root))
    empties.sort()
    return empties

def delete_section(rel_path: str, root: str = TESTS_ROOT) -> Tuple[bool, str]:
    """
    Видаляє теку. Дозволяє видалення «ефективно порожніх» тек (де лише службові файли).
    Спершу пробує os.rmdir, якщо не вдається — shutil.rmtree з onerror (Windows/OneDrive locks).
    """
    try:
        abs_dir = _safe_join(root, rel_path)
        if not os.path.isdir(abs_dir):
            return False, "Теки не існує."

        # Не дозволяємо видаляти корінь tests/
        if os.path.abspath(abs_dir) == os.path.abspath(root):
            return False, "Не можна видалити кореневу теку tests."

        # Якщо «ефективно порожня» — приберемо службові файли і видалимо
        if _is_effectively_empty(abs_dir):
            # спроба швидкого rmdir
            try:
                os.rmdir(abs_dir)
                return True, f"Теку «{rel_path}» видалено."
            except Exception:
                # Windows/OneDrive: спробуємо rmtree з onerror
                try:
                    shutil.rmtree(abs_dir, onerror=_on_rm_error)
                    return True, f"Теку «{rel_path}» видалено."
                except Exception as e:
                    return False, f"Помилка: {e}"

        # Якщо є неслужбові файли/підтеки — не видаляємо з міркувань безпеки
        return False, "Тека не порожня."
    except Exception as e:
        return False, f"Помилка: {e}"

def rename_section(rel_path: str, new_name: str, root: str = TESTS_ROOT) -> Tuple[bool, str]:
    """
    Перейменовує останній сегмент шляху теки (не міняючи батьківський шлях).
    """
    try:
        abs_dir = _safe_join(root, rel_path)
        if not os.path.isdir(abs_dir):
            return False, "Теки не існує."
        parent = os.path.dirname(abs_dir)
        new_abs = os.path.join(parent, new_name)
        if os.path.exists(new_abs):
            return False, "Тека з такою назвою вже існує."
        os.replace(abs_dir, new_abs)
        return True, f"Теку «{rel_path}» перейменовано на «{os.path.relpath(new_abs, root)}»."
    except Exception as e:
        return False, f"Помилка: {e}"

# ------ Tests operations ------

def _media_candidates(dir_path: str, base_name: str) -> List[str]:
    """
    Можливі назви тек з медіа для даного тесту (історичні варіанти).
    """
    return [
        os.path.join(dir_path, base_name),
        os.path.join(dir_path, f"#{base_name}"),
        os.path.join(dir_path, f"_{base_name}"),
    ]

def delete_test(json_rel_path: str, with_media: bool = True, root: str = TESTS_ROOT) -> Tuple[bool, str]:
    """
    Видаляє файл тесту .json і, за замовчуванням, пов'язану теку медіа.
    """
    try:
        abs_json = _safe_join(root, json_rel_path)
        if not os.path.isfile(abs_json):
            return False, "Файл тесту не існує."

        dir_path = os.path.dirname(abs_json)
        base_name = os.path.splitext(os.path.basename(abs_json))[0]

        # Видаляємо json
        try:
            os.remove(abs_json)
        except PermissionError:
            os.chmod(abs_json, stat.S_IWRITE)
            os.remove(abs_json)

        # Опційно — видаляємо теку медіа (якщо існує)
        if with_media:
            for cand in _media_candidates(dir_path, base_name):
                if os.path.isdir(cand):
                    try:
                        shutil.rmtree(cand, onerror=_on_rm_error)
                    except Exception:
                        pass

        return True, f"Тест «{json_rel_path}» видалено."
    except Exception as e:
        return False, f"Помилка: {e}"

def move_test(json_rel_path: str, target_section_rel: str, root: str = TESTS_ROOT) -> Tuple[bool, str]:
    """
    Переміщує файл тесту .json і відповідну теку медіа (якщо є) в іншу теку.
    """
    try:
        abs_json = _safe_join(root, json_rel_path)
        if not os.path.isfile(abs_json):
            return False, "Файл тесту не існує."

        src_dir = os.path.dirname(abs_json)
        base_name = os.path.splitext(os.path.basename(abs_json))[0]

        # Підготуємо ціль
        abs_target_dir = _safe_join(root, target_section_rel) if target_section_rel else os.path.abspath(root)
        if not os.path.isdir(abs_target_dir):
            os.makedirs(abs_target_dir, exist_ok=True)

        # Цільовий json
        target_json = os.path.join(abs_target_dir, os.path.basename(abs_json))
        if os.path.exists(target_json):
            return False, "У цільовій теці вже є файл з такою назвою."

        # Спочатку копіюємо з правами, потім атомарно замінюємо
        temp_target = target_json + ".tmp_move"
        shutil.copy2(abs_json, temp_target)
        os.replace(temp_target, target_json)
        # Тільки після успіху видалимо оригінал
        try:
            os.remove(abs_json)
        except PermissionError:
            os.chmod(abs_json, stat.S_IWRITE)
            os.remove(abs_json)

        # Переносимо теку з медіа (якщо є)
        for cand in _media_candidates(src_dir, base_name):
            if os.path.isdir(cand):
                dst_media = os.path.join(abs_target_dir, os.path.basename(cand))
                if os.path.exists(dst_media):
                    # уникаємо конфліктів — пропускаємо
                    continue
                shutil.move(cand, dst_media)

        return True, f"Тест переміщено до «{target_section_rel or '.'}»."
    except Exception as e:
        return False, f"Помилка: {e}"

def find_custom_tests(root: str = TESTS_ROOT) -> List[str]:
    """
    Повертає відносні шляхи JSON-файлів тестів, у назві яких є '(custom)'.
    """
    res: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(("#", "_", "."))]
        for fname in filenames:
            if not fname.lower().endswith(".json"):
                continue
            lower = fname.lower()
            if "(custom)" in lower or " (custom)" in fname:
                res.append(os.path.relpath(os.path.join(dirpath, fname), root))
    res.sort()
    return res
