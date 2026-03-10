# -*- coding: utf-8 -*-
"""
Локальное хранилище SQLite: пользователи, путешествия, расходы, активное путешествие.
"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Tuple, Any
from contextlib import contextmanager

from config import DB_PATH


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Создаёт таблицы при первом запуске."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                from_currency TEXT NOT NULL,
                to_currency TEXT NOT NULL,
                rate REAL NOT NULL,
                balance_from REAL NOT NULL,
                balance_to REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                amount_to REAL NOT NULL,
                amount_from REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_trip (
                user_id INTEGER PRIMARY KEY,
                trip_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (trip_id) REFERENCES trips(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                state_data TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)


def ensure_user(user_id: int):
    """Создаёт пользователя, если его ещё нет."""
    from datetime import datetime
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)",
            (user_id, datetime.utcnow().isoformat()),
        )


def set_user_state(user_id: int, state: str, state_data: Optional[str] = None):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_state (user_id, state, state_data) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET state=?, state_data=?""",
            (user_id, state, state_data or "", state, state_data or ""),
        )


def get_user_state(user_id: int) -> Tuple[Optional[str], Optional[str]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT state, state_data FROM user_state WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None, None
    return row["state"], row["state_data"]


def clear_user_state(user_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM user_state WHERE user_id = ?", (user_id,))


def create_trip(
    user_id: int,
    name: str,
    from_currency: str,
    to_currency: str,
    rate: float,
    balance_from: float,
    balance_to: float,
) -> int:
    from datetime import datetime
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO trips (user_id, name, from_currency, to_currency, rate, balance_from, balance_to, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, from_currency, to_currency, rate, balance_from, balance_to, datetime.utcnow().isoformat()),
        )
        trip_id = cur.lastrowid
        conn.execute(
            "INSERT OR REPLACE INTO active_trip (user_id, trip_id) VALUES (?, ?)",
            (user_id, trip_id),
        )
    return trip_id


def get_trips(user_id: int) -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, from_currency, to_currency, rate, balance_from, balance_to FROM trips WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_trip(trip_id: int, user_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, from_currency, to_currency, rate, balance_from, balance_to FROM trips WHERE id = ? AND user_id = ?",
            (trip_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def get_active_trip(user_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT t.id, t.name, t.from_currency, t.to_currency, t.rate, t.balance_from, t.balance_to
               FROM trips t JOIN active_trip a ON t.id = a.trip_id WHERE a.user_id = ?""",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def set_active_trip(user_id: int, trip_id: int):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO active_trip (user_id, trip_id) VALUES (?, ?)",
            (user_id, trip_id),
        )


def add_expense(trip_id: int, amount_to: float, amount_from: float) -> bool:
    """Списывает сумму с баланса путешествия и записывает расход. Возвращает True при успехе."""
    from datetime import datetime
    with get_connection() as conn:
        trip = conn.execute("SELECT balance_from, balance_to FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if not trip or trip["balance_to"] < amount_to:
            return False
        conn.execute(
            "UPDATE trips SET balance_from = balance_from - ?, balance_to = balance_to - ? WHERE id = ?",
            (amount_from, amount_to, trip_id),
        )
        conn.execute(
            "INSERT INTO expenses (trip_id, amount_to, amount_from, created_at) VALUES (?, ?, ?, ?)",
            (trip_id, amount_to, amount_from, datetime.utcnow().isoformat()),
        )
    return True


def get_expenses(trip_id: int, limit: int = 50) -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, amount_to, amount_from, created_at FROM expenses WHERE trip_id = ? ORDER BY id DESC LIMIT ?",
            (trip_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def update_trip_rate(trip_id: int, user_id: int, new_rate: float) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE trips SET rate = ? WHERE id = ? AND user_id = ?",
            (new_rate, trip_id, user_id),
        )
        return cur.rowcount > 0
