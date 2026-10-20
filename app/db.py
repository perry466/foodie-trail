"""SQLite 初始化与连接管理"""
import os
import sqlite3
from contextlib import contextmanager

from .pathconf import DB_PATH, DATA_DIR, DB_VERSION


SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  lng             REAL NOT NULL,
  lat             REAL NOT NULL,
  rating          INTEGER NOT NULL DEFAULT 3 CHECK (rating BETWEEN 1 AND 5),
  tags            TEXT,                 -- JSON array
  business_hours  TEXT,
  avg_price       INTEGER,
  checkin_status  TEXT,                 -- 'want'|'visited'|'favorite'|NULL
  note            TEXT,
  draft           INTEGER NOT NULL DEFAULT 0,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_updated ON records(updated_at);
CREATE INDEX IF NOT EXISTS idx_records_rating  ON records(rating);
CREATE INDEX IF NOT EXISTS idx_records_avg     ON records(avg_price);
CREATE INDEX IF NOT EXISTS idx_records_checkin ON records(checkin_status);

CREATE TABLE IF NOT EXISTS photos (
  id          TEXT PRIMARY KEY,
  record_id   TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,
  thumb       TEXT,
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photos_record ON photos(record_id);

CREATE TABLE IF NOT EXISTS settings (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def init_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES('dbVersion', ?)",
            (str(DB_VERSION),),
        )
        # 一次性把老数据里的 `photos\x.jpg` 归一成 `photos/x.jpg`（幂等）。
        # 用 char(92) 表示反斜杠，避免 SQL 字符串里出现转义歧义。
        conn.execute("UPDATE photos SET path = replace(path, char(92), '/') "
                     "WHERE instr(path, char(92)) > 0")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
