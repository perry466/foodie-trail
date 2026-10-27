# -*- coding: utf-8 -*-
"""并发写回归：任何一条记录都不能静默丢掉。

背景：`get_conn()` 曾经**每次连接**都执行 `PRAGMA journal_mode=WAL`。
两个连接同时切换日志模式会互相踩，报 `attempt to write a readonly database`
——错误信息还误导成"数据库只读"。实测 8 线程并发写 160 条会丢 7 条。

WAL 是写进数据库文件头的**持久**属性，只在 `init_db()` 里设一次即可。
这类问题单线程测试永远发现不了，所以单独守一条。
"""
import threading
import time
import uuid

from app.db import get_conn
from app.repository import SQLiteRepository


def _payload(name):
    ts = int(time.time() * 1000)
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "lng": 116.4,
        "lat": 39.9,
        "rating": 4,
        "createdAt": ts,
        "updatedAt": ts,
    }


def test_concurrent_writes_do_not_lose_records():
    repo = SQLiteRepository()
    errors = []
    threads_n, per_thread = 8, 10

    def writer(idx):
        for j in range(per_thread):
            try:
                repo.create(_payload(f"并发{idx}-{j}"))
            except Exception as e:  # noqa: BLE001 - 失败原因要原样带出来
                errors.append(f"{type(e).__name__}: {e}")

    workers = [threading.Thread(target=writer, args=(i,)) for i in range(threads_n)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()

    assert not errors, f"并发写出现 {len(errors)} 个错误：{errors[:3]}"
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    assert count == threads_n * per_thread, f"期望 {threads_n * per_thread} 条，实际 {count} 条"


def test_reads_keep_working_while_writing():
    """写的同时读不能被拖垮或报错（WAL 下读不阻塞写，写不阻塞读）。"""
    repo = SQLiteRepository()
    errors = []
    reads = [0]
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                repo.list({}, [("updatedAt", "desc")], 50)
                reads[0] += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"read {type(e).__name__}: {e}")
                return

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for i in range(40):
            repo.create(_payload(f"混合{i}"))
    finally:
        time.sleep(0.2)
        stop.set()
        thread.join()

    assert not errors, f"读写混合出错：{errors[:3]}"
    assert reads[0] > 0, "读线程一次都没查询成功"
