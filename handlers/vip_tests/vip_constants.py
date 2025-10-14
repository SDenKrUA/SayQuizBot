import os
import logging

logger = logging.getLogger("test_bot")

OWNERS_REG_PATH = os.path.join("tests", "_owners.json")
TESTS_ROOT = "tests"
ILLEGAL_WIN_CHARS = set('<>:"/\\|?*')
IMG_MAX_BYTES = 50 * 1024  # 50KB для VIP-картинок
