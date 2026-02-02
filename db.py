import sqlite3
from contextlib import contextmanager
from typing import Optional, List, Dict

DB_PATH = "birthdays.sqlite3"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS birthdays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                day INTEGER NOT NULL,
                month INTEGER NOT NULL,
                year INTEGER,
                last_notified_year INTEGER,
                UNIQUE(user_id, name COLLATE NOCASE)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_birthdays_user ON birthdays(user_id);")


def upsert_birthday(user_id: int, name: str, day: int, month: int, year: Optional[int]) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO birthdays(user_id, name, day, month, year, last_notified_year)
            VALUES (?, ?, ?, ?, ?, NULL)
            ON CONFLICT(user_id, name) DO UPDATE SET
                day=excluded.day,
                month=excluded.month,
                year=excluded.year,
                last_notified_year=NULL;
            """,
            (user_id, name, day, month, year),
        )


def delete_birthday(user_id: int, name: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM birthdays WHERE user_id=? AND name=? COLLATE NOCASE;",
            (user_id, name),
        )
        return cur.rowcount


def list_birthdays(user_id: int) -> List[Dict]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT name, day, month, year
            FROM birthdays
            WHERE user_id=?
            ORDER BY month, day, LOWER(name);
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    return [
        {"name": r[0], "day": int(r[1]), "month": int(r[2]), "year": (int(r[3]) if r[3] is not None else None)}
        for r in rows
    ]


def get_all_users() -> List[int]:
    with get_conn() as conn:
        cur = conn.execute("SELECT DISTINCT user_id FROM birthdays;")
        return [int(r[0]) for r in cur.fetchall()]


def get_birthdays_for_user(user_id: int) -> List[Dict]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT id, name, day, month, year, last_notified_year
            FROM birthdays
            WHERE user_id=?;
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": int(r[0]),
            "name": r[1],
            "day": int(r[2]),
            "month": int(r[3]),
            "year": (int(r[4]) if r[4] is not None else None),
            "last_notified_year": (int(r[5]) if r[5] is not None else None),
        }
        for r in rows
    ]


def set_last_notified_year(birthday_id: int, year: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE birthdays SET last_notified_year=? WHERE id=?;",
            (year, birthday_id),
        )
