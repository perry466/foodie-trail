# -*- coding: utf-8 -*-
"""生成演示记录并写入**正在运行的** FoodMap（走 API，固定随机种子可复现）。

⚠️ 会直接写库，且目标由「数据目录里的 .last_port」推断。为了不误伤真实数据：
- 数据目录优先取 `FOODMAP_DATA_DIR`，其次才是项目下的 `data/`；
- 启动前先探测服务（3s），连不上就**一条都不写**并退出 1；
- 写入过程中连续失败 5 条就中止，不会空转 1000 次；
- 支持 `--base` 指定地址、`--dry-run` 只看目标不写。

用法：
    python seed_1000.py --count 200
    python seed_1000.py --base http://127.0.0.1:51834 --count 50
    python seed_1000.py --dry-run
"""
import argparse
import json
import os
import random
import sys
import urllib.parse as up
import urllib.request as u

CITIES = [
    ('北京',116.40,39.90),('上海',121.47,31.23),('广州',113.26,23.13),('深圳',114.06,22.55),
    ('成都',104.07,30.57),('重庆',106.55,29.56),('杭州',120.15,30.28),('武汉',114.30,30.59),
    ('西安',108.95,34.27),('南京',118.80,32.06),('天津',117.20,39.12),('苏州',120.58,31.30),
    ('长沙',112.94,28.23),('郑州',113.62,34.75),('青岛',120.38,36.07),('沈阳',123.43,41.80),
    ('大连',121.62,38.91),('哈尔滨',126.53,45.80),('长春',125.32,43.82),('济南',117.00,36.65),
    ('合肥',117.28,31.86),('福州',119.30,26.08),('厦门',118.09,24.48),('南昌',115.89,28.68),
    ('太原',112.55,37.87),('石家庄',114.51,38.04),('南宁',108.32,22.82),('昆明',102.83,24.88),
    ('贵阳',106.63,26.65),('兰州',103.83,36.06),('海口',110.20,20.04),('乌鲁木齐',87.62,43.79),
    ('呼和浩特',111.75,40.84),('银川',106.23,38.49),('西宁',101.78,36.62),('宁波',121.55,29.87),
    ('无锡',120.30,31.57),('温州',120.70,28.00),('泉州',118.68,24.87),('徐州',117.28,34.20),
    ('唐山',118.18,39.63),('洛阳',112.45,34.62),
]
PREFIX = ['老','金','福','聚','香','味','家','御','蜀','湘','粤','徽','京','川','渝','真','好','大','小','鲜','和','兴','德','一','三']
SUFFIX = ['记','馆','轩','坊','居','楼','铺','庄','屋','社','堂','房','舍']
CORES = ['火锅','川菜','粤菜','日料','韩餐','烧烤','小龙虾','麻辣烫','快餐','咖啡','奶茶','甜品',
         '面馆','米线','寿司','汉堡','披萨','海鲜','鲁菜','家常菜','砂锅','卤味','烘焙','早餐','夜宵',
         '大排档','江湖菜','私房菜','汤包','螺蛳粉','酸菜鱼','烧腊','烤鱼','串串','干锅','猪脚饭',
         '肠粉','拉面','茶餐厅','简餐','食堂','小吃','夜市','海鲜城','烧味','煲仔饭','麻辣香锅']
TAGS = ['火锅','川菜','粤菜','日料','烧烤','小龙虾','麻辣烫','快餐','咖啡','奶茶','甜品','面馆',
        '寿司','披萨','海鲜','家常菜','砂锅','卤味','烘焙','早餐','夜宵','大排档','江湖菜','汤包',
        '螺蛳粉','酸菜鱼','烧腊','烤鱼','串串','拉面','本地菜','清淡','重辣','微辣','适合约会',
        '适合家庭','适合聚会','性价比','人均低','老字号','排队王']
NOTES = ['性价比很高，环境干净','朋友聚合适合','味道正宗，排队也值得','服务态度好','分量足',
         '老板很热情','装修有特色','适合家庭聚餐','外卖很快','味道稳定','值得一试',
         '分量比想象中多','环境安静','菜偏辣','价格小贵','位置好找','停车方便','上菜快',
         '有老字号的感觉','本地人都来','适合一个人吃']


def data_dir() -> str:
    """数据目录：与 app/pathconf.py 同口径，先看 FOODMAP_DATA_DIR。"""
    env = os.environ.get("FOODMAP_DATA_DIR")
    if env:
        return os.path.abspath(env)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def resolve_base(cli_base: str = "") -> str:
    """目标服务地址：--base 优先，其次数据目录里的 .last_port，最后兜底 20000。"""
    if cli_base:
        return cli_base.rstrip("/")
    try:
        with open(os.path.join(data_dir(), ".last_port")) as f:
            port = int(f.read().strip())
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:20000"


def gen_hours():
    if random.random() < 0.25:
        return None
    sched = {k: [] for k in ['mon','tue','wed','thu','fri','sat','sun']}
    r = random.random()
    if r < 0.40:
        s, e = random.choice([('09:00','21:00'),('10:00','22:00'),('08:00','20:00'),('11:00','23:00'),('07:00','19:00')])
        for k in sched: sched[k] = [{'s': s, 'e': e}]
    elif r < 0.75:
        for k in ['mon','tue','wed','thu','fri']:
            sched[k] = [{'s':'10:00','e':'14:00'},{'s':'17:00','e':'22:00'}]
        for k in ['sat','sun']:
            sched[k] = [{'s':'10:00','e':'22:00'}]
    else:
        rest = random.choice(['mon','tue','wed','thu','fri','sat','sun'])
        s, e = random.choice([('10:00','22:00'),('09:00','21:00'),('11:00','23:00')])
        for k in sched:
            if k != rest: sched[k] = [{'s': s, 'e': e}]
    return json.dumps(sched, ensure_ascii=False)


def build_rows(count: int) -> list:
    rows, used = [], set()
    for _ in range(count):
        cname, clng, clat = random.choice(CITIES)
        name = f"{random.choice(PREFIX)}{random.choice(CORES)}{random.choice(SUFFIX)}"
        while name in used:
            name = f"{random.choice(PREFIX)}{random.choice(CORES)}{random.choice(SUFFIX)}{random.randint(1,99)}"
        used.add(name)
        rows.append({
            'name': name,
            'lng': round(clng + random.uniform(-0.05, 0.05), 6),
            'lat': round(clat + random.uniform(-0.05, 0.05), 6),
            'rating': random.choices([1,2,3,4,5], weights=[5,10,28,36,21])[0],
            'tags': random.sample(TAGS, random.randint(1, 3)),
            'businessHours': gen_hours(),
            'avgPrice': random.randint(12, 380),
            'checkinStatus': random.choices([None,'want','visited','favorite'], weights=[18,24,34,24])[0],
            'note': random.choice(NOTES),
            'draft': False,
        })
    return rows


def opener_for(base: str):
    """本机地址绕开系统代理。

    开了 Clash / 公司代理的机器上，urllib 会按 http_proxy 把 127.0.0.1 也送进代理，
    结果是 502 Bad Gateway（服务明明在跑）。本机回环地址不该走代理。
    """
    host = (up.urlparse(base).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return u.build_opener(u.ProxyHandler({}))
    return u.build_opener()


def probe(base: str, timeout: float = 3.0):
    """先确认服务活着：连不上就一条都不写（旧版会空转上千次请求，且目标错也照写）。"""
    try:
        with opener_for(base).open(base + "/api/records?limit=1", timeout=timeout) as r:
            return r.status == 200, ""
    except Exception as e:
        return False, str(e)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="向运行中的 FoodMap 写入演示记录")
    ap.add_argument("--count", type=int, default=1000, help="生成条数（默认 1000）")
    ap.add_argument("--base", default="", help="服务地址，如 http://127.0.0.1:51834")
    ap.add_argument("--dry-run", action="store_true", help="只打印目标和条数，不写入")
    ap.add_argument("--yes", action="store_true", help="确认向真实数据目录对应的服务写入")
    args = ap.parse_args(argv)

    base = resolve_base(args.base)
    print(f"[seed] 数据目录: {data_dir()}")
    print(f"[seed] 目标服务: {base}")
    print(f"[seed] 计划写入: {args.count} 条")

    if args.dry_run:                       # 只读操作，不需要 --yes
        ok, err = probe(base)
        print("[seed] dry-run：未写入。" + ("" if ok else f"（服务当前不可用：{err[:80]}）"))
        return 0

    if not os.environ.get("FOODMAP_DATA_DIR") and not args.yes:
        print("[seed] 未设置 FOODMAP_DATA_DIR，目标是项目下的真实数据目录。")
        print("[seed] 确认要写入真实库请加 --yes；只想试跑请用 --dry-run，或先设置临时目录。")
        return 2

    ok, err = probe(base)
    if not ok:
        print("[seed] 连不上服务，已中止（未写入任何数据）。")
        print("       先运行 start.bat，或用 --base 指定地址；错误：" + err[:160])
        return 1

    random.seed(20261010)
    rows = build_rows(args.count)
    opener = opener_for(base)

    inserted = failed = consecutive = 0
    errors = []
    for r in rows:
        try:
            req = u.Request(base + '/api/records',
                            data=json.dumps(r, ensure_ascii=False).encode(),
                            headers={'Content-Type': 'application/json'}, method='POST')
            opener.open(req, timeout=10).read()
            inserted += 1
            consecutive = 0
        except Exception as e:
            failed += 1
            consecutive += 1
            if len(errors) < 3:
                errors.append(str(e)[:140])
            if consecutive >= 5:           # 服务半路挂了就别空转剩下的请求
                print(f"[seed] 连续失败 {consecutive} 条，中止（已写入 {inserted} 条）")
                break

    print('INSERTED', inserted, 'FAILED', failed)
    for e in errors:
        print('ERR:', e)
    try:
        with opener.open(base + '/api/records?sort=updatedAt:desc', timeout=15) as r:
            total = json.loads(r.read())
        print('TOTAL IN DB:', len(total))
    except Exception as e:
        print('取总数失败:', str(e)[:160])
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
