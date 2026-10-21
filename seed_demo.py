# -*- coding: utf-8 -*-
"""生成演示数据（默认 100 条），直接写入本地 SQLite，不经过 API。

特点：
- 记录 id 统一以 `demo-` 开头，`--clear` 只删这些，绝不碰真实记录；
- 店名/城市/标签/价位/状态/录入时间都有分布，看板与筛选都能看出效果；
- 固定随机种子，重复执行结果可复现（--seed 可改）。

用法：
    python seed_demo.py --count 100
    python seed_demo.py --clear
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

from app.db import get_conn, init_db
from app.pathconf import DATA_DIR, PHOTOS_DIR
from app.repository import SQLiteRepository

DEMO_PREFIX = "demo-"

CITIES = [
    ("北京", 116.40, 39.90), ("上海", 121.47, 31.23), ("广州", 113.26, 23.13),
    ("深圳", 114.06, 22.55), ("成都", 104.07, 30.57), ("重庆", 106.55, 29.56),
    ("杭州", 120.15, 30.28), ("武汉", 114.30, 30.59), ("西安", 108.95, 34.27),
    ("南京", 118.80, 32.06), ("长沙", 112.94, 28.23), ("厦门", 118.09, 24.48),
]

PREFIX = ["巷子口", "老街", "阿婆", "小院", "深夜", "转角", "弄堂", "桥头", "南门", "北岸", "东街", "梧桐"]
SUFFIX = ["食堂", "小馆", "铺子", "老店", "二店", "厨房", "档口", "人家"]

CUISINES = [
    ("火锅", ["火锅", "聚餐"], 60, 180),
    ("川菜", ["川菜", "下饭"], 40, 110),
    ("日料", ["日料", "深夜"], 80, 260),
    ("烧烤", ["烧烤", "夜宵"], 50, 140),
    ("面馆", ["面馆", "小吃"], 15, 45),
    ("咖啡", ["咖啡", "下午茶"], 25, 70),
    ("甜品", ["甜品", "下午茶"], 15, 50),
    ("粤菜", ["粤菜", "宴请"], 100, 300),
    ("小吃", ["小吃", "老字号"], 10, 40),
    ("西餐", ["西餐", "约会"], 90, 280),
    ("湘菜", ["湘菜", "下饭"], 40, 120),
    ("江浙菜", ["江浙菜", "清淡"], 60, 160),
    ("海鲜", ["海鲜", "聚餐"], 120, 320),
    ("早餐", ["早餐", "小吃"], 8, 25),
    ("烤肉", ["烤肉", "聚餐"], 70, 180),
    ("茶餐厅", ["粤菜", "快餐"], 35, 90),
]

NOTES = [
    "周末人有点多，建议错峰。",
    "招牌菜确实稳，其他一般。",
    "环境不错，适合朋友小聚。",
    "性价比高，分量足。",
    "服务一般，但味道值得。",
    "排队四十分钟，吃到就值了。",
    "带长辈来比较合适。",
    "下午去人少，座位随便挑。",
    "第二次来了，还是很稳。",
    "口味偏重，记得让少放辣。",
]

STATUS = ["want", "visited", "favorite"]


def schedule(fmt):
    """生成一份「每天都营业」的时间表，格式与前端 serializeHours 一致。"""
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return json.dumps({d: [{"s": fmt[0], "e": fmt[1]}] for d in days}, ensure_ascii=False)


def is_real_data_dir() -> bool:
    """目标是不是项目下的真实 data/（没有用 FOODMAP_DATA_DIR 指到别处）。

    写库脚本一旦误打真实库，清理起来很麻烦（2026-10-21 真发生过一次）。
    所以只要目标是真实目录，就必须显式加 --yes。
    """
    return not os.environ.get("FOODMAP_DATA_DIR")


def _photo_file(rel_path):
    """把 photos/xxx.jpg 解析成绝对路径；越界（../）返回 None。"""
    try:
        root = os.path.realpath(PHOTOS_DIR)
        full = os.path.realpath(os.path.join(DATA_DIR, str(rel_path).replace("\\", "/")))
        return full if os.path.commonpath([root, full]) == root else None
    except (OSError, ValueError):
        return None


def clear_demo():
    """删除 demo- 记录；照片行随外键级联，文件等库删成功后再清。"""
    repo = SQLiteRepository()
    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM records WHERE id LIKE ?", (DEMO_PREFIX + "%",)).fetchall()]
    if not ids:
        print("没有演示记录（id 前缀 demo-），无需清理")
        return
    paths = repo.photo_paths(ids)          # 先取文件路径，库删完再删文件
    n = repo.delete_many(ids)
    files = 0
    for p in paths:
        full = _photo_file(p)
        if full and os.path.isfile(full):
            try:
                os.remove(full)
                files += 1
            except OSError:
                pass
    print(f"已删除演示记录 {n} 条、照片文件 {files} 个（真实记录未动）")


def seed(count, seed_value):
    random.seed(seed_value)
    repo = SQLiteRepository()
    now = datetime.now()
    created = 0

    # 先清掉上一轮 demo 数据：id 是 demo-001 这样的固定编号，
    # 直接 INSERT 会在第二次执行时撞主键（UNIQUE constraint failed）。
    # 只删 demo- 前缀，真实记录不受影响。
    with get_conn() as conn:
        conn.execute("DELETE FROM records WHERE id LIKE ?", (DEMO_PREFIX + "%",))

    for i in range(count):
        city, clng, clat = random.choice(CITIES)
        cuisine, tags, lo, hi = random.choice(CUISINES)
        draft = (i % 13 == 0) and i != 0          # 约 7 条草稿，第一条保持正式
        rating = random.choices([5, 4, 3, 2, 1], weights=[30, 40, 20, 7, 3])[0]
        status = None if draft else random.choices(STATUS, weights=[40, 40, 20])[0]

        name = f"{random.choice(PREFIX)}{cuisine}"
        if random.random() < 0.25:
            name += random.choice(SUFFIX)
        if random.random() < 0.55:
            name = f"{city}·{name}"
        if random.random() < 0.12:
            name += f"（{random.randint(2, 5)}号店）"

        price = None if (draft or random.random() < 0.08) else random.randint(lo, hi)
        days_ago = random.randint(0, 180)
        ts = int((now - timedelta(days=days_ago, hours=random.randint(0, 20),
                                  minutes=random.randint(0, 59))).timestamp() * 1000)
        # 一部分记录最近被编辑过，让「最近更新」排序有层次
        if random.random() < 0.25:
            ts = min(int(now.timestamp() * 1000), ts + random.randint(1, 72) * 3600 * 1000)

        hours = None
        if not draft and random.random() < 0.7:
            start = random.choice(["09:00", "10:30", "11:00", "17:00"])
            end = random.choice(["21:00", "22:00", "22:30", "02:00"])
            hours = schedule((start, end))

        repo.create({
            "id": f"{DEMO_PREFIX}{i + 1:03d}",
            "name": name,
            "lng": round(clng + random.uniform(-0.08, 0.08), 6),
            "lat": round(clat + random.uniform(-0.08, 0.08), 6),
            "rating": rating,
            "tags": tags if not draft else tags[:1],
            "businessHours": hours,
            "avgPrice": price,
            "checkinStatus": status,
            "note": None if draft and random.random() < 0.5 else random.choice(NOTES),
            "draft": draft,
            "createdAt": ts,
            "updatedAt": ts,
        })
        created += 1

    print(f"已写入演示记录 {created} 条（id 前缀 {DEMO_PREFIX}）")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 / 清除美食地图演示数据")
    ap.add_argument("--count", type=int, default=100, help="生成条数，默认 100")
    ap.add_argument("--seed", type=int, default=20261019, help="随机种子（默认固定）")
    ap.add_argument("--clear", action="store_true", help="只删除 id 以 demo- 开头的记录")
    ap.add_argument("--yes", action="store_true", help="确认真实数据目录也允许写入/清理")
    args = ap.parse_args(argv)

    if is_real_data_dir() and not args.yes:
        print(f"[seed_demo] 目标数据目录：{DATA_DIR}")
        print("[seed_demo] 这是项目下的真实数据目录，本次会真的写入/删除。")
        print("[seed_demo] 确认执行请加 --yes；只想试跑请先设置 FOODMAP_DATA_DIR 指向临时目录。")
        return 2

    print(f"[seed_demo] 数据目录：{DATA_DIR}")
    init_db()
    if args.clear:
        clear_demo()
        return 0
    if args.count <= 0:
        print("--count 必须大于 0", file=sys.stderr)
        return 1
    seed(args.count, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
