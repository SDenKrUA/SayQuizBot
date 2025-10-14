import os
import json
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("test_bot")

TESTS_ROOT = "tests"

# Імена/префікси, які вважаємо "прихованими" (не показуємо у браузері розділів)
HIDDEN_PREFIXES = ("#", "_", ".")

# Службові JSON, які не є тестами (не виводимо у списку тестів)
COMMENTS_SUFFIX = ".comments.json"  # лишаємо для зворотної сумісності (не використовується напряму)
IGNORED_JSON_SUFFIXES = (
    ".comments.json",     # коментарі
    ".docx.meta.json",    # мета до DOCX
)

# ====== ПРИКРІПЛЕННЯ МЕДІА ДО ПИТАНЬ ======
def _find_first_exist(base_dir: str, candidates: list[str]) -> Optional[str]:
    for rel in candidates:
        p = os.path.join(base_dir, rel)
        if os.path.exists(p):
            return p
    return None

def attach_images(questions: List[dict], media_dir: Optional[str]) -> List[dict]:
    """
    РОЗШИРЕНА версія (назва збережена для зворотної сумісності).
    Для кожного питання i (1..N) підтягуємо:
      - image: image{i}|img{i}|q{i} з розширеннями: jpg, jpeg, png, webp, gif
      - video: video{i}|vid{i}|q{i} з розширеннями: mp4, 3gp, avi, mkv, webm, mpeg, mpg, m4v, mov, ts, flv
      - audio: audio{i}|aud{i}|q{i} з розширеннями: mp3, wav, ogg, m4a, aac, flac
      - document: doc{i}|document{i}|q{i} з розширеннями: pdf, docx, doc, xlsx
    Записуємо у поля 'image'/'video'/'audio'/'document' абсолютні шляхи (якщо знайдено).

    ВАЖЛИВО:
    - У відправниках (testing/learning) .mp4 піде як відео, інші відео — як документ (файл),
      аудіо — як audio, зображення — photo/animation (gif).
    """
    if not questions:
        return questions
    if not media_dir or not os.path.isdir(media_dir):
        logger.debug("DEBUG: Знайдено медіа: 0/%d (теку не знайдено)", len(questions))
        return questions

    image_exts = ["jpg", "jpeg", "png", "webp", "gif"]
    video_exts = ["mp4", "3gp", "avi", "mkv", "webm", "mpeg", "mpg", "m4v", "mov", "ts", "flv"]
    audio_exts = ["mp3", "wav", "ogg", "m4a", "aac", "flac"]
    doc_exts   = ["pdf", "docx", "doc", "xlsx"]

    # Пріоритет імен-файлів зберігаємо як було: image/img/q; video/vid/q; audio/aud/q; doc/document/q
    def build_candidates(prefixes: List[str], exts: List[str], i: int) -> List[str]:
        cands: List[str] = []
        for pref in prefixes:
            for ext in exts:
                cands.append(f"{pref}{i}.{ext}")
        return cands

    found_any = 0
    for i, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            continue

        # IMAGE
        image_path = _find_first_exist(
            media_dir,
            build_candidates(["image", "img", "q"], image_exts, i)
        )
        if image_path:
            q["image"] = os.path.abspath(image_path)

        # VIDEO (mp4 залишиться inline-відео; інші формати підуть як документ)
        # Пріоритет: спочатку шукаємо mp4, потім інші
        video_path = _find_first_exist(
            media_dir,
            build_candidates(["video", "vid", "q"], ["mp4"], i)
        )
        if not video_path:
            video_path = _find_first_exist(
                media_dir,
                build_candidates(["video", "vid", "q"], [e for e in video_exts if e != "mp4"], i)
            )
        if video_path:
            q["video"] = os.path.abspath(video_path)

        # AUDIO
        audio_path = _find_first_exist(
            media_dir,
            build_candidates(["audio", "aud", "q"], audio_exts, i)
        )
        if audio_path:
            q["audio"] = os.path.abspath(audio_path)

        # DOCUMENT
        doc_path = _find_first_exist(
            media_dir,
            build_candidates(["doc", "document", "q"], doc_exts, i)
        )
        if doc_path:
            q["document"] = os.path.abspath(doc_path)

        if image_path or video_path or audio_path or doc_path:
            found_any += 1

    logger.debug("DEBUG: Знайдено медіа (будь-якого типу) для %d/%d питань", found_any, len(questions))
    return questions


# ====== ВНУТРІШНІ ======
def _load_json(path: str) -> List[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"[LOADER] Failed to load {path}: {e}")
        return []


def _detect_images_dir(dir_path: str, base_name: str) -> Optional[str]:
    """
    Визначає теку з медіа для тесту (історично — "зображення").
    Підтримує:
      <dir>/<base_name>
      <dir>/#<base_name>
      <dir>/_<base_name>
    Повертає існуючий шлях або None.
    """
    candidates = [
        os.path.join(dir_path, base_name),
        os.path.join(dir_path, f"#{base_name}"),
        os.path.join(dir_path, f"_{base_name}"),
    ]
    # Розширений список "ймовірних" файлів для швидкої перевірки наявності медіа
    probe_images = [f"image1.{ext}" for ext in ["jpg", "jpeg", "png", "webp", "gif"]] + \
                   [f"img1.{ext}"   for ext in ["jpg", "jpeg", "png", "webp", "gif"]] + \
                   [f"q1.{ext}"     for ext in ["jpg", "jpeg", "png", "webp", "gif"]]
    probe_videos = [f"video1.{ext}" for ext in ["mp4", "3gp", "avi", "mkv", "webm", "mpeg", "mpg", "m4v", "mov", "ts", "flv"]] + \
                   [f"vid1.{ext}"   for ext in ["mp4", "3gp", "avi", "mkv", "webm", "mpeg", "mpg", "m4v", "mov", "ts", "flv"]] + \
                   [f"q1.{ext}"     for ext in ["mp4", "3gp", "avi", "mkv", "webm", "mpeg", "mpg", "m4v", "mov", "ts", "flv"]]
    probe_audios = [f"audio1.{ext}" for ext in ["mp3", "wav", "ogg", "m4a", "aac", "flac"]] + \
                   [f"aud1.{ext}"   for ext in ["mp3", "wav", "ogg", "m4a", "aac", "flac"]] + \
                   [f"q1.{ext}"     for ext in ["mp3", "wav", "ogg", "m4a", "aac", "flac"]]
    probe_docs   = [f"doc1.{ext}" for ext in ["pdf", "docx", "doc", "xlsx"]] + \
                   [f"document1.{ext}" for ext in ["pdf", "docx", "doc", "xlsx"]] + \
                   [f"q1.{ext}" for ext in ["pdf", "docx", "doc", "xlsx"]]

    for cand in candidates:
        if os.path.isdir(cand):
            # Мінімальна перевірка: наявність хоча б якогось media першого питання
            for probe in (*probe_images, *probe_videos, *probe_audios, *probe_docs):
                if os.path.exists(os.path.join(cand, probe)):
                    return cand
            # навіть якщо нічого з типових не знайшли — повернемо cand;
            # attach_images сам перевірить детальніше
            return cand
    return None


def _entry_from_json(json_path: str) -> Tuple[str, dict]:
    """
    Повертає (test_name, entry)
    entry = {
        "questions": [...],
        "total": int,
        "images_dir": <dir or None>,
        "dir": <directory>,
        "json_path": <full path>
    }
    """
    base_name = os.path.splitext(os.path.basename(json_path))[0]
    dir_path = os.path.dirname(json_path)
    images_dir = _detect_images_dir(dir_path, base_name)
    questions = _load_json(json_path)
    return base_name, {
        "questions": questions,
        "total": len(questions),
        "images_dir": images_dir,
        "dir": dir_path,
        "json_path": json_path,
    }


def _is_hidden_name(name: str) -> bool:
    return name.startswith(HIDDEN_PREFIXES)


def _is_ignored_json(filename: str) -> bool:
    """True, якщо JSON-файл службовий і його треба ігнорувати як тест."""
    fname = filename.lower()
    return any(fname.endswith(suf) for suf in IGNORED_JSON_SUFFIXES)


def _is_potential_images_dir(abs_dir: str, images_dirs: set) -> bool:
    return os.path.abspath(abs_dir) in images_dirs


# ====== СКАНУВАННЯ ТЕСТІВ ======
def discover_tests(root_dir: str = TESTS_ROOT) -> Dict[str, dict]:
    """
    Повертає ПЛОСКИЙ каталог тестів {name: entry}.
    - Ігноруємо файли, що починаються з #/_/. (приховані)
    - Ігноруємо службові JSON (*.comments.json, *.docx.meta.json)
    - Рекурсивно обходимо підтеки.
    """
    catalog: Dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # ховаємо службові теки (починаються з #/_/.)
        dirnames[:] = [d for d in dirnames if not _is_hidden_name(d)]

        for fname in filenames:
            if _is_hidden_name(fname):
                continue
            if not fname.lower().endswith(".json"):
                continue
            if _is_ignored_json(fname):
                # службові JSON не є тестами
                continue

            json_path = os.path.join(dirpath, fname)
            name, entry = _entry_from_json(json_path)
            if name in catalog:
                logger.warning(f"[LOADER] Duplicate test name '{name}' at {json_path}. Keeping first occurrence.")
                continue
            catalog[name] = entry
    logger.debug(f"[LOADER] discover_tests: loaded {len(catalog)} tests")
    return catalog


# ====== ДЕРЕВО РОЗДІЛІВ (з урахуванням порожніх тек) ======
def discover_tests_hierarchy(root_dir: str = TESTS_ROOT) -> dict:
    """
    Будує дерево розділів, включаючи порожні теки, але:
      - ігнорує теки, що починаються з #/_/. (приховані)
      - ігнорує теки, які є "теками зображень/медіа" для тестів (назва як у тесту, або #/_, і містять media типових назв)
    Структура вузла:
      node = {"subdirs": {name: node, ...}, "tests": [test_name, ...], "dir": abs_path}
    """
    root_abs = os.path.abspath(root_dir)

    # Спочатку зберемо тести (щоб знати їх можливі теки з медіа)
    catalog = discover_tests(root_dir)

    # Набір тек із медіа (для відсіву при побудові дерева)
    images_dirs: set = set()
    for entry in catalog.values():
        if entry.get("images_dir"):
            images_dirs.add(os.path.abspath(entry["images_dir"]))

    def make_node(dir_path: str) -> dict:
        return {"subdirs": {}, "tests": [], "dir": dir_path}

    root = make_node(root_abs)

    def ensure_node(parts: List[str]) -> dict:
        node = root
        cur = root_abs
        for p in parts:
            cur = os.path.join(cur, p)
            if p not in node["subdirs"]:
                node["subdirs"][p] = make_node(cur)
            node = node["subdirs"][p]
        return node

    # 1) Проходимо ФС і додаємо ВСІ (неприховані) теки
    for dirpath, dirnames, filenames in os.walk(root_dir):
        filtered = []
        for d in dirnames:
            abs_d = os.path.abspath(os.path.join(dirpath, d))
            if _is_hidden_name(d):
                continue
            if _is_potential_images_dir(abs_d, images_dirs):
                # Це тека з медіа до тесту — ховаємо її у браузері
                continue
            if d.lower().endswith(".comments"):
                continue
            filtered.append(d)
        dirnames[:] = filtered

        # Створюємо вузол у дереві (щоб показати порожні теки теж)
        abs_dir = os.path.abspath(dirpath)
        rel = os.path.relpath(abs_dir, root_abs)
        parts = [] if rel == "." else rel.split(os.sep)
        ensure_node(parts)

    # 2) Розкладаємо тести по своїх теках
    for test_name, entry in catalog.items():
        abs_dir = os.path.abspath(entry["dir"])
        rel = os.path.relpath(abs_dir, root_abs)
        parts = [] if rel == "." else rel.split(os.sep)
        node = ensure_node(parts)
        node["tests"].append(test_name)

    # 3) Сортування для стабільного вигляду
    def sort_node(n: dict):
        n["tests"].sort()
        for key in sorted(list(n["subdirs"].keys())):
            sort_node(n["subdirs"][key])

    sort_node(root)
    return root


def get_node_for_path(tree: dict, path: List[str]) -> Optional[dict]:
    node = tree
    for p in path:
        if not node or "subdirs" not in node:
            return None
        node = node["subdirs"].get(p)
    return node


def build_listing_for_path(tree: dict, path: List[str]) -> Tuple[List[str], List[str], str]:
    """
    Повертає (subfolders, tests, abs_dir) для вузла за шляхом `path`.
    subfolders та tests уже відсортовані у discover_tests_hierarchy().
    """
    node = get_node_for_path(tree, path)
    if not node:
        return [], [], os.path.abspath(TESTS_ROOT)
    subfolders = sorted(list(node["subdirs"].keys()))
    tests = list(node["tests"])
    return subfolders, tests, node["dir"]
