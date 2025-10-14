# handlers/vip_tests/vip_validation.py
"""
Валідатор структури VIP JSON тесту.

Крок 1 міграції під медіа:
- Дозволяємо додаткові поля питання: audio, video, document (рядки).
- Дозволяємо дублі "."
- Підтримуємо питання БЕЗ тексту, якщо є хоча б одне з медіаполів.
"""

from typing import Any, Dict, List, Tuple

ALLOWED_QUESTION_EXTRA_KEYS = {
    # існуюче
    "image",
    # нові опційні
    "audio",        # напр. "q12.mp3" (Telegram-friendly)
    "video",        # напр. "clip5.mp4"
    "document",     # напр. "ref12.pdf" або "task.docx"
    # технічні, якщо десь зʼявляються у пайплайні
    "caption",
}

def _err(idx: int, msg: str) -> Tuple[bool, str]:
    return False, f"Питання #{idx}: {msg}"

def _ok() -> Tuple[bool, str]:
    return True, "OK"

def _is_nonempty_str(x: Any) -> bool:
    return isinstance(x, str) and len(x.strip()) > 0

def _validate_answers(i: int, answers: Any) -> Tuple[bool, str]:
    if not isinstance(answers, list):
        return _err(i, "поле 'answers' має бути списком із 4 елементів.")
    if len(answers) != 4:
        return _err(i, "очікуються рівно 4 варіанти відповіді.")

    seen_texts = set()
    correct_count = 0

    for j, a in enumerate(answers, start=1):
        if not isinstance(a, dict):
            return _err(i, f"варіант #{j} має бути обʼєктом.")
        text = a.get("text")
        if not _is_nonempty_str(text):
            return _err(i, f"варіант #{j} має непорожній 'text' (рядок).")

        # Дублікати: дозволяємо лише крапки "." (та самі пробіли не рахуються)
        normalized = text.strip()
        if normalized != ".":  # крапки можна дублювати
            if normalized in seen_texts:
                return _err(i, "знайдено дублікати варіантів відповіді.")
            seen_texts.add(normalized)

        if bool(a.get("correct", False)):
            correct_count += 1

    if correct_count != 1:
        return _err(i, "має бути рівно один правильний варіант ('correct': true).")

    return _ok()

def _has_any_media(q: Dict[str, Any]) -> bool:
    return any(
        _is_nonempty_str(q.get(k))
        for k in ("image", "audio", "video", "document")
    )

def _validate_question(i: int, q: Any) -> Tuple[bool, str]:
    if not isinstance(q, dict):
        return _err(i, "питання має бути обʼєктом.")

    # Текст питання:
    q_text = q.get("question")
    has_media = _has_any_media(q)

    # Якщо НІ медіа — текст питання обовʼязковий (збережемо поточну логіку бекв.)
    # Якщо Є медіа — допускаємо пустий/відсутній question.
    if not has_media:
        if not _is_nonempty_str(q_text):
            return _err(i, "обовʼязкове поле 'question' (рядок) відсутнє або порожнє.")

    # Перевірка answers
    ok, msg = _validate_answers(i, q.get("answers"))
    if not ok:
        return False, msg

    # Перевірка типів додаткових ключів (якщо задані)
    for k in ("image", "audio", "video", "document", "caption"):
        if k in q and q[k] is not None and not isinstance(q[k], str):
            return _err(i, f"поле '{k}' має бути рядком.")

    return _ok()

def _validate_test_json(data: Any) -> Tuple[bool, str]:
    """
    Основна точка входу. Приймає `data` з json.loads() і повертає (ok, msg).
    """
    if not isinstance(data, list):
        return False, "Корінь файлу має бути списком питань."

    if not data:
        return False, "Список питань порожній."

    for i, q in enumerate(data, start=1):
        ok, msg = _validate_question(i, q)
        if not ok:
            return False, msg

    return True, "OK"
