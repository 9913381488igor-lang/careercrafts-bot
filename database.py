import sqlite3
from typing import Optional


class Database:
    def __init__(self, db_path: str = "users.db"):
        self.db_path = db_path
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id   INTEGER PRIMARY KEY,
                    name      TEXT,
                    category  TEXT,
                    salary    TEXT,
                    format    TEXT,
                    active    INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_jobs (
                    user_id INTEGER,
                    job_id  TEXT,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, job_id)
                )
            """)
            conn.commit()

    def save_user(self, user_id: int, data: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO users (user_id, name, category, salary, format, active)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(user_id) DO UPDATE SET
                    name=excluded.name, category=excluded.category,
                    salary=excluded.salary, format=excluded.format, active=1
            """, (user_id, data.get("name",""), data["category"], data["salary"], data["format"]))
            conn.commit()

    def get_user(self, user_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id, name, category, salary, format, active FROM users WHERE user_id=?",
                (user_id,)
            ).fetchone()
        if not row:
            return None
        return {"user_id": row[0], "name": row[1], "category": row[2],
                "salary": row[3], "format": row[4], "active": bool(row[5])}

    def get_all_active_users(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT user_id, name, category, salary, format FROM users WHERE active=1"
            ).fetchall()
        return [{"user_id": r[0], "name": r[1], "category": r[2],
                 "salary": r[3], "format": r[4]} for r in rows]

    def set_active(self, user_id: int, active: bool):
        with self._conn() as conn:
            conn.execute("UPDATE users SET active=? WHERE user_id=?", (int(active), user_id))
            conn.commit()

    def filter_new_jobs(self, user_id: int, jobs: list) -> list:
        if not jobs:
            return []
        with self._conn() as conn:
            sent = {row[0] for row in conn.execute(
                "SELECT job_id FROM sent_jobs WHERE user_id=?", (user_id,)
            ).fetchall()}
        return [j for j in jobs if j["id"] not in sent]

    def mark_job_sent(self, user_id: int, job_id: str):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO sent_jobs (user_id, job_id) VALUES (?, ?)",
                         (user_id, job_id))
            conn.commit()
