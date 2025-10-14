# utils/logger.py
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# === Env ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "").strip()  # приклад: /data/logs/bot.log або пусто

# === Формат логів ===
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def _ensure_parent_dir(path_str: str) -> None:
    """
    Створює батьківську теку для файла, якщо вона відсутня.
    """
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
    """
    Створює обертовий file handler:
      - maxBytes ~ 5 MB на файл
      - backupCount 3 (разом ~20 MB)
    """
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
    Налаштовує root-логгер один раз. Без дублювання хендлерів при повторному імпорті.
    Виклич у bot.py якомога раніше (після load_dotenv()).
    """
    root = logging.getLogger()
    if getattr(root, "_sayquiz_configured", False):
        return

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    root.setLevel(level)

    # Прибираємо існуючі хендлери, якщо вони є
    for h in list(root.handlers):
        root.removeHandler(h)

    if LOG_FILE:
        handler = _build_file_handler(LOG_FILE, level)
    else:
        handler = _build_console_handler(level)

    root.addHandler(handler)
    root._sayquiz_configured = True  # маркер, щоб не конфігурувати двічі

    # Опційно: зменшити балакучість сторонніх бібліотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)

# Стандартна точка входу при імпорті
setup_logging()

# Експортуємо зручний логгер для модулів
logger = logging.getLogger("sayquiz")
