# -*- coding: utf-8 -*-
"""生成 1000 条美食记录并写入 FoodMap（经 API，固定随机种子可复现）。"""
import urllib.request as u, json, random, os


def _base():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".last_port")
    try:
        port = int(open(p).read().strip())
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:20000"


random.seed(20261010)
BASE = _base()

cities = [
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
prefix = ['老','金','福','聚','香','味','家','御','蜀','湘','粤','徽','京','川','渝','真','好','大','小','鲜','和','兴','德','一','三']
suffix = ['记','馆','轩','坊','居','楼','铺','庄','屋','社','堂','房','舍']
cores = ['火锅','川菜','粤菜','日料','韩餐','烧烤','小龙虾','麻辣烫','快餐','咖啡','奶茶','甜品',
         '面馆','米线','寿司','汉堡','披萨','海鲜','鲁菜','家常菜','砂锅','卤味','烘焙','早餐','夜宵',
         '大排档','江湖菜','私房菜','汤包','螺蛳粉','酸菜鱼','烧腊','烤鱼','串串','干锅','猪脚饭',
         '肠粉','拉面','茶餐厅','简餐','食堂','小吃','夜市','海鲜城','烧味','煲仔饭','麻辣香锅']
tagpool = ['火锅','川菜','粤菜','日料','烧烤','小龙虾','麻辣烫','快餐','咖啡','奶茶','甜品','面馆',
           '寿司','披萨','海鲜','家常菜','砂锅','卤味','烘焙','早餐','夜宵','大排档','江湖菜','汤包',
           '螺蛳粉','酸菜鱼','烧腊','烤鱼','串串','拉面','本地菜','清淡','重辣','微辣','适合约会',
           '适合家庭','适合聚会','性价比','人均低','老字号','排队王']
notes = ['性价比很高，环境干净','朋友聚合适合','味道正宗，排队也值得','服务态度好','分量足',
         '老板很热情','装修有特色','适合家庭聚餐','外卖很快','味道稳定','值得一试',
         '分量比想象中多','环境安静','菜偏辣','价格小贵','位置好找','停车方便','上菜快',
         '有老字号的感觉','本地人都来','适合一个人吃']

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

used = set()
rows = []
for _ in range(1000):
    cname, clng, clat = random.choice(cities)
    name = f"{random.choice(prefix)}{random.choice(cores)}{random.choice(suffix)}"
    while name in used:
        name = f"{random.choice(prefix)}{random.choice(cores)}{random.choice(suffix)}{random.randint(1,99)}"
    used.add(name)
    rows.append({
        'name': name,
        'lng': round(clng + random.uniform(-0.05, 0.05), 6),
        'lat': round(clat + random.uniform(-0.05, 0.05), 6),
        'rating': random.choices([1,2,3,4,5], weights=[5,10,28,36,21])[0],
        'tags': random.sample(tagpool, random.randint(1, 3)),
        'businessHours': gen_hours(),
        'avgPrice': random.randint(12, 380),
        'checkinStatus': random.choices([None,'want','visited','favorite'], weights=[18,24,34,24])[0],
        'note': random.choice(notes),
        'draft': False,
    })

ok = err = 0
errs = []
for r in rows:
    try:
        req = u.Request(BASE+'/api/records',
                        data=json.dumps(r, ensure_ascii=False).encode(),
                        headers={'Content-Type':'application/json'}, method='POST')
        u.urlopen(req, timeout=10).read()
        ok += 1
    except Exception as e:
        err += 1
        if len(errs) < 3: errs.append(str(e)[:140])

print('INSERTED', ok, 'FAILED', err)
for e in errs: print('ERR:', e)
total = json.loads(u.urlopen(BASE+'/api/records?sort=updatedAt:desc', timeout=15).read())
print('TOTAL IN DB:', len(total))