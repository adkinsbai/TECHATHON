"""本地存储：聊天记录、长期记忆、回忆片段、状态。全部存在 data/companion.db 里。"""
import json
import sqlite3
import time

from .config import DATA_DIR, ROOT

DB_PATH = DATA_DIR / "companion.db"
PERSONA_PATH = DATA_DIR / "persona.json"
DEFAULT_PERSONA_PATH = ROOT / "app" / "default_persona.json"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL, content TEXT NOT NULL,
                emotion TEXT, ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL, category TEXT DEFAULT 'fact',
                importance INTEGER DEFAULT 3, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS episodes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL, start_ts REAL, end_ts REAL);
            CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS diary(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity TEXT, content TEXT NOT NULL, ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS dreams(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, content TEXT NOT NULL, imagery TEXT, feelings TEXT,
                ts REAL NOT NULL, world_id INTEGER);
            CREATE TABLE IF NOT EXISTS worlds(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL, recipe TEXT NOT NULL, inspiration TEXT,
                created REAL NOT NULL, completed REAL);
            """
        )


# ---------- 状态 ----------
def get_state(key, default=None):
    with _conn() as c:
        row = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_state(key, value):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO state(key, value) VALUES(?, ?)",
                  (key, json.dumps(value, ensure_ascii=False)))


# ---------- 人设 ----------
def get_persona() -> dict:
    base = json.loads(DEFAULT_PERSONA_PATH.read_text(encoding="utf-8"))
    if PERSONA_PATH.exists():
        base.update(json.loads(PERSONA_PATH.read_text(encoding="utf-8")))
    return base


def save_persona(p: dict):
    PERSONA_PATH.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 消息 ----------
def add_message(role, content, emotion=None) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO messages(role, content, emotion, ts) VALUES(?,?,?,?)",
                        (role, content, emotion, time.time()))
        return cur.lastrowid


def recent_messages(limit=40):
    with _conn() as c:
        rows = c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]


def messages_after(msg_id):
    with _conn() as c:
        rows = c.execute("SELECT * FROM messages WHERE id > ? ORDER BY id", (msg_id,)).fetchall()
    return [dict(r) for r in rows]


def message_count():
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def first_message_ts():
    with _conn() as c:
        row = c.execute("SELECT MIN(ts) FROM messages").fetchone()
    return row[0]


def last_message():
    with _conn() as c:
        row = c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def clear_messages():
    with _conn() as c:
        c.execute("DELETE FROM messages")
    set_state("last_extracted_id", 0)


# ---------- 长期记忆 ----------
def list_memories():
    with _conn() as c:
        rows = c.execute("SELECT * FROM memories ORDER BY importance DESC, updated DESC").fetchall()
    return [dict(r) for r in rows]


def add_memory(content, category="fact", importance=3):
    now = time.time()
    with _conn() as c:
        c.execute("INSERT INTO memories(content, category, importance, created, updated) VALUES(?,?,?,?,?)",
                  (content, category, int(importance), now, now))


def update_memory(mem_id, content, importance=None):
    with _conn() as c:
        if importance is None:
            c.execute("UPDATE memories SET content=?, updated=? WHERE id=?", (content, time.time(), mem_id))
        else:
            c.execute("UPDATE memories SET content=?, importance=?, updated=? WHERE id=?",
                      (content, int(importance), time.time(), mem_id))


def delete_memory(mem_id):
    with _conn() as c:
        c.execute("DELETE FROM memories WHERE id=?", (mem_id,))


# ---------- 日记（TA 自己的内心生活） ----------
def add_diary(activity, content):
    with _conn() as c:
        c.execute("INSERT INTO diary(activity, content, ts) VALUES(?,?,?)", (activity, content, time.time()))


def list_diary(limit=50, since=None):
    with _conn() as c:
        if since is None:
            rows = c.execute("SELECT * FROM diary ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM diary WHERE ts > ? ORDER BY id DESC LIMIT ?", (since, limit)).fetchall()
    return [dict(r) for r in rows]


def last_user_ts():
    with _conn() as c:
        row = c.execute("SELECT MAX(ts) FROM messages WHERE role='user'").fetchone()
    return row[0]


# ---------- 梦境日记 ----------
def add_dream(content, title="", imagery=None, feelings=None, ts=None):
    with _conn() as c:
        cur = c.execute("INSERT INTO dreams(title, content, imagery, feelings, ts) VALUES(?,?,?,?,?)",
                        (title, content, json.dumps(imagery or [], ensure_ascii=False),
                         json.dumps(feelings or [], ensure_ascii=False), ts or time.time()))
        return cur.lastrowid


def list_dreams(limit=100, unused_only=False):
    q = "SELECT * FROM dreams" + (" WHERE world_id IS NULL" if unused_only else "") + " ORDER BY ts DESC LIMIT ?"
    with _conn() as c:
        rows = c.execute(q, (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["imagery"] = json.loads(d["imagery"] or "[]")
        d["feelings"] = json.loads(d["feelings"] or "[]")
        out.append(d)
    return out


def mark_dreams_used(ids, world_id):
    with _conn() as c:
        c.executemany("UPDATE dreams SET world_id=? WHERE id=?", [(world_id, i) for i in ids])


def delete_dream(dream_id):
    with _conn() as c:
        c.execute("DELETE FROM dreams WHERE id=?", (dream_id,))


# ---------- 编织出来的世界 ----------
def add_world(title, recipe, inspiration=""):
    with _conn() as c:
        cur = c.execute("INSERT INTO worlds(title, recipe, inspiration, created) VALUES(?,?,?,?)",
                        (title, json.dumps(recipe, ensure_ascii=False), inspiration, time.time()))
        return cur.lastrowid


def list_worlds():
    with _conn() as c:
        rows = c.execute("SELECT * FROM worlds ORDER BY id").fetchall()
    return [{**dict(r), "recipe": json.loads(r["recipe"])} for r in rows]


def get_world(world_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM worlds WHERE id=?", (world_id,)).fetchone()
    return {**dict(r), "recipe": json.loads(r["recipe"])} if r else None


def complete_world(world_id):
    with _conn() as c:
        c.execute("UPDATE worlds SET completed=? WHERE id=? AND completed IS NULL", (time.time(), world_id))


def delete_world(world_id):
    with _conn() as c:
        c.execute("DELETE FROM worlds WHERE id=?", (world_id,))
        c.execute("UPDATE dreams SET world_id=NULL WHERE world_id=?", (world_id,))


# ---------- 回忆片段 ----------
def add_episode(summary, start_ts, end_ts):
    with _conn() as c:
        c.execute("INSERT INTO episodes(summary, start_ts, end_ts) VALUES(?,?,?)", (summary, start_ts, end_ts))


def list_episodes():
    with _conn() as c:
        rows = c.execute("SELECT * FROM episodes ORDER BY end_ts DESC").fetchall()
    return [dict(r) for r in rows]


def delete_episode(ep_id):
    with _conn() as c:
        c.execute("DELETE FROM episodes WHERE id=?", (ep_id,))
