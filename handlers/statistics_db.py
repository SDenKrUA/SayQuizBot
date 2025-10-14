import os
import json
import aiosqlite
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

# Константи
DB_FILENAME = os.path.join(os.path.dirname(__file__), "..", "stats.db")
JSON_BACKUP = os.path.join(os.path.dirname(__file__), "..", "user_stats.json")

# Глобальне асинхронне підключення
_db_connection: Optional[aiosqlite.Connection] = None

async def get_db_connection():
    """Повертає асинхронне підключення до БД"""
    global _db_connection
    if _db_connection is None:
        _db_connection = await aiosqlite.connect(DB_FILENAME)
        await _db_connection.execute("PRAGMA journal_mode=WAL;")
        await _db_connection.execute("PRAGMA synchronous=NORMAL;")
        await _db_connection.execute("PRAGMA foreign_keys=ON;")
    return _db_connection

# ===== Допоміжні утиліти для міграцій =====

async def _column_exists(conn: aiosqlite.Connection, table: str, column: str) -> bool:
    try:
        async with conn.execute(f"PRAGMA table_info({table});") as cur:
            rows = await cur.fetchall()
            return any(row[1] == column for row in rows)  # row[1] = name
    except Exception:
        return False

async def _ensure_column(conn: aiosqlite.Connection, table: str, column_def_sql: str):
    """
    Додає колонку, якщо її немає.
    column_def_sql: наприклад 'current_streak INTEGER DEFAULT 0'
    """
    col_name = column_def_sql.split()[0]
    exists = await _column_exists(conn, table, col_name)
    if not exists:
        try:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def_sql};")
            await conn.commit()
        except Exception:
            # Якщо одночасний доступ або стара SQLite без IF NOT EXISTS — ігноруємо
            pass

# ===== Ініціалізація / Міграції =====

async def init_db():
    """Асинхронне створення таблиць + міні-міграції"""
    conn = await get_db_connection()

    # Результати тестів
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS user_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        test_name TEXT NOT NULL,
        mode TEXT,
        score INTEGER,
        total_questions INTEGER,
        duration REAL,
        percent REAL,
        current_streak INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON user_results(user_id);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON user_results(created_at DESC);")

    # ⭐ Улюблені питання
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        test_name TEXT NOT NULL,
        q_index INTEGER,
        question_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_fav_user_id ON favorites(user_id);")

    # ❌ Неправильні відповіді (персональні списки помилок по тестах)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS wrong_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        test_name TEXT NOT NULL,
        q_index INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, test_name, q_index)
    );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_wrong_user ON wrong_answers(user_id);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_wrong_user_test ON wrong_answers(user_id, test_name);")

    await conn.commit()

    # ---------- МІНІ-МІГРАЦІЇ ----------
    # 1) Додати колонку current_streak у user_results, якщо відсутня
    await _ensure_column(conn, "user_results", "current_streak INTEGER DEFAULT 0")

async def migrate_from_json(json_path=JSON_BACKUP):
    """Асинхронна міграція зі старого JSON (залишаємо як було)"""
    if not os.path.exists(json_path):
        return {"migrated": 0, "note": "json not found"}
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"migrated": 0, "error": f"cannot read json: {e}"}

    migrated = 0
    conn = await get_db_connection()
    
    for user_key, results in data.items():
        try:
            user_id = int(user_key)
        except:
            user_id = None
        
        if not isinstance(results, list):
            continue
            
        for r in results:
            try:
                test_name = r.get("test_name") or "unknown"
                mode = r.get("mode") or None
                score = int(r.get("score")) if r.get("score") is not None else None
                total_questions = int(r.get("total_questions") or 0)
                duration = float(r.get("duration")) if r.get("duration") is not None else None
                percent = (score / total_questions * 100.0) if score and total_questions else None
                username = r.get("username") or None
                created_at = r.get("date") or None
                current_streak = int(r.get("current_streak", 0))

                await conn.execute("""
                    INSERT INTO user_results(user_id, username, test_name, mode, score, total_questions, duration, percent, current_streak, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """, (user_id, username, test_name, mode, score, total_questions, duration, percent, current_streak, created_at))
                migrated += 1
                if migrated % 100 == 0:
                    await conn.commit()
            except Exception as e:
                print(f"Error migrating record: {e}")
                continue
    
    await conn.commit()
    try:
        os.rename(json_path, json_path + ".bak")
    except Exception as e:
        print(f"Error creating backup: {e}")
    
    return {"migrated": migrated}

# ===== Збереження результатів =====

async def save_user_result_db(
    user_id: int, 
    test_name: str, 
    mode: str, 
    score: int, 
    total_questions: int, 
    duration: float = None, 
    percent: float = None, 
    username: str = None,
    current_streak: int = 0
) -> int:
    """Зберігає результат тесту"""
    if percent is None and score is not None and total_questions:
        try:
            percent = (score / total_questions) * 100.0
        except Exception:
            percent = None

    try:
        conn = await get_db_connection()
        cursor = await conn.execute("""
            INSERT INTO user_results(user_id, username, test_name, mode, score, total_questions, duration, percent, current_streak)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, test_name, mode, score, total_questions, duration, percent, current_streak))
        
        last_id = cursor.lastrowid
        await conn.commit()
        return last_id
    except Exception as e:
        print(f"Error saving user result: {e}")
        return -1

async def get_user_results(user_id: int, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Отримати результати користувача"""
    try:
        conn = await get_db_connection()
        async with conn.execute("""
            SELECT id, user_id, username, test_name, mode, score, total_questions, duration, percent, current_streak, created_at
            FROM user_results
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "username": row[2],
                    "test_name": row[3],
                    "mode": row[4],
                    "score": row[5],
                    "total_questions": row[6],
                    "duration": row[7],
                    "percent": row[8],
                    "current_streak": row[9],
                    "created_at": row[10]
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Error getting user results: {e}")
        return []

async def get_latest_results(limit: int = 100) -> List[Dict[str, Any]]:
    """Отримати останні результати всіх"""
    try:
        conn = await get_db_connection()
        async with conn.execute("""
            SELECT id, user_id, username, test_name, mode, score, total_questions, duration, percent, current_streak, created_at
            FROM user_results
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "username": row[2],
                    "test_name": row[3],
                    "mode": row[4],
                    "score": row[5],
                    "total_questions": row[6],
                    "duration": row[7],
                    "percent": row[8],
                    "current_streak": row[9],
                    "created_at": row[10]
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Error getting latest results: {e}")
        return []

# ===== ⭐ Favorites =====

async def save_favorite_db(user_id: int, username: str, test_name: str, q_index: int, question_text: str):
    """Зберегти улюблене питання (із захистом від дублікатів)"""
    try:
        conn = await get_db_connection()
        # Перевірка на дубль
        async with conn.execute("""
            SELECT 1 FROM favorites WHERE user_id=? AND test_name=? AND q_index=? LIMIT 1
        """, (user_id, test_name, q_index)) as cursor:
            row = await cursor.fetchone()
            if row:
                return  # вже існує

        await conn.execute("""
            INSERT INTO favorites(user_id, username, test_name, q_index, question_text)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, test_name, q_index, question_text))
        await conn.commit()
    except Exception as e:
        print(f"Error saving favorite: {e}")

async def delete_favorite_db(user_id: int, test_name: str, q_index: int):
    """Видалити питання з улюблених"""
    try:
        conn = await get_db_connection()
        await conn.execute("""
            DELETE FROM favorites WHERE user_id=? AND test_name=? AND q_index=?
        """, (user_id, test_name, q_index))
        await conn.commit()
    except Exception as e:
        print(f"Error deleting favorite: {e}")

async def delete_all_favorites(user_id: int) -> int:
    """Видалити ВСІ улюблені питання користувача (по всіх тестах). Повертає кількість видалених рядків."""
    try:
        conn = await get_db_connection()
        cursor = await conn.execute("DELETE FROM favorites WHERE user_id=?", (user_id,))
        await conn.commit()
        count = cursor.rowcount if cursor and cursor.rowcount is not None else 0
        return max(count, 0)
    except Exception as e:
        print(f"Error deleting all favorites: {e}")
        return 0

async def get_user_favorites(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Отримати улюблені питання користувача (усі тести)"""
    try:
        conn = await get_db_connection()
        async with conn.execute("""
            SELECT id, test_name, q_index, question_text, created_at
            FROM favorites
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "test_name": row[1],
                    "q_index": row[2],
                    "question": row[3],
                    "created_at": row[4]
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Error getting favorites: {e}")
        return []

async def get_user_favorites_by_test(user_id: int, test_name: str, limit: int = 10000) -> List[Dict[str, Any]]:
    """Отримати улюблені питання користувача конкретного тесту"""
    try:
        conn = await get_db_connection()
        async with conn.execute("""
            SELECT id, test_name, q_index, question_text, created_at
            FROM favorites
            WHERE user_id = ? AND test_name = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, test_name, limit)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "test_name": row[1],
                    "q_index": row[2],
                    "question": row[3],
                    "created_at": row[4]
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Error getting favorites by test: {e}")
        return []

async def get_favorite_counts_by_test(user_id: int) -> List[Dict[str, Any]]:
    """Повертає кількість улюблених по кожному тесту для користувача"""
    try:
        conn = await get_db_connection()
        async with conn.execute("""
            SELECT test_name, COUNT(*) as cnt
            FROM favorites
            WHERE user_id = ?
            GROUP BY test_name
            ORDER BY test_name
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [{"test_name": row[0], "count": row[1]} for row in rows]
    except Exception as e:
        print(f"Error getting favorite counts: {e}")
        return []

# ===== ❌ Wrong answers (нове) =====

async def add_wrong_answer(user_id: int, test_name: str, q_index: int) -> None:
    """
    Додати питання до списку «мої помилки» для користувача/тесту.
    Унікальність на (user_id, test_name, q_index) — дублікати ігноруються.
    """
    try:
        conn = await get_db_connection()
        await conn.execute("""
            INSERT OR IGNORE INTO wrong_answers(user_id, test_name, q_index)
            VALUES (?, ?, ?)
        """, (user_id, test_name, q_index))
        await conn.commit()
    except Exception as e:
        print(f"Error adding wrong answer: {e}")

async def get_wrong_counts_by_test(user_id: int) -> List[Dict[str, Any]]:
    """
    Повертає [{'test_name': str, 'count': int}, ...] — скільки помилкових питань у кожному тесті.
    """
    try:
        conn = await get_db_connection()
        async with conn.execute("""
            SELECT test_name, COUNT(*) AS cnt
            FROM wrong_answers
            WHERE user_id = ?
            GROUP BY test_name
            ORDER BY test_name
        """, (user_id,)) as cur:
            rows = await cur.fetchall()
            return [{"test_name": r[0], "count": r[1]} for r in rows]
    except Exception as e:
        print(f"Error getting wrong counts: {e}")
        return []

async def get_wrong_indices_by_test(user_id: int, test_name: str) -> List[int]:
    """Повертає відсортований список індексів питань зі списку помилок для вказаного тесту."""
    try:
        conn = await get_db_connection()
        async with conn.execute("""
            SELECT q_index
            FROM wrong_answers
            WHERE user_id = ? AND test_name = ?
            ORDER BY q_index
        """, (user_id, test_name)) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]
    except Exception as e:
        print(f"Error getting wrong indices by test: {e}")
        return []

async def clear_wrong_for_test(user_id: int, test_name: str) -> int:
    """Видалити всі записи помилок користувача для конкретного тесту. Повертає кількість видалених рядків."""
    try:
        conn = await get_db_connection()
        cur = await conn.execute("""
            DELETE FROM wrong_answers
            WHERE user_id = ? AND test_name = ?
        """, (user_id, test_name))
        await conn.commit()
        return cur.rowcount or 0
    except Exception as e:
        print(f"Error clearing wrong answers: {e}")
        return 0

# ===== Очищення всієї статистики =====

async def delete_all_results(user_id: int) -> int:
    """
    Видалити ВСІ результати користувача з таблиці user_results.
    Повертає кількість видалених рядків.
    """
    try:
        conn = await get_db_connection()
        cursor = await conn.execute("DELETE FROM user_results WHERE user_id=?", (user_id,))
        await conn.commit()
        count = cursor.rowcount if cursor and cursor.rowcount is not None else 0
        return max(count, 0)
    except Exception as e:
        print(f"Error deleting all results: {e}")
        return 0

# ===== Закриття / Ініціалізація =====

async def close_db_connection():
    """Закрити з’єднання з БД"""
    global _db_connection
    if _db_connection:
        await _db_connection.close()
        _db_connection = None

async def initialize_database():
    """Ініціалізація БД при запуску бота"""
    try:
        await init_db()
        if os.path.exists(JSON_BACKUP):
            result = await migrate_from_json(JSON_BACKUP)
            print(f"Migrated {result.get('migrated', 0)} records from JSON")
    except Exception as e:
        print(f"Database initialization error: {e}")
