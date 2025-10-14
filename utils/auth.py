import os
from typing import Set

# Fallback — твій ID як власника за замовчуванням
DEFAULT_OWNER_IDS = {5798500887}

def _parse_owner_ids(env_val: str) -> Set[int]:
    ids: Set[int] = set()
    for part in env_val.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            # ігноруємо некоректні
            pass
    return ids

def get_owner_ids() -> Set[int]:
    """
    Зчитує OWNER_IDS з .env (розділювач — кома), або повертає DEFAULT_OWNER_IDS.
    Приклад у .env: OWNER_IDS=5798500887,123456789
    """
    env_val = os.getenv("OWNER_IDS", "").strip()
    if env_val:
        parsed = _parse_owner_ids(env_val)
        if parsed:
            return parsed
    return set(DEFAULT_OWNER_IDS)

def is_owner(user_id: int) -> bool:
    return user_id in get_owner_ids()
