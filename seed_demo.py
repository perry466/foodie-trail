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
import random
import sys
import time
from datetime import datetime, timedelta

from app.db import get_conn, init_db
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


def clear_demo():
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM records WHERE id LIKE ?", (DEMO_PREFIX + "%",))
        n = cur.rowcount or 0
    print(f"已删除演示记录 {n} 条（真实记录未动）")


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


def main():
    ap = argparse.ArgumentParser(description="生成 / 清除美食地图演示数据")
    ap.add_argument("--count", type=int, default=100, help="生成条数，默认 100")
    ap.add_argument("--seed", type=int, default=20261019, help="随机种子（默认固定）")
    ap.add_argument("--clear", action="store_true", help="只删除 id 以 demo- 开头的记录")
    args = ap.parse_args()

    init_db()
    if args.clear:
        clear_demo()
        return
    if args.count <= 0:
        print("--count 必须大于 0", file=sys.stderr)
        sys.exit(1)
    seed(args.count, args.seed)


if __name__ == "__main__":
    main()
