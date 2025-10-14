# handlers/vip_tests/vip_utils.py
import os
import io
import re
import zipfile
from typing import Dict, Tuple

# ---- Опційне стиснення зображень ----
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# Які розширення вважаємо яким типом
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp"}  # ✅ додано .3gp
DOC_EXTS   = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv"}

# Ліміт стиснення для картинок (байт). Невеликий, щоб Telegram швидше приймав.
IMG_TARGET_LIMIT = 200 * 1024  # 200 KB

# ---------------- Назви тестів ----------------

_ILLEGAL_WIN_CHARS = set('<>:"/\\|?*')

def _sanitize_test_name(name: str) -> str:
    """
    Очищає назву тесту: прибирає заборонені символи Windows, обрізає пробіли.
    Порожній результат вважається невалідним.
    """
    if not isinstance(name, str):
        return ""
    s = name.strip()
    if not s:
        return ""
    if any(ch in _ILLEGAL_WIN_CHARS for ch in s):
        return ""
    return s

# --------------- Утиліти для ZIP ---------------

_num_re = re.compile(r"(\d+)")

def _extract_index_from_name(stem: str) -> int | None:
    """
    Повертає перший знайдений номер з імені (без розширення), наприклад:
      '03_pump' -> 3, 'audio12_fail' -> 12, інакше None
    """
    m = _num_re.search(stem)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _write_bytes(dest_path: str, data: bytes) -> None:
    _ensure_dir(os.path.dirname(dest_path))
    with open(dest_path, "wb") as f:
        f.write(data)

def _compress_image_bytes(data: bytes, limit_bytes: int = IMG_TARGET_LIMIT) -> bytes:
    """
    Повертає стиснуті JPEG-байти <= limit_bytes, якщо є Pillow.
    Якщо Pillow немає або сталося виключення — повертає оригінал.
    """
    if not PIL_AVAILABLE:
        return data
    try:
        im = Image.open(io.BytesIO(data))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")

        # початкове зменшення довгої сторони до ~1400px
        max_side = max(im.size)
        if max_side > 1400:
            scale = 1400.0 / max_side
            new_size = (max(1, int(im.size[0] * scale)), max(1, int(im.size[1] * scale)))
            im = im.resize(new_size, Image.LANCZOS)

        # бінарний пошук по якості JPEG
        low, high = 20, 90
        best = None
        for _ in range(9):
            q = (low + high) // 2
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=q, optimize=True, progressive=True)
            b = buf.getvalue()
            if len(b) <= limit_bytes:
                best = b
                low = q + 1
            else:
                high = q - 1

        if best is None:
            # не влізли — візьмемо найнижчу якість
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=25, optimize=True, progressive=True)
            best = buf.getvalue()
        return best if len(best) < len(data) else data
    except Exception:
        return data

def _classify_ext(ext_lower: str) -> str | None:
    if ext_lower in IMAGE_EXTS:
        return "image"
    if ext_lower in AUDIO_EXTS:
        return "audio"
    if ext_lower in VIDEO_EXTS:
        return "video"
    if ext_lower in DOC_EXTS:
        return "document"
    return None

def _next_index(counters: Dict[str, int], kind: str) -> int:
    counters[kind] = counters.get(kind, 0) + 1
    return counters[kind]

def _canonical_name(kind: str, idx: int, ext: str) -> str:
    base = {
        "image": "image",
        "audio": "audio",
        "video": "video",
        "document": "doc",
    }.get(kind, "file")
    return f"{base}{idx}{ext}"

def _clean_member_name(name: str) -> str:
    # нормалізуємо шлях усередині архіву
    return name.strip().replace("\\", "/").lstrip("./")

def _read_member_bytes(zf: zipfile.ZipFile, member) -> bytes:
    with zf.open(member, "r") as fp:
        return fp.read()

# --------- ГОЛОВНЕ: універсальна обробка архіву з медіа ---------

def _process_media_zip(zip_bytes: bytes, base_media_dir: str) -> Dict[str, int]:
    """
    Приймає архів із змішаним контентом (images, audio, video, documents),
    розкладає у `base_media_dir` з канонічними іменами:
      image{N}.*, audio{N}.*, video{N}.*, doc{N}.*
    Нумерація береться з назви файлу (перші цифри), або автоінкремент.
    Картинки стискаємо (якщо доступний Pillow).
    Повертає stats-словник.
    """
    stats = {
        "total": 0,
        "processed": 0,
        "skipped_nonmedia": 0,
        "errors": 0,
        "images": 0,
        "audio": 0,
        "video": 0,
        "docs": 0,
    }
    counters: Dict[str, int] = {"image": 0, "audio": 0, "video": 0, "document": 0}

    _ensure_dir(base_media_dir)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # стабільний порядок
        members = [m for m in zf.infolist() if not m.is_dir()]
        members.sort(key=lambda m: _clean_member_name(m.filename).lower())

        for m in members:
            stats["total"] += 1
            name = _clean_member_name(m.filename)
            stem, ext = os.path.splitext(os.path.basename(name))
            ext_low = ext.lower()

            kind = _classify_ext(ext_low)
            if not kind:
                stats["skipped_nonmedia"] += 1
                continue

            try:
                raw = _read_member_bytes(zf, m)

                # стиснення тільки для зображень
                if kind == "image":
                    raw = _compress_image_bytes(raw, IMG_TARGET_LIMIT)

                # номер з назви або авто
                idx = _extract_index_from_name(stem)
                if not idx or idx <= 0:
                    idx = _next_index(counters, kind)
                else:
                    # трекаємо максимум, щоб наступні без номерів не конфліктували
                    if idx > counters.get(kind, 0):
                        counters[kind] = idx

                out_name = _canonical_name(kind, idx, ext_low)
                out_path = os.path.join(base_media_dir, out_name)
                _write_bytes(out_path, raw)

                stats["processed"] += 1
                if kind == "image":
                    stats["images"] += 1
                elif kind == "audio":
                    stats["audio"] += 1
                elif kind == "video":
                    stats["video"] += 1
                elif kind == "document":
                    stats["docs"] += 1

            except Exception:
                stats["errors"] += 1

    return stats
