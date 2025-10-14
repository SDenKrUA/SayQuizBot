import os
import json
import asyncio
import logging
from telegram.ext import ContextTypes
from utils.loader import attach_images

logger = logging.getLogger("test_bot")

IGNORED_JSON_SUFFIXES = (".comments.json", ".docx.meta.json")

def _find_json_for_test(test_dir: str, test_name: str) -> str | None:
    """
    Повертає шлях до JSON-файла тесту в теці test_dir.
    Спочатку шукаємо точну назву `<test_name>.json`,
    якщо нема — пробуємо знайти найкращий збіг серед .json у теці,
    ігноруючи службові файли (.comments.json, .docx.meta.json).
    """
    exact = os.path.join(test_dir, f"{test_name}.json")
    if os.path.exists(exact):
        return exact

    try:
        jsons = [
            f for f in os.listdir(test_dir)
            if f.lower().endswith(".json") and not any(f.lower().endswith(suf) for suf in IGNORED_JSON_SUFFIXES)
        ]
    except Exception:
        return None

    if not jsons:
        return None

    low = test_name.lower()
    # найкращий кандидат: точний збіг base-name без .json, далі — найкоротший
    candidates = sorted(jsons, key=lambda n: (0 if n[:-5].lower() == low else 1, len(n)))
    return os.path.join(test_dir, candidates[0])

async def reload_current_test_state(context: ContextTypes.DEFAULT_TYPE):
    """
    Перечитує базовий і кастомний JSON поточного тесту, підтягує зображення,
    оновлює context.user_data['questions'] та ['total_questions'].

    Викликайте перед стартом режимів (навчання/тестування) і після генерації DOCX,
    щоб RAM-стан завжди відповідав файлам на диску.
    """
    test_name = context.user_data.get("current_test")
    test_dir = context.user_data.get("current_test_dir")
    if not test_name or not test_dir:
        return

    # Пошук базового JSON з fallback
    base_path = _find_json_for_test(test_dir, test_name)
    custom_path = os.path.join(test_dir, f"{test_name} (custom).json")

    base_questions, custom_questions = [], []

    # Читаємо базовий JSON
    try:
        if base_path and os.path.exists(base_path):
            with open(base_path, "r", encoding="utf-8") as f:
                base_questions = json.load(f) or []
            if not isinstance(base_questions, list):
                base_questions = []
    except Exception as e:
        logger.warning(f"[RELOAD] base load error: {e}")

    # Читаємо кастомний JSON
    try:
        if os.path.exists(custom_path):
            with open(custom_path, "r", encoding="utf-8") as f:
                custom_questions = json.load(f) or []
            if not isinstance(custom_questions, list):
                custom_questions = []
    except Exception as e:
        logger.warning(f"[RELOAD] custom load error: {e}")

    # Підтягуємо зображення асинхронно через executor (attach_images — синхронна)
    loop = asyncio.get_event_loop()
    try:
        # для базових зображень беремо теку за фактичною основою імені JSON
        base_images_dir_name = test_name
        if base_path:
            base_images_dir_name = os.path.splitext(os.path.basename(base_path))[0]
        base_questions = await loop.run_in_executor(
            None, attach_images, base_questions, os.path.join(test_dir, base_images_dir_name)
        )
    except Exception as e:
        logger.warning(f"[RELOAD] attach base images error: {e}")

    try:
        custom_questions = await loop.run_in_executor(
            None, attach_images, custom_questions, os.path.join(test_dir, f"{test_name} (custom)")
        )
    except Exception as e:
        logger.warning(f"[RELOAD] attach custom images error: {e}")

    # Об’єднуємо та оновлюємо RAM-стан
    questions = (base_questions or []) + (custom_questions or [])
    context.user_data["questions"] = questions
    context.user_data["total_questions"] = len(questions)
