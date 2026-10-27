"""SQLite 初始化与连接管理"""
import os
import sqlite3
from contextlib import contextmanager

from .pathconf import DATA_DIR, DB_PATH, DB_VERSION

# 常驻的守卫连接：只为保住 WAL 的共享内存文件，不参与任何业务读写。
_KEEPER = None


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
        # WAL 是写进数据库文件头的**持久**属性，设一次就永久有效，新连接不需要再设。
        # 以前这一句放在 get_conn() 里（每次连接都执行）：两个连接同时切换日志模式会互相踩，
        # 报 "attempt to write a readonly database"——错误信息还误导成只读。
        # 实测 8 线程并发写 160 条会静默丢 7 条；移到这里后 160/160 全成功。
        # （tests/test_concurrency.py 守着这条回归。）
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES('dbVersion', ?)",
            (str(DB_VERSION),),
        )
        # 一次性把老数据里的 `photos\x.jpg` 归一成 `photos/x.jpg`（幂等）。
        # 用 char(92) 表示反斜杠，避免 SQL 字符串里出现转义歧义。
        conn.execute("UPDATE photos SET path = replace(path, char(92), '/') "
                     "WHERE instr(path, char(92)) > 0")

    _keep_wal_alive()


def _keep_wal_alive() -> None:
    """保住一条常驻连接，别让 WAL 的 -shm 文件被删掉。

    Windows 上 WAL 依赖共享内存文件（`-shm`）。**最后一个连接关闭时** SQLite 会把它
    删掉；如果此时另一个线程正好在开新连接并写入，就会拿到 SQLITE_READONLY，报
    「attempt to write a readonly database」——错误信息还误导成"库是只读的"。

    实测（8 线程并发写 160 条，3 轮）：不保连接时偶发丢 1 条；保住之后 3 轮全通过。
    单用户日常使用很难撞上，但「批量操作 + 自动保存」同时发生时会丢记录，所以修掉。

    这条连接不读业务数据、不开事务，不影响 checkpoint。
    """
    global _KEEPER
    if _KEEPER is None:
        _KEEPER = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        _KEEPER.row_factory = sqlite3.Row
        _KEEPER.execute("PRAGMA journal_mode=WAL")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)   # timeout 即 busy_timeout（30s）
    conn.row_factory = sqlite3.Row
    # 不要在这里设 journal_mode：见 init_db() 的注释，并发下会丢写。
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
