"""数据访问层：RecordRepository 抽象 + SQLiteRepository 实现
预留 PostgresRepository（DB_TYPE 切换），见需求文档 C-8。
"""
import json
from abc import ABC, abstractmethod
from typing import Optional

from .db import get_conn


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


class SQLiteRepository(RecordRepository):
    def list(self, filters: dict, sort: list, limit: int = 0, offset: int = 0):
        sql = "SELECT * FROM records WHERE 1=1"
        args: list = []
        if not filters.get("includeDrafts"):
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
        with get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM records WHERE draft=0").fetchone()["c"]
            visited = conn.execute(
                "SELECT COUNT(*) c FROM records WHERE checkin_status='visited' AND draft=0"
            ).fetchone()["c"]
            want = conn.execute(
                "SELECT COUNT(*) c FROM records WHERE checkin_status='want' AND draft=0"
            ).fetchone()["c"]
            favorite = conn.execute(
                "SELECT COUNT(*) c FROM records WHERE checkin_status='favorite' AND draft=0"
            ).fetchone()["c"]
            # 城市数：按经纬度粗略四舍五入聚类到 1° 网格近似"城市"
            rows = conn.execute(
                "SELECT DISTINCT round(lat,1), round(lng,1) FROM records WHERE draft=0"
            ).fetchall()
            cities = len(rows)
            avg_rows = conn.execute(
                "SELECT avg_price FROM records WHERE avg_price IS NOT NULL AND draft=0"
            ).fetchall()
            avg_price_list = [r["avg_price"] for r in avg_rows]
            # Top 菜系（标签频次）
            tag_rows = conn.execute("SELECT tags FROM records WHERE draft=0").fetchall()
            from collections import Counter
            cnt = Counter()
            for r in tag_rows:
                for t in (json.loads(r["tags"]) if r["tags"] else []):
                    cnt[t] += 1
            top_cuisines = [{"tag": k, "count": v} for k, v in cnt.most_common(10)]
            avg_price_avg = round(sum(avg_price_list) / len(avg_price_list), 1) if avg_price_list else 0
        return {
            "total": total,
            "cities": cities,
            "checkin": {"visited": visited, "want": want, "favorite": favorite},
            "avgPriceAvg": avg_price_avg,
            "topCuisines": top_cuisines,
        }
