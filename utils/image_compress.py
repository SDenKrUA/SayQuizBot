import os
import io
import shutil

# Спроба підключити Pillow
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


def compress_image_file_to_limit_sync(src_path: str, dest_path: str, limit_bytes: int) -> bool:
    """
    Синхронне стиснення зображення до ліміту.
    - Якщо Pillow доступний: конверт у JPEG, поступове зниження якості + ресайз.
    - Якщо Pillow недоступний: просто копіюємо файл як є (повернемо True/False залежно від розміру).
    """
    if not PIL_AVAILABLE:
        # Fallback без Pillow: просто копіюємо
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copyfile(src_path, dest_path)
        try:
            return os.path.getsize(dest_path) <= limit_bytes
        except Exception:
            return False

    try:
        img = Image.open(src_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        max_side = max(img.size)
        if max_side > 1000:
            scale = 1000.0 / max_side
            new_size = (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale)))
            img = img.resize(new_size, Image.LANCZOS)

        qualities = [85, 75, 65, 55, 45, 35, 30, 25, 20, 18, 16, 14, 12, 10]
        best_buf = None
        best_size = None
        cur_img = img
        width, height = cur_img.size

        while True:
            for q in qualities:
                buf = io.BytesIO()
                cur_img.save(buf, format="JPEG", quality=q, optimize=True, progressive=True)
                data = buf.getvalue()
                size = len(data)

                if best_size is None or size < best_size:
                    best_size = size
                    best_buf = data

                if size <= limit_bytes:
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(dest_path, "wb") as f:
                        f.write(data)
                    return True

            if width <= 60 or height <= 60:
                break
            width = max(1, int(width * 0.85))
            height = max(1, int(height * 0.85))
            cur_img = cur_img.resize((width, height), Image.LANCZOS)

        if best_buf:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(best_buf)
            return len(best_buf) <= limit_bytes

        return False
    except Exception:
        return False
