# -*- coding: utf-8 -*-
"""数据健康检查（**只读**，不会写入或修改任何东西）。

用途：随时确认「库没坏、照片没丢、没有脏数据、没有混进演示数据」。
默认检查项目下的 data/；用 `--data-dir` 或环境变量 FOODMAP_DATA_DIR 指向别处。

用法：
    python health_check.py
    python health_check.py --deep                 # 额外逐张解码验证 JPEG
    python health_check.py --data-dir D:\\tmp\\fm-data

退出码：0 = 没有致命问题（可能有警告）；1 = 发现需要处理的问题；2 = 指定目录不存在。
"""
import argparse
import json
import os
import sqlite3
import sys

MIN_TS_MS = 946_684_800_000
MAX_TS_MS = 4_102_444_800_000
DEMO_PREFIX = "demo-"

ERRORS = []
WARNINGS = []
NOTES = []


def err(msg):
    ERRORS.append(msg)


def warn(msg):
    WARNINGS.append(msg)


def note(msg):
    NOTES.append(msg)


def check_db(db_path, deep=False):
    if not os.path.isfile(db_path):
        err(f"数据库不存在：{db_path}（全新安装时属正常，随便记一条就会创建）")
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        err(f"打不开数据库：{e}")
        return

    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        (note if integrity == "ok" else err)(f"integrity_check = {integrity}")

        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = {"records", "photos", "settings", "meta"} - tables
        if missing:
            err(f"缺少数据表：{sorted(missing)}")
            return

        total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        drafts = conn.execute("SELECT COUNT(*) FROM records WHERE draft=1").fetchone()[0]
        photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        note(f"记录 {total} 条（草稿 {drafts}），照片行 {photos} 条")

        # ---- 脏字段：任何一条越界都说明有外部写入绕过了校验 ----
        bad = []
        for r in conn.execute("SELECT id,name,lng,lat,rating,avg_price,checkin_status,"
                              "tags,created_at,updated_at FROM records"):
            problems = []
            if not (r["name"] or "").strip():
                problems.append("空店名")
            if r["lng"] is None or not (-180 <= r["lng"] <= 180):
                problems.append("经度越界")
            if r["lat"] is None or not (-90 <= r["lat"] <= 90):
                problems.append("纬度越界")
            if not (isinstance(r["rating"], int) and 1 <= r["rating"] <= 5):
                problems.append("星级越界")
            if r["avg_price"] is not None and not (0 <= r["avg_price"] <= 100000):
                problems.append("人均越界")
            if r["checkin_status"] not in (None, "want", "visited", "favorite"):
                problems.append("打卡状态非法")
            try:
                tags = json.loads(r["tags"]) if r["tags"] else []
                if not isinstance(tags, list):
                    problems.append("tags 非数组")
            except ValueError:
                problems.append("tags 不是 JSON")
            for key in ("created_at", "updated_at"):
                if not (MIN_TS_MS <= (r[key] or 0) <= MAX_TS_MS):
                    problems.append(f"{key} 时间戳异常")
            if problems:
                bad.append((r["id"], problems))
        if bad:
            err(f"有 {len(bad)} 条记录字段异常，例：{bad[:3]}")
        else:
            note("所有记录字段都在合法范围内")

        # ---- 照片：库里有行但文件没了 = 数据丢失 ----
        photos_dir = os.path.join(os.path.dirname(db_path), "photos")
        rows = conn.execute("SELECT id,record_id,path FROM photos").fetchall()
        referenced = set()
        missing_files = []
        empty_files = []
        for r in rows:
            rel = (r["path"] or "").replace("\\", "/")
            full = os.path.realpath(os.path.join(os.path.dirname(db_path), rel))
            referenced.add(os.path.normcase(full))
            if not os.path.isfile(full):
                missing_files.append(rel)
            elif os.path.getsize(full) == 0:
                empty_files.append(rel)
            elif deep:
                try:
                    from PIL import Image
                    with Image.open(full) as im:
                        im.verify()
                except Exception as e:
                    err(f"照片损坏无法解码：{rel}（{type(e).__name__}）")
        if missing_files:
            err(f"{len(missing_files)} 张照片的记录还在但文件丢失，例：{missing_files[:3]}")
        if empty_files:
            err(f"{len(empty_files)} 张照片文件是 0 字节，例：{empty_files[:3]}")
        if not missing_files and not empty_files:
            note(f"{len(rows)} 张照片文件齐全" + ("，且都能解码" if deep else ""))

        orphans = []
        if os.path.isdir(photos_dir):
            for name in os.listdir(photos_dir):
                full = os.path.join(photos_dir, name)
                if not os.path.isfile(full):
                    continue
                if name.startswith("."):          # 导入暂存文件由后端定期清理
                    continue
                if os.path.normcase(os.path.realpath(full)) not in referenced:
                    orphans.append(name)
        if orphans:
            warn(f"{len(orphans)} 个照片文件在磁盘上但没有记录引用（多为删除残留，可忽略），例：{orphans[:3]}")
        else:
            note("没有孤儿照片文件")

        # ---- 演示数据指纹 ----
        demo = conn.execute("SELECT COUNT(*) FROM records WHERE id LIKE ?",
                            (DEMO_PREFIX + "%",)).fetchone()[0]
        if demo:
            warn(f"库里有 {demo} 条演示数据（id 前缀 {DEMO_PREFIX}），确认不想保留可执行："
                 f"python seed_demo.py --clear --yes")
        else:
            note("没有演示数据")
    except sqlite3.Error as e:
        err(f"查询失败：{e}")
    finally:
        conn.close()


def check_key_file(db_path):
    key_path = os.path.join(os.path.dirname(db_path), ".fernet.key")
    if not os.path.isfile(key_path):
        warn("没有 .fernet.key（还没保存过高德 Key 时属正常）")
        return
    try:
        from cryptography.fernet import Fernet
        with open(key_path, "rb") as f:
            Fernet(f.read().strip())
        note(".fernet.key 可用")
    except Exception:
        err(".fernet.key 已损坏；下次启动会自动留档并换新（已存的高德 Key 需重填）")


def check_wal(db_path):
    wal = db_path + "-wal"
    if os.path.isfile(wal):
        mb = os.path.getsize(wal) / 1048576
        (warn if mb > 50 else note)(f"WAL 文件 {mb:.1f} MB")
    else:
        note("没有未合并的 WAL")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="数据健康检查（只读）")
    ap.add_argument("--data-dir", default="", help="数据目录，默认 FOODMAP_DATA_DIR 或项目 data/")
    ap.add_argument("--deep", action="store_true", help="逐张解码验证照片")
    args = ap.parse_args(argv)

    # 进程内可能被多次调用（测试/脚本复用），每次从零开始收集
    ERRORS.clear()
    WARNINGS.clear()
    NOTES.clear()

    data_dir = os.path.abspath(args.data_dir or os.environ.get("FOODMAP_DATA_DIR")
                               or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    print(f"[health] 检查目录：{data_dir}")
    if not os.path.isdir(data_dir):
        print("[health] 目录不存在。全新安装时属正常。")
        return 2

    db_path = os.path.join(data_dir, "foodmap.db")
    check_db(db_path, deep=args.deep)
    if os.path.isfile(db_path):
        check_key_file(db_path)
        check_wal(db_path)

    for m in NOTES:
        print("  ok   " + m)
    for m in WARNINGS:
        print("  warn " + m)
    for m in ERRORS:
        print("  FAIL " + m)
    print(f"\n[health] {len(NOTES)} 项正常 / {len(WARNINGS)} 项警告 / {len(ERRORS)} 项问题")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
