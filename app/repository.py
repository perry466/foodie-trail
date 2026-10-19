"""数据访问层：RecordRepository 抽象 + SQLiteRepository 实现
预留 PostgresRepository（DB_TYPE 切换），见需求文档 C-8。
"""
import json
from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime
from typing import Optional

from .db import get_conn

# SQLite 单条 SQL 的参数上限默认 999，批量 IN 操作按 400 分批
_CHUNK_SIZE = 400


def _pct(part: int, whole: int) -> float:
    """占比（百分比，保留 1 位小数）；分母为 0 时返回 0。"""
    return round(part * 100 / whole, 1) if whole else 0.0


def _epoch_ms(value) -> int:
    """created_at 统一为毫秒时间戳；兼容历史数据里可能存在的字符串写法。"""
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str):
        txt = value.strip().replace("Z", "+00:00")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(txt[:19], fmt).timestamp() * 1000)
            except ValueError:
                continue
        try:
            return int(datetime.fromisoformat(txt).timestamp() * 1000)
        except ValueError:
            return 0
    return 0


def _chunks(seq, size: int = _CHUNK_SIZE):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _row_to_record(row, with_photos: bool = False) -> dict:
    rec = {
        "id": row["id"],
        "name": row["name"],
        "lng": row["lng"],
        "lat": row["lat"],
        "rating": row["rating"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "businessHours": row["business_hours"],
        "avgPrice": row["avg_price"],
        "checkinStatus": row["checkin_status"],
        "note": row["note"],
        "draft": bool(row["draft"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if with_photos:
        rec["photos"] = _photos_for(row["id"])
    return rec


def _photos_for(record_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, path, thumb, created_at FROM photos WHERE record_id=? ORDER BY created_at",
            (record_id,),
        ).fetchall()
    return [
        {"id": r["id"], "path": r["path"], "thumb": r["thumb"], "createdAt": r["created_at"]}
        for r in rows
    ]


class RecordRepository(ABC):
    @abstractmethod
    def list(self, filters: dict, sort: list, limit: int = 0, offset: int = 0): ...
    @abstractmethod
    def get(self, rid: str): ...
    @abstractmethod
    def create(self, payload: dict): ...
    @abstractmethod
    def update(self, rid: str, payload: dict): ...
    @abstractmethod
    def delete(self, rid: str): ...
    @abstractmethod
    def delete_many(self, ids: list) -> int: ...
    @abstractmethod
    def photo_paths(self, ids: list) -> list: ...


class SQLiteRepository(RecordRepository):
    def list(self, filters: dict, sort: list, limit: int = 0, offset: int = 0):
        sql = "SELECT * FROM records WHERE 1=1"
        args: list = []
        if filters.get("draftsOnly"):
            sql += " AND (draft=1)"
        elif not filters.get("includeDrafts"):
            sql += " AND (draft=0)"
        if filters.get("keyword"):
            kw = f"%{filters['keyword']}%"
            sql += " AND (name LIKE ? OR note LIKE ? OR tags LIKE ?)"
            args += [kw, kw, kw]
        if filters.get("ratingMin") is not None:
            sql += " AND rating >= ?"
            args.append(filters["ratingMin"])
        if filters.get("ratingMax") is not None:
            sql += " AND rating <= ?"
            args.append(filters["ratingMax"])
        if filters.get("avgPriceMin") is not None:
            sql += " AND avg_price >= ?"
            args.append(filters["avgPriceMin"])
        if filters.get("avgPriceMax") is not None:
            sql += " AND avg_price <= ?"
            args.append(filters["avgPriceMax"])
        if filters.get("checkinStatus"):
            sql += " AND checkin_status = ?"
            args.append(filters["checkinStatus"])
        if filters.get("tags"):
            for t in filters["tags"]:
                sql += " AND tags LIKE ?"
                args.append('%"' + t + '"%')  # 粗略匹配标签 JSON
        if filters.get("bounds"):
            b = filters["bounds"]
            sql += " AND lng BETWEEN ? AND ? AND lat BETWEEN ? AND ?"
            args += [b["swLng"], b["neLng"], b["swLat"], b["neLat"]]

        order_clauses = []
        for field, direction in (sort or [("updated_at", "desc")]):
            col = {
                "updatedAt": "updated_at",
                "rating": "rating",
                "name": "name",
                "avgPrice": "avg_price",
                "createdAt": "created_at",
            }.get(field, "updated_at")
            order_clauses.append(f"{col} {direction}")
        sql += " ORDER BY " + ", ".join(order_clauses)
        if limit > 0:
            sql += " LIMIT ? OFFSET ?"
            args += [limit, offset]

        with get_conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_row_to_record(r) for r in rows]

    def get(self, rid: str):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
        return _row_to_record(row, with_photos=True) if row else None

    def create(self, payload: dict):
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO records
                   (id,name,lng,lat,rating,tags,business_hours,avg_price,checkin_status,note,draft,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload["id"], payload["name"], payload["lng"], payload["lat"],
                    payload["rating"], json.dumps(payload.get("tags", []), ensure_ascii=False),
                    payload.get("businessHours"), payload.get("avgPrice"),
                    payload.get("checkinStatus"), payload.get("note"),
                    int(bool(payload.get("draft", False))),
                    payload["createdAt"], payload["updatedAt"],
                ),
            )
        return self.get(payload["id"])

    def update(self, rid: str, payload: dict):
        with get_conn() as conn:
            cur = conn.execute(
                """UPDATE records SET
                   name=?, lng=?, lat=?, rating=?, tags=?, business_hours=?, avg_price=?,
                   checkin_status=?, note=?, draft=?, updated_at=?
                   WHERE id=?""",
                (
                    payload["name"], payload["lng"], payload["lat"], payload["rating"],
                    json.dumps(payload.get("tags", []), ensure_ascii=False),
                    payload.get("businessHours"), payload.get("avgPrice"),
                    payload.get("checkinStatus"), payload.get("note"),
                    int(bool(payload.get("draft", False))), payload["updatedAt"], rid,
                ),
            )
            if cur.rowcount == 0:
                return None
        return self.get(rid)

    def delete(self, rid: str):
        with get_conn() as conn:
            conn.execute("DELETE FROM records WHERE id=?", (rid,))

    def delete_many(self, ids: list) -> int:
        """单连接、分批删除多条记录；photos 表随外键 ON DELETE CASCADE 清理。

        SQLite 的 IN 参数上限默认 999，且每次新建连接都会重新执行
        `PRAGMA journal_mode=WAL`（需抢写锁），逐条删 1000 条会因锁竞争慢到超时，
        因此这里共用一条连接并每批 400 个 id。
        """
        if not ids:
            return 0
        total = 0
        with get_conn() as conn:
            for chunk in _chunks(ids):
                placeholders = ",".join("?" for _ in chunk)
                cur = conn.execute(
                    f"DELETE FROM records WHERE id IN ({placeholders})", tuple(chunk)
                )
                total += cur.rowcount or 0
        return total

    def photo_paths(self, ids: list) -> list:
        """批量取照片文件路径（删除记录前清理磁盘文件用），同样单连接分批查询。"""
        if not ids:
            return []
        paths = []
        with get_conn() as conn:
            for chunk in _chunks(ids):
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT path FROM photos WHERE record_id IN ({placeholders})",
                    tuple(chunk),
                ).fetchall()
                paths += [r["path"] for r in rows]
        return paths

    def upsert(self, payload: dict):
        """导入用：存在则按 updatedAt 较新覆盖，否则插入。"""
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT updated_at FROM records WHERE id=?", (payload["id"],)
            ).fetchone()
            if existing and existing["updated_at"] >= payload["updatedAt"]:
                return "skip"
            conn.execute(
                """INSERT INTO records
                   (id,name,lng,lat,rating,tags,business_hours,avg_price,checkin_status,note,draft,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name, lng=excluded.lng, lat=excluded.lat, rating=excluded.rating,
                   tags=excluded.tags, business_hours=excluded.business_hours, avg_price=excluded.avg_price,
                   checkin_status=excluded.checkin_status, note=excluded.note, draft=excluded.draft,
                   updated_at=excluded.updated_at, created_at=excluded.created_at""",
                (
                    payload["id"], payload["name"], payload["lng"], payload["lat"],
                    payload["rating"], json.dumps(payload.get("tags", []), ensure_ascii=False),
                    payload.get("businessHours"), payload.get("avgPrice"),
                    payload.get("checkinStatus"), payload.get("note"),
                    int(bool(payload.get("draft", False))),
                    payload["createdAt"], payload["updatedAt"],
                ),
            )
        return "upsert"

    def add_photo(self, photo: dict):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO photos(id,record_id,path,thumb,created_at) VALUES (?,?,?,?,?)",
                (photo["id"], photo["recordId"], photo["path"], photo.get("thumb"), photo["createdAt"]),
            )

    def get_photo(self, pid: str):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None

    def delete_photo(self, pid: str):
        with get_conn() as conn:
            conn.execute("DELETE FROM photos WHERE id=?", (pid,))

    def get_setting(self, key: str) -> Optional[str]:
        with get_conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def delete_setting(self, key: str):
        with get_conn() as conn:
            conn.execute("DELETE FROM settings WHERE key=?", (key,))

    def dashboard(self) -> dict:
        """看板聚合：一次查询取回全部记录，在内存里算出所有指标。

        旧实现发了 12 条独立 SQL，且"城市"用 1° 经纬度网格近似（约 110km），
        语义不准 → 现统一改称"区域"。新增状态构成、评分分布、价位分布、
        月度趋势、行动清单与数据健康度。
        """
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT r.id, r.name, r.rating, r.avg_price, r.checkin_status, r.tags,
                          r.note, r.created_at, r.lat, r.lng,
                          (SELECT COUNT(*) FROM photos p WHERE p.record_id = r.id) AS photo_count
                   FROM records r WHERE r.draft = 0"""
            ).fetchall()
            photo_total = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]

        total = len(rows)
        status = {"visited": 0, "want": 0, "favorite": 0}
        rating_dist = {s: 0 for s in range(1, 6)}
        rating_sum = rating_n = 0
        prices: list = []
        tag_cnt: Counter = Counter()
        regions = set()
        want_items: list = []
        q_no_price = q_no_tags = q_no_note = q_no_photo = 0
        with_photo = 0
        newest_days = None

        now = datetime.now()
        months: list = []
        for back in range(11, -1, -1):
            mi = (now.year * 12 + now.month - 1) - back
            months.append(f"{mi // 12:04d}-{mi % 12 + 1:02d}")
        month_index = {k: 0 for k in months}

        for r in rows:
            st = r["checkin_status"] or ""
            if st in status:
                status[st] += 1

            rating = r["rating"]
            if isinstance(rating, int) and 1 <= rating <= 5:
                rating_dist[rating] += 1
                rating_sum += rating
                rating_n += 1
            else:
                rating = 0          # 脏数据不参与分布，也不影响均分

            price = r["avg_price"]
            if isinstance(price, (int, float)) and price > 0:
                prices.append(float(price))
            else:
                q_no_price += 1

            tags = []
            if r["tags"]:
                try:
                    tags = json.loads(r["tags"]) or []
                except (ValueError, TypeError):
                    tags = []
            if tags:
                for t in tags:
                    tag_cnt[t] += 1
            else:
                q_no_tags += 1

            if r["photo_count"]:
                with_photo += 1
            else:
                q_no_photo += 1

            if not (r["note"] or "").strip():
                q_no_note += 1

            if r["lat"] and r["lng"]:
                regions.add((round(r["lat"], 1), round(r["lng"], 1)))

            ts = _epoch_ms(r["created_at"])
            if ts:
                created = datetime.fromtimestamp(ts / 1000)
                key = f"{created.year:04d}-{created.month:02d}"
                if key in month_index:
                    month_index[key] += 1
                days = max(0, (now - created).days)
                newest_days = days if newest_days is None else min(newest_days, days)
            else:
                days = 0

            if st in ("want", "favorite"):
                want_items.append({
                    "id": r["id"], "name": r["name"] or "未命名",
                    "rating": rating, "status": st, "days": days,
                })

        prices.sort()

        def _median(seq: list):
            n = len(seq)
            if not n:
                return 0
            mid = n // 2
            return seq[mid] if n % 2 else round((seq[mid - 1] + seq[mid]) / 2, 1)

        price_buckets = []
        for label, lo, hi in (("<30", 0, 30), ("30-60", 30, 60), ("60-100", 60, 100),
                              ("100-200", 100, 200), ("≥200", 200, None)):
            c = sum(1 for p in prices if p >= lo and (hi is None or p < hi))
            price_buckets.append({
                "label": label, "min": lo, "max": hi,
                "count": c, "pct": _pct(c, len(prices)),
            })

        rating_list = [
            {"star": s, "count": rating_dist[s], "pct": _pct(rating_dist[s], rating_n)}
            for s in (5, 4, 3, 2, 1)
        ]
        tag_total = sum(tag_cnt.values())
        tags_top = [
            {"tag": t, "count": c, "pct": _pct(c, tag_total)}
            for t, c in tag_cnt.most_common(8)
        ]
        month_list = [
            {"key": k, "label": f"{int(k.split('-')[1])}月", "count": month_index[k]}
            for k in months
        ]
        peak = max([m["count"] for m in month_list], default=0)
        year_total = sum(m["count"] for m in month_list)

        top_rated_want = sorted(
            [w for w in want_items if w["rating"] >= 4],
            key=lambda w: (-w["rating"], -w["days"]),
        )[:5]
        oldest_want = sorted(want_items, key=lambda w: -w["days"])[:5]

        return {
            # —— 概览 ——
            "total": total,
            "checkin": status,
            "visitedRate": _pct(status["visited"], total),
            "pending": status["want"] + status["favorite"],
            "pendingHighRated": len([w for w in want_items if w["rating"] >= 4]),
            "regions": len(regions),
            "cities": len(regions),          # 兼容旧字段名
            # —— 人均消费 ——
            "avgPriceAvg": round(sum(prices) / len(prices), 1) if prices else 0,
            "price": {
                "count": len(prices),
                "avg": round(sum(prices) / len(prices), 1) if prices else 0,
                "median": _median(prices),
                "min": int(prices[0]) if prices else 0,
                "max": int(prices[-1]) if prices else 0,
                "buckets": price_buckets,
            },
            # —— 评分 ——
            "rating": {
                "count": rating_n,
                "avg": round(rating_sum / rating_n, 2) if rating_n else 0,
                "dist": rating_list,
            },
            # —— 标签 ——
            "tags": {"distinct": len(tag_cnt), "top": tags_top},
            "topCuisines": [{"tag": t["tag"], "count": t["count"]} for t in tags_top],
            # —— 趋势 ——
            "months": month_list,
            "thisMonth": month_index.get(f"{now.year:04d}-{now.month:02d}", 0),
            "monthPeak": peak,
            "yearTotal": year_total,
            "perMonth": round(year_total / 12, 1),
            "lastAddedDays": newest_days,
            # —— 照片 ——
            "photos": {
                "records": with_photo,
                "total": photo_total,
                "pct": _pct(with_photo, total),
            },
            # —— 数据健康度（rating / 经纬度为 NOT NULL，不缺，故不列入）——
            "quality": {
                "noPrice": q_no_price, "noTags": q_no_tags,
                "noNote": q_no_note, "noPhoto": q_no_photo,
            },
            # —— 行动清单 ——
            "actions": {
                "topRatedWant": top_rated_want,
                "oldestWant": oldest_want,
            },
        }
