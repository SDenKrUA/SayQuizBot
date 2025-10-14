import html
from typing import Dict, Any, Optional, Tuple

def format_question_text(
    q: Dict[str, Any],
    highlight: Optional[Tuple[int, bool]] = None,
    hide_correct_on_wrong: bool = False,
    show_correct_if_no_highlight: bool = False
) -> str:
    """
    Форматує текст питання з HTML розміткою.

    Args:
        q: Словник з даними питання
        highlight: Кортеж (індекс обраної відповіді, чи правильна)
        hide_correct_on_wrong: Чи приховувати правильну відповідь при помилці
        show_correct_if_no_highlight: Якщо True і highlight=None — показувати правильну відповідь (виділяти жирним + ✅)

    Returns:
        Відформатований HTML текст
    """
    text = f"<b>{html.escape(q.get('question',''))}</b>\n\n"
    letters = ["A", "B", "C", "D"]

    picked_idx = None
    picked_is_correct = None
    if highlight is not None:
        picked_idx, picked_is_correct = highlight

    # Визначимо індекс правильної відповіді (для обох форматів)
    answers = q.get("answers", [])
    correct_idx = None
    if isinstance(answers, list) and answers:
        for i, a in enumerate(answers[:4]):
            if isinstance(a, dict) and a.get("correct"):
                correct_idx = i
                break
    else:
        # альтернативні формати
        correct_idx = q.get("answer")

    for i, a in enumerate(answers or []):
        if i >= len(letters):
            break

        letter = letters[i]
        # Витягнути текст відповіді
        if isinstance(a, dict):
            ans_text = a.get("text") or a.get("answer") or a.get("value") or a.get("content") or ""
            if not isinstance(ans_text, str):
                ans_text = str(ans_text)
        else:
            ans_text = str(a)

        ans_text = html.escape(ans_text)
        is_correct = (i == correct_idx)

        emoji = ""
        bold = False

        if highlight is not None:
            # Після вибору
            if is_correct:
                if not (hide_correct_on_wrong and not picked_is_correct):
                    bold = True
                    emoji = "✅"
            if i == picked_idx:
                emoji = "✅" if picked_is_correct else "❌"
                if not picked_is_correct:
                    bold = False
        else:
            # Режим без highlight (наприклад, показ з пошуку)
            if show_correct_if_no_highlight and is_correct:
                bold = True
                emoji = "✅"

        if bold:
            line = f"{emoji} <b>{letter}) {ans_text}</b>"
        else:
            line = f"{emoji} {letter}) {ans_text}"

        text += line + "\n\n"

    if highlight is not None and q.get("explanation"):
        text += f"\n💡 <i>{html.escape(q['explanation'])}</i>\n"

    return text
