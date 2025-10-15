import html
from typing import Dict, Any, Optional, Tuple, List

def _escape(s: str) -> str:
    return html.escape(s or "")

def _format_topics(topics: List[str]) -> str:
    """Рендер маленьких 'тегів' перед питанням."""
    if not topics:
        return ""
    chips = " ".join(f"<code>#{html.escape(t)}</code>" for t in topics[:10])
    return f"{chips}\n\n"

def _format_explanation(expl: str) -> str:
    if not expl:
        return ""
    return f"\n💡 <i>{_escape(expl)}</i>\n"

def format_question_text(
    q: Dict[str, Any],
    highlight: Optional[Tuple[int, bool]] = None,
    hide_correct_on_wrong: bool = False,
    show_correct_if_no_highlight: bool = False,
    *,
    mode: str = "testing",         # "testing" | "learning"
    show_topics: bool = True
) -> str:
    """
    Форматує текст питання з HTML розміткою.

    Параметри (беквард-сумісно з твоїм кодом):
      - highlight: (picked_index, picked_is_correct) або None
      - hide_correct_on_wrong: якщо True — при помилці не підсвічуємо правильну
      - show_correct_if_no_highlight: коли highlight=None, показати правильну (для пошуку/передперегляду)
      - mode: "testing" -> explanation показується після вибору;
              "learning" -> explanation показується завжди
      - show_topics: показувати topics над питанням
    """
    parts: List[str] = []

    # --- ТЕМИ (теги) ---
    topics = q.get("topics") if isinstance(q.get("topics"), list) else []
    if show_topics and topics:
        parts.append(_format_topics(topics))

    # --- ТЕКСТ ПИТАННЯ ---
    parts.append(f"<b>{_escape(q.get('question',''))}</b>\n\n")

    # --- ВАРІАНТИ ---
    letters = ["A", "B", "C", "D"]  # у тебе клавіатура під 4 варіанти
    picked_idx = None
    picked_is_correct = None
    if highlight is not None:
        picked_idx, picked_is_correct = highlight

    answers = q.get("answers", [])
    # Визначаємо індекс правильної відповіді (для формату [{text,correct}])
    correct_idx = None
    if isinstance(answers, list) and answers:
        for i, a in enumerate(answers[:len(letters)]):
            if isinstance(a, dict) and a.get("correct"):
                correct_idx = i
                break
    else:
        # альтернативні історичні формати (якщо раптом)
        correct_idx = q.get("answer")

    for i, a in enumerate(answers or []):
        if i >= len(letters):
            break

        # Витягуємо текст варіанту
        if isinstance(a, dict):
            ans_text = a.get("text") or a.get("answer") or a.get("value") or a.get("content") or ""
            if not isinstance(ans_text, str):
                ans_text = str(ans_text)
        else:
            ans_text = str(a)

        ans_text = _escape(ans_text)
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
            # Режим без вибору (наприклад, у пошуку/передперегляді)
            if show_correct_if_no_highlight and is_correct:
                bold = True
                emoji = "✅"

        prefix = f"{letters[i]}) "
        line = f"{emoji} <b>{prefix}{ans_text}</b>" if bold else f"{emoji} {prefix}{ans_text}"
        parts.append(line + "\n")

    # --- ПОЯСНЕННЯ ---
    explanation = q.get("explanation") or ""
    if explanation:
        if mode == "learning":
            # завжди у навчанні
            parts.append(_format_explanation(explanation))
        else:
            # у тестуванні — тільки після відповіді
            if highlight is not None:
                parts.append(_format_explanation(explanation))

    return "".join(parts)
