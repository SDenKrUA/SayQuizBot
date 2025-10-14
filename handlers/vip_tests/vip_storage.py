import json
import os
import shutil
import logging
from typing import Dict, Any, Optional, List

from telegram.ext import ContextTypes

from .vip_constants import OWNERS_REG_PATH, TESTS_ROOT

logger = logging.getLogger("test_bot")

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _load_owners() -> Dict[str, Any]:
    if os.path.exists(OWNERS_REG_PATH):
        try:
            with open(OWNERS_REG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def _save_owners(data: Dict[str, Any]) -> None:
    try:
        with open(OWNERS_REG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Failed to save owners registry: %s", e)

def _relative_to_tests(abs_path: str) -> str:
    abs_path = os.path.abspath(abs_path)
    tests_root = os.path.abspath(TESTS_ROOT)
    try:
        rel = os.path.relpath(abs_path, tests_root)
    except ValueError:
        rel = abs_path
    return rel.replace("\\", "/")

# --------- «Ефективно порожня» тека + агресивне підняття вгору ---------

_IGNORABLE_NAMES = {
    ".ds_store", "thumbs.db", "desktop.ini", ".gitkeep", ".gitignore",
    # іноді архіватори/системи лишають службові мітки:
    ".directory", "readme.txt", ".placeholder"
}

def _is_effectively_empty(dir_path: str) -> bool:
    """
    Порожньою вважається тека, якщо:
      - вона існує;
      - у ній немає підпапок;
      - усі файли — службові (_IGNORABLE_NAMES) або взагалі немає файлів.
    """
    try:
        names = os.listdir(dir_path)
    except Exception as e:
        logger.debug("[CLEANUP] listdir failed for %s: %s", dir_path, e)
        return False

    if not names:
        logger.debug("[CLEANUP] %s is empty", dir_path)
        return True

    for name in names:
        full = os.path.join(dir_path, name)
        if os.path.isdir(full):
            logger.debug("[CLEANUP] %s is not empty (has subdir %s)", dir_path, name)
            return False
        if name.lower() in _IGNORABLE_NAMES:
            continue
        # будь-який інший файл — рахуємо, що не порожня
        logger.debug("[CLEANUP] %s is not empty (file %s)", dir_path, name)
        return False

    logger.debug("[CLEANUP] %s has only ignorable files: %s", dir_path, names)
    return True

def _cleanup_empty_dirs(start_dir: str) -> None:
    """
    Видаляє ефективно порожні теки від start_dir вгору до tests/.
    Не чіпає сам TESTS_ROOT.
    Працює навіть якщо start_dir вже видалено (починає з найближчої існуючої).
    """
    try:
        root_abs = os.path.abspath(TESTS_ROOT)
        cur = os.path.abspath(start_dir)
        logger.debug("[CLEANUP] START: start_dir=%s (abs=%s), root=%s", start_dir, cur, root_abs)

        # Якщо стартова тека не існує — піднімаємось до першої існуючої
        while not os.path.isdir(cur) and cur.startswith(root_abs) and cur != root_abs:
            logger.debug("[CLEANUP] %s doesn't exist, go parent", cur)
            cur = os.path.dirname(cur)

        while cur.startswith(root_abs) and cur != root_abs:
            if not os.path.isdir(cur):
                logger.debug("[CLEANUP] %s no longer a dir, up", cur)
                cur = os.path.dirname(cur)
                continue

            if _is_effectively_empty(cur):
                try:
                    os.rmdir(cur)
                    logger.info("[CLEANUP] removed empty dir: %s", cur)
                except Exception as e:
                    logger.debug("[CLEANUP] rmdir failed for %s: %s", cur, e)
                    break
                cur = os.path.dirname(cur)
                continue
            else:
                logger.debug("[CLEANUP] stop at non-empty dir: %s", cur)
                break
    except Exception as e:
        logger.debug("[CLEANUP] unexpected error: %s", e)

# ---- catalogs / discovery ----
from utils.loader import discover_tests, discover_tests_hierarchy

def _refresh_catalogs(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data["tests_catalog"] = discover_tests(TESTS_ROOT)
    context.bot_data["tests_tree"] = discover_tests_hierarchy(TESTS_ROOT)

def _test_name_exists(context: ContextTypes.DEFAULT_TYPE, name: str) -> bool:
    context.bot_data["tests_catalog"] = discover_tests(TESTS_ROOT)
    catalog = context.bot_data.get("tests_catalog") or {}
    return name in catalog

def _catalog_entry(context: ContextTypes.DEFAULT_TYPE, name: str) -> Optional[Dict[str, Any]]:
    catalog = context.bot_data.get("tests_catalog") or {}
    return catalog.get(name)

def _find_json_in_dir(test_dir: str, test_name: str) -> Optional[str]:
    exact = os.path.join(test_dir, f"{test_name}.json")
    if os.path.exists(exact):
        return exact
    try:
        jsons = [f for f in os.listdir(test_dir) if f.lower().endswith(".json")]
    except Exception:
        return None
    if not jsons:
        return None
    low = test_name.lower()
    candidates = sorted(jsons, key=lambda n: (0 if n[:-5].lower() == low else 1, len(n)))
    return os.path.join(test_dir, candidates[0])

# ====== meta (trusted/pending) в tests/_owners.json ======

def _ensure_meta_shape(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    m = dict(meta or {})
    m.setdefault("owner_id", None)
    m.setdefault("trusted", [])
    m.setdefault("trusted_usernames", [])
    m.setdefault("pending", [])
    return m

def get_meta_for_rel(rel: str) -> Dict[str, Any]:
    owners = _load_owners()
    return _ensure_meta_shape(owners.get(rel, {}))

def save_meta_for_rel(rel: str, meta: Dict[str, Any]) -> None:
    owners = _load_owners()
    owners[rel] = _ensure_meta_shape(meta)
    _save_owners(owners)

# утиліти для edit-меню
def resolve_item_by_index(context: ContextTypes.DEFAULT_TYPE, idx_str: str) -> Optional[Dict[str, Any]]:
    try:
        idx = int(idx_str)
    except ValueError:
        return None
    items = context.user_data.get("vip_mytests") or []
    if not (0 <= idx < len(items)):
        return None
    return items[idx]

def set_images_dir_in_context(context: ContextTypes.DEFAULT_TYPE, abs_dir: str, test_name: str) -> None:
    context.user_data["vip_images_dir"] = os.path.join(abs_dir, test_name)

def get_requests_count_for_rel(rel: str) -> int:
    meta = get_meta_for_rel(rel)
    return len(meta.get("pending", []))

# ====== Довірені: допоміжні ======

def list_trusted_display(trusted_ids: List[int], trusted_unames: List[str]) -> str:
    lines = []
    for uid in trusted_ids or []:
        lines.append(f"• ID:{uid}")
    for uname in trusted_unames or []:
        lines.append(f"• @{uname}")
    return "\n".join(lines)

def add_trusted_username(rel: str, uname: str) -> bool:
    meta = get_meta_for_rel(rel)
    unames = meta.get("trusted_usernames", [])
    if uname.lower() in [u.lower() for u in unames]:
        return False
    unames.append(uname)
    meta["trusted_usernames"] = unames
    save_meta_for_rel(rel, meta)
    return True

def remove_trusted_by_key(rel: str, kind: str, key: str) -> bool:
    meta = get_meta_for_rel(rel)
    changed = False
    if kind == "id":
        try:
            uid = int(key)
        except ValueError:
            return False
        ids = meta.get("trusted", [])
        if uid in ids:
            ids.remove(uid)
            meta["trusted"] = ids
            changed = True
    elif kind == "uname":
        unames = meta.get("trusted_usernames", [])
        new = [u for u in unames if u.lower() != key.lower()]
        if len(new) != len(unames):
            meta["trusted_usernames"] = new
            changed = True
    if changed:
        save_meta_for_rel(rel, meta)
    return changed

def list_pending_display(pending: List[Dict[str, Any]]) -> str:
    lines = []
    for i, req in enumerate(pending or [], start=1):
        lines.append(f"{i}. @{req.get('username','-')} (ID:{req.get('user_id','?')})")
    return "\n".join(lines)

def accept_pending_by_key(rel: str, idx_str: str) -> bool:
    try:
        idx = int(idx_str)
    except ValueError:
        return False
    meta = get_meta_for_rel(rel)
    pend = list(meta.get("pending", []))
    if not (0 <= idx < len(pend)):
        return False
    req = pend.pop(idx)
    # додаємо у trusted
    ids = meta.get("trusted", [])
    unames = meta.get("trusted_usernames", [])
    uid = req.get("user_id")
    uname = req.get("username")
    if uid and uid not in ids:
        ids.append(uid)
    if uname and uname.lower() not in [u.lower() for u in unames]:
        unames.append(uname)
    meta["trusted"] = ids
    meta["trusted_usernames"] = unames
    meta["pending"] = pend
    save_meta_for_rel(rel, meta)
    return True

def decline_pending_by_key(rel: str, idx_str: str) -> bool:
    try:
        idx = int(idx_str)
    except ValueError:
        return False
    meta = get_meta_for_rel(rel)
    pend = list(meta.get("pending", []))
    if not (0 <= idx < len(pend)):
        return False
    pend.pop(idx)
    meta["pending"] = pend
    save_meta_for_rel(rel, meta)
    return True

# ====== Перевірка прав редагування ======

def can_edit_vip(rel: str, user_id: int, username: Optional[str]) -> bool:
    meta = get_meta_for_rel(rel)
    if user_id and meta.get("owner_id") == user_id:
        return True
    if user_id and user_id in (meta.get("trusted") or []):
        return True
    uname = (username or "").strip()
    if uname and uname in (meta.get("trusted_usernames") or []):
        return True
    return False
