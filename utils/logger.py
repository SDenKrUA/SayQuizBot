# utils/logger.py
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# === Env ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "").strip()  # напр.: /data/logs/bot.log або пусто

# === Формат логів ===
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def _ensure_parent_dir(path_str: str) -> None:
    """Створює батьківську теку для файла, якщо її немає."""
    if not path_str:
        return
    p = Path(path_str)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)

def _build_console_handler(level: int) -> logging.Handler:
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    return ch

def _build_file_handler(path_str: str, level: int) -> logging.Handler:
    """Обертовий file handler: ~5MB * 4 файли ≈ 20MB."""
    _ensure_parent_dir(path_str)
    fh = RotatingFileHandler(
        path_str,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    return fh

def setup_logging() -> None:
    """
    Налаштування root-логгера один раз.
    Виклич якнайраніше (після load_dotenv()).
    """
    root = logging.getLogger()
    if getattr(root, "_sayquiz_configured", False):
        return

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    root.setLevel(level)

    # прибираємо попередні хендлери
    for h in list(root.handlers):
        root.removeHandler(h)

    # консоль або файл
    if LOG_FILE:
        handler = _build_file_handler(LOG_FILE, level)
    else:
        handler = _build_console_handler(level)

    root.addHandler(handler)
    root._sayquiz_configured = True

    # зменшити балакучість сторонніх бібліотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)

# --- Беквард-сумісність з твоїм імпортом ---
def setup_logger() -> None:
    """
    Сумісна назва для старого імпорту:
        from utils.logger import setup_logger
    Робить те саме, що setup_logging().
    """
    setup_logging()

# Виконуємо одразу при імпорті (безпечно — захищено від повторної конфігурації)
setup_logging()

# Зручний модульний логгер
logger = logging.getLogger("sayquiz")
