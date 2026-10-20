"""导入校验：畸形备份不能把库写脏，也不能让列表接口炸掉。

覆盖两类问题：
1. 字段类型不合法（tags 是字符串/对象、价格是 "abc"、状态是乱写）→ 归一化或拒绝；
2. 照片载荷不合法（非图片、超大、非 base64）→ 只跳过该张，记录照常恢复。
"""
import base64

from app.db import get_conn


def _import(client, records, confirm=True):
    import json

    body = {"app": "foodmap", "version": 2, "records": records}
    params = {"confirm": "true"} if confirm else None
    return client.post(
        "/api/import",
        params=params,
        files={"file": ("b.json", json.dumps(body, ensure_ascii=False).encode(), "application/json")},
    )


def _rec(**over):
    base = {"id": "r1", "name": "测试店", "lng": 116.4, "lat": 39.9, "rating": 4}
    base.update(over)
    return base


# ---------- tags 归一化 ----------

def test_string_tags_become_list(client):
    res = _import(client, [_rec(tags="火锅")])
    assert res.status_code == 200, res.text
    assert client.get("/api/records/r1").json()["tags"] == ["火锅"]


def test_object_tags_become_empty_list(client):
    res = _import(client, [_rec(tags={"a": 1})])
    assert res.status_code == 200
    assert client.get("/api/records/r1").json()["tags"] == []


def test_nested_and_mixed_tags_are_cleaned(client):
    res = _import(client, [_rec(tags=["火锅", 1, None, {"x": 1}, " 火锅 ", "", "烧烤"])])
    assert res.status_code == 200
    # 非字符串丢弃、去重、去空白
    assert client.get("/api/records/r1").json()["tags"] == ["火锅", "烧烤"]


def test_list_still_loads_after_bad_tags(client):
    """核心回归：畸形 tags 不能让 /api/records 500（前端一次请求就白屏）。"""
    _import(client, [_rec(tags="火锅")])
    r = client.get("/api/records")
    assert r.status_code == 200, r.text
    assert isinstance(r.json()[0]["tags"], list)


# ---------- 其它字段 ----------

def test_price_and_checkin_are_normalized(client):
    _import(client, [_rec(avgPrice="abc", checkinStatus="VISITED ")])
    rec = client.get("/api/records/r1").json()
    assert rec["avgPrice"] is None
    assert rec["checkinStatus"] == "visited"


def test_numeric_price_string_is_accepted(client):
    _import(client, [_rec(avgPrice="88")])
    assert client.get("/api/records/r1").json()["avgPrice"] == 88


def test_out_of_range_price_is_dropped(client):
    _import(client, [_rec(avgPrice=9999999)])
    assert client.get("/api/records/r1").json()["avgPrice"] is None


def test_iso_timestamps_are_converted(client):
    _import(client, [_rec(createdAt="2026-01-02T03:04:05", updatedAt="2026-01-02 03:04:05")])
    rec = client.get("/api/records/r1").json()
    assert isinstance(rec["createdAt"], int) and rec["createdAt"] > 0
    assert isinstance(rec["updatedAt"], int) and rec["updatedAt"] > 0


def test_bad_timestamps_fall_back_to_now(client):
    _import(client, [_rec(createdAt="昨天", updatedAt=None)])
    rec = client.get("/api/records/r1").json()
    assert isinstance(rec["createdAt"], int) and rec["createdAt"] > 0


def test_non_string_note_is_dropped(client):
    _import(client, [_rec(note={"not": "text"})])
    assert client.get("/api/records/r1").json()["note"] is None


# ---------- 无效记录 ----------

def test_invalid_core_fields_are_reported_not_crashing(client):
    res = _import(client, [
        _rec(id="ok"),
        _rec(id="bad_rating", rating=9),
        _rec(id="bad_lng", lng="abc"),
        _rec(id="nan", lng=float("nan")),
        _rec(id="no_name", name="   "),
        "not-a-dict",
    ], confirm=False)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["append"] == 1
    assert body["invalid"] == 5
    fields = [d["fields"][0] for d in body["invalidDetails"]]
    assert "rating" in fields and "lng/lat" in fields and "name" in fields


def test_bool_rating_is_not_treated_as_int(client):
    res = _import(client, [_rec(rating=True)], confirm=False)
    assert res.json()["invalid"] == 1


# ---------- 照片安全 ----------

def test_non_image_photo_payload_is_skipped(client):
    payload = base64.b64encode(b"<html><script>alert(1)</script></html>").decode()
    body = _import(client, [_rec(photos=[{"data": payload}])]).json()
    assert body["written"] == 1
    assert body["photosSkipped"] == 1
    rec = client.get("/api/records/r1").json()
    assert rec.get("cover") is None           # 没有把 HTML 伪装成 .jpg 存下来


def test_invalid_base64_is_skipped(client):
    body = _import(client, [_rec(photos=[{"data": "!!!not-base64!!!"}])]).json()
    assert body["photosSkipped"] == 1


def test_base64_with_line_breaks_is_accepted(client):
    """手工/第三方工具常把 base64 折成 76 列，去掉空白后应当照常识别。"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (24, 18), (30, 160, 60)).save(buf, "JPEG")
    raw = base64.b64encode(buf.getvalue()).decode()
    wrapped = "\n".join(raw[i:i + 76] for i in range(0, len(raw), 76))
    body = _import(client, [_rec(photos=[{"data": wrapped}])]).json()
    assert body["photosSkipped"] == 0
    row = next(r for r in client.get("/api/records").json() if r["id"] == "r1")
    assert row.get("cover")


def test_photo_path_outside_photos_dir_is_not_served(client):
    """库里若被写入逃逸路径（../ 或绝对路径），读取与删除都必须拒绝。"""
    from app.main import _safe_photo_path

    assert _safe_photo_path("../foodmap.db") is None
    assert _safe_photo_path("C:/Windows/win.ini") is None
    assert _safe_photo_path("") is None
    assert _safe_photo_path("photos/ok.jpg") is not None

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id,name,lng,lat,rating,tags,business_hours,avg_price,"
            "checkin_status,note,draft,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("evil", "越权店", 1, 1, 4, "[]", None, None, None, None, 0, 1, 1),
        )
        conn.execute(
            "INSERT INTO photos (id,record_id,path,thumb,created_at) VALUES (?,?,?,?,?)",
            ("evilp", "evil", "../../etc/passwd", None, 1),
        )
    assert client.get("/api/photos/evilp").status_code == 404


def test_export_does_not_read_outside_photos_dir(client):
    """库里的 photos.path 被改成 ../ 时，导出不能把目录外文件当照片打包走。

    导出走的是 _safe_photo_path，和读取/删除同一套边界检查。
    """
    import json
    import os

    from app.pathconf import DATA_DIR

    secret = os.path.join(DATA_DIR, "secret-note.txt")
    with open(secret, "w", encoding="utf-8") as f:
        f.write("TOP-SECRET-CONTENT")

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id,name,lng,lat,rating,tags,business_hours,avg_price,"
            "checkin_status,note,draft,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("evil2", "越权店", 1, 1, 4, "[]", None, None, None, None, 0, 1, 1),
        )
        conn.execute(
            "INSERT INTO photos (id,record_id,path,thumb,created_at) VALUES (?,?,?,?,?)",
            ("evilp2", "evil2", "../secret-note.txt", None, 1),
        )

    r = client.get("/api/export", params={"mode": "full"})
    assert r.status_code == 200
    body = json.loads(r.content)
    rec = next(x for x in body["records"] if x["id"] == "evil2")
    assert rec["photos"] == []
    assert "TOP-SECRET-CONTENT" not in r.text


def test_oversized_photo_is_skipped_without_decoding(client):
    payload = base64.b64encode(b"\x00" * (3 * 1024 * 1024)).decode()
    body = _import(client, [_rec(photos=[{"data": payload}])]).json()
    assert body["written"] == 1
    assert body["photosSkipped"] == 1


def test_photos_field_with_wrong_type_keeps_record(client):
    body = _import(client, [_rec(photos={"data": "x"})]).json()
    assert body["written"] == 1
    assert client.get("/api/records/r1").status_code == 200


def test_import_rejects_non_json_and_wrong_shape(client):
    r = client.post("/api/import", files={"file": ("x.json", b"{not json", "application/json")})
    assert r.status_code == 400
    r = client.post("/api/import", files={"file": ("x.json", b'{"foo":1}', "application/json")})
    assert r.status_code == 400


# ---------- 历史脏数据兜底 ----------

def test_legacy_bad_tags_in_db_do_not_break_list_or_dashboard(client):
    """手工改过/旧版本留下的脏 tags（JSON 字符串）也要能安全读出。"""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id,name,lng,lat,rating,tags,business_hours,avg_price,"
            "checkin_status,note,draft,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy", "旧数据店", 116.4, 39.9, 4, '"火锅"', None, "abc", None, None, 0, 1, 1),
        )

    r = client.get("/api/records")
    assert r.status_code == 200, r.text
    rec = next(x for x in r.json() if x["id"] == "legacy")
    assert rec["tags"] == ["火锅"]
    assert rec["avgPrice"] is None

    assert client.get("/api/dashboard").status_code == 200
