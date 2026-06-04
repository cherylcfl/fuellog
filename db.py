import sqlite3
import os
from datetime import date

DB_PATH = os.environ.get("DB_PATH", "fuelbot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            food_name   TEXT NOT NULL,
            calories    REAL DEFAULT 0,
            protein     REAL DEFAULT 0,
            carbs       REAL DEFAULT 0,
            fat         REAL DEFAULT 0,
            logged_date TEXT NOT NULL,
            logged_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS workouts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            description     TEXT NOT NULL,
            calories_burned REAL DEFAULT 0,
            source          TEXT DEFAULT 'manual',
            logged_date     TEXT NOT NULL,
            logged_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id         INTEGER PRIMARY KEY,
            oura_token      TEXT,
            first_seen      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def _upsert_user(user_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (user_id) VALUES (?)
        ON CONFLICT(user_id) DO UPDATE SET last_active = CURRENT_TIMESTAMP
    """, (user_id,))
    conn.commit()
    conn.close()


def log_meal(user_id: int, meal: dict):
    _upsert_user(user_id)
    today = date.today().isoformat()
    conn = get_conn()
    conn.execute("""
        INSERT INTO meals (user_id, food_name, calories, protein, carbs, fat, logged_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        meal["food_name"],
        meal.get("calories", 0),
        meal.get("protein", 0),
        meal.get("carbs", 0),
        meal.get("fat", 0),
        today,
    ))
    conn.commit()
    conn.close()


def log_workout(user_id: int, description: str, calories_burned: float, source: str = "manual"):
    _upsert_user(user_id)
    today = date.today().isoformat()
    conn = get_conn()
    # Remove existing Oura entry for today if syncing fresh
    if source == "oura":
        conn.execute(
            "DELETE FROM workouts WHERE user_id = ? AND logged_date = ? AND source = 'oura'",
            (user_id, today)
        )
    conn.execute("""
        INSERT INTO workouts (user_id, description, calories_burned, source, logged_date)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, description, calories_burned, source, today))
    conn.commit()
    conn.close()


def get_today_meals(user_id: int) -> list:
    today = date.today().isoformat()
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM meals WHERE user_id = ? AND logged_date = ?
        ORDER BY logged_at ASC
    """, (user_id, today)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_workouts(user_id: int) -> list:
    today = date.today().isoformat()
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM workouts WHERE user_id = ? AND logged_date = ?
        ORDER BY logged_at ASC
    """, (user_id, today)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_totals(user_id: int) -> dict:
    today = date.today().isoformat()
    conn = get_conn()
    food = conn.execute("""
        SELECT
            COALESCE(SUM(calories), 0) AS calories,
            COALESCE(SUM(protein),  0) AS protein,
            COALESCE(SUM(carbs),    0) AS carbs,
            COALESCE(SUM(fat),      0) AS fat
        FROM meals WHERE user_id = ? AND logged_date = ?
    """, (user_id, today)).fetchone()
    burned = conn.execute("""
        SELECT COALESCE(SUM(calories_burned), 0) AS burned
        FROM workouts WHERE user_id = ? AND logged_date = ?
    """, (user_id, today)).fetchone()
    conn.close()
    return {
        "calories": food["calories"],
        "protein": food["protein"],
        "carbs": food["carbs"],
        "fat": food["fat"],
        "burned": burned["burned"],
        "net_calories": food["calories"] - burned["burned"],
    }


def undo_last_meal(user_id: int) -> str | None:
    today = date.today().isoformat()
    conn = get_conn()
    row = conn.execute("""
        SELECT id, food_name FROM meals
        WHERE user_id = ? AND logged_date = ?
        ORDER BY logged_at DESC LIMIT 1
    """, (user_id, today)).fetchone()
    if row:
        conn.execute("DELETE FROM meals WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()
        return row["food_name"]
    conn.close()
    return None


def undo_last_workout(user_id: int) -> str | None:
    today = date.today().isoformat()
    conn = get_conn()
    row = conn.execute("""
        SELECT id, description FROM workouts
        WHERE user_id = ? AND logged_date = ? AND source = 'manual'
        ORDER BY logged_at DESC LIMIT 1
    """, (user_id, today)).fetchone()
    if row:
        conn.execute("DELETE FROM workouts WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()
        return row["description"]
    conn.close()
    return None


def clear_today(user_id: int):
    today = date.today().isoformat()
    conn = get_conn()
    conn.execute("DELETE FROM meals WHERE user_id = ? AND logged_date = ?", (user_id, today))
    conn.execute("DELETE FROM workouts WHERE user_id = ? AND logged_date = ?", (user_id, today))
    conn.commit()
    conn.close()


def save_oura_token(user_id: int, token: str):
    _upsert_user(user_id)
    conn = get_conn()
    conn.execute("UPDATE users SET oura_token = ? WHERE user_id = ?", (token, user_id))
    conn.commit()
    conn.close()


def get_oura_token(user_id: int) -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT oura_token FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row["oura_token"] if row else None


def get_all_active_users() -> list[int]:
    conn = get_conn()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]
