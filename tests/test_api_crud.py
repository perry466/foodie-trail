"""常规 CRUD 与照片接口的基线测试。

这些接口是所有功能的地基，之前没有直接覆盖：改坏一个字段名、把 201 写成 200、
或者上传接口在非图片上抛 500，都不容易被发现。
"""
import io

from PIL import Image

from app.db import get_conn


def _img_bytes(size=(32, 24), color=(200, 60, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _create(client, **over):
    payload = {"name": "测试店", "lng": 116.4, "lat": 39.9, "rating": 4}
    payload.update(over)
    return client.post("/api/records", json=payload)


# ---------- 创建 ----------

def test_create_record_returns_201_and_fields(client):
    r = _create(client, name="  阿婆面馆  ", tags=["面馆", "小吃"], avgPrice=28,
                checkinStatus="visited", note="汤头好")
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["name"] == "阿婆面馆"          # 两端空白被清掉
    assert rec["tags"] == ["面馆", "小吃"]
    assert rec["avgPrice"] == 28
    assert rec["checkinStatus"] == "visited"
    assert rec["id"]


def test_create_rejects_blank_name(client):
    assert _create(client, name="   ").status_code == 422


def test_create_rejects_bad_coordinates(client):
    assert _create(client, lng=200).status_code == 422
    assert _create(client, lat=-91).status_code == 422


def test_create_rejects_non_string_tags(client):
    # 标签里混入数字/对象会让前端 tags.forEach 渲染出奇怪内容，入口直接拒绝
    assert _create(client, tags=["火锅", 1]).status_code == 422
    assert _create(client, tags={"a": 1}).status_code == 422


def test_create_dedupes_and_trims_tags(client):
    rec = _create(client, tags=[" 火锅 ", "火锅", "", "火锅"]).json()
    assert rec["tags"] == ["火锅"]


# ---------- 读取 / 更新 / 删除 ----------

def test_get_and_update_record(client):
    rid = _create(client).json()["id"]

    got = client.get(f"/api/records/{rid}")
    assert got.status_code == 200, got.text
    assert got.json()["name"] == "测试店"

    upd = client.put(f"/api/records/{rid}", json={
        "name": "改名后的店", "lng": 116.41, "lat": 39.91, "rating": 5,
        "tags": ["新标签"], "draft": False,
    })
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["name"] == "改名后的店"
    assert body["rating"] == 5
    assert body["tags"] == ["新标签"]


def test_update_missing_record_404(client):
    r = client.put("/api/records/nope", json={"name": "x", "lng": 1, "lat": 1})
    assert r.status_code == 404


def test_delete_record(client):
    rid = _create(client).json()["id"]
    assert client.delete(f"/api/records/{rid}").status_code == 200
    assert client.get(f"/api/records/{rid}").status_code == 404


def test_batch_delete_dedupes_and_counts(client):
    ids = [_create(client, name=f"店{i}").json()["id"] for i in range(3)]
    r = client.request("DELETE", "/api/records/batch",
                       json={"ids": ids + ids[:1] + ["missing"]})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 3
    assert client.get("/api/records").json() == []


def test_unknown_record_does_not_shadow_batch_route(client):
    """批量路由必须注册在 /api/records/{rid} 之前，否则 batch 会被当成 id。"""
    assert client.request("DELETE", "/api/records/batch", json={"ids": []}).status_code == 200


# ---------- 照片 ----------

def test_upload_get_delete_photo(client):
    rid = _create(client).json()["id"]

    up = client.post(f"/api/records/{rid}/photos",
                     files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    assert up.status_code == 200, up.text
    pid = up.json()["id"]

    got = client.get(f"/api/photos/{pid}")
    assert got.status_code == 200
    assert got.content[:2] == b"\xff\xd8"          # 落盘的是 JPEG
    assert len(got.content) > 0

    assert client.delete(f"/api/photos/{pid}").status_code == 200
    assert client.get(f"/api/photos/{pid}").status_code == 404


def test_upload_non_image_is_4xx_not_500(client):
    rid = _create(client).json()["id"]
    r = client.post(f"/api/records/{rid}/photos",
                    files={"file": ("fake.jpg", b"<html>not an image</html>", "image/jpeg")})
    assert r.status_code == 400, r.text


def test_upload_empty_file_is_400(client):
    rid = _create(client).json()["id"]
    r = client.post(f"/api/records/{rid}/photos",
                    files={"file": ("empty.jpg", b"", "image/jpeg")})
    assert r.status_code == 400


def test_photo_limit_per_record(client):
    rid = _create(client).json()["id"]
    for _ in range(9):
        up = client.post(f"/api/records/{rid}/photos",
                         files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
        assert up.status_code == 200, up.text
    over = client.post(f"/api/records/{rid}/photos",
                       files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    assert over.status_code == 400
    assert "9" in over.text


def test_upload_to_missing_record_404(client):
    r = client.post("/api/records/nope/photos",
                    files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    assert r.status_code == 404


# ---------- 排序参数白名单 ----------

def test_sort_by_field_and_direction(client):
    _create(client, name="A", rating=5, avgPrice=100)
    _create(client, name="B", rating=3, avgPrice=30)
    _create(client, name="C", rating=4, avgPrice=60)

    assert [r["rating"] for r in client.get("/api/records", params={"sort": "rating:asc"}).json()] == [3, 4, 5]
    assert [r["rating"] for r in client.get("/api/records", params={"sort": "rating:desc"}).json()] == [5, 4, 3]
    assert [r["avgPrice"] for r in client.get("/api/records", params={"sort": "avgPrice:asc"}).json()] == [30, 60, 100]
    assert [r["name"] for r in client.get("/api/records", params={"sort": "name:asc"}).json()] == ["A", "B", "C"]


def test_sort_field_and_direction_are_whitelisted(client):
    """ORDER BY 无法参数化：非法字段/方向必须被丢弃，不能进 SQL。"""
    from app.repository import normalize_sort

    assert normalize_sort("rating:asc") == [("rating", "asc")]
    assert normalize_sort("name:DESC,avgPrice:asc") == [("name", "desc"), ("avg_price", "asc")]
    # 注入尝试：整段被丢弃，回落到默认排序
    assert normalize_sort("rating:desc;DROP TABLE records--") == [("updated_at", "desc")]
    assert normalize_sort("rating desc") == [("updated_at", "desc")]
    assert normalize_sort("secret:asc") == [("updated_at", "desc")]
    assert normalize_sort(None) == [("updated_at", "desc")]

    _create(client, name="A", rating=5)
    _create(client, name="B", rating=3)
    for bad in ("rating:desc;DROP TABLE records--", "rating:sideways", "secret:asc", "rating desc"):
        r = client.get("/api/records", params={"sort": bad})
        assert r.status_code == 200, (bad, r.text)
    assert len(client.get("/api/records").json()) == 2      # 表还在，数据没被删


# ---------- 人均价位区间：统一为 [下限, 上限) ----------

def _price_records(client):
    """一批刚好卡在桶边界上的记录：29/30/59/60/99/100/199/200 + 一条无人均。"""
    for p in [29, 30, 59, 60, 99, 100, 199, 200]:
        _create(client, name=f"P{p}", avgPrice=p)
    _create(client, name="P-none", avgPrice=None)


def _ids_by_price(client, **params):
    rows = client.get("/api/records", params=params).json()
    return sorted(r["avgPrice"] for r in rows)


def test_price_max_is_exclusive(client):
    """「30–60」= [30, 60)：恰好 60 元的记录不能混进来（与看板分桶、前端预览一致）。"""
    _price_records(client)
    assert _ids_by_price(client, avgPriceMin=30, avgPriceMax=60) == [30, 59]
    assert _ids_by_price(client, avgPriceMin=60, avgPriceMax=100) == [60, 99]
    assert _ids_by_price(client, avgPriceMin=100, avgPriceMax=200) == [100, 199]
    assert _ids_by_price(client, avgPriceMin=0, avgPriceMax=30) == [29]
    assert _ids_by_price(client, avgPriceMin=200) == [200]


def test_price_buckets_match_api_filters(client):
    """看板分桶数必须等于同样条件的列表查询条数（否则点进桶里数量对不上）。"""
    _price_records(client)
    dash = client.get("/api/dashboard").json()
    for b in dash["price"]["buckets"]:
        params = {"avgPriceMin": b["min"]}
        if b["max"] is not None:
            params["avgPriceMax"] = b["max"]
        rows = client.get("/api/records", params=params).json()
        assert len(rows) == b["count"], (b["label"], len(rows), b["count"])
        for r in rows:
            assert r["avgPrice"] >= b["min"]
            if b["max"] is not None:
                assert r["avgPrice"] < b["max"]


# ---------- 删除顺序：先删库，再删文件 ----------

def _rec_with_photo(client, name="待删店"):
    rid = _create(client, name=name).json()["id"]
    up = client.post(f"/api/records/{rid}/photos",
                     files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    assert up.status_code == 200, up.text
    return rid, up.json()["id"]


def test_single_delete_keeps_file_when_db_fails(client, monkeypatch):
    """数据库删除失败时，照片文件不能先被删掉（否则记录还在、图没了）。"""
    import pytest

    from app import main

    rid, pid = _rec_with_photo(client)

    def boom(_rid):
        raise RuntimeError("db down")

    monkeypatch.setattr(main.repo, "delete", boom)
    with pytest.raises(RuntimeError):
        client.delete(f"/api/records/{rid}")

    assert client.get(f"/api/records/{rid}").status_code == 200   # 记录还在
    assert client.get(f"/api/photos/{pid}").status_code == 200    # 文件也还在


def test_batch_delete_keeps_files_when_db_fails(client, monkeypatch):
    import pytest

    from app import main

    rid, pid = _rec_with_photo(client, "批量待删店")

    def boom(_ids):
        raise RuntimeError("db down")

    monkeypatch.setattr(main.repo, "delete_many", boom)
    with pytest.raises(RuntimeError):
        client.request("DELETE", "/api/records/batch", json={"ids": [rid]})

    assert client.get(f"/api/photos/{pid}").status_code == 200


def test_photo_delete_keeps_file_when_db_fails(client, monkeypatch):
    import pytest

    from app import main

    _rid, pid = _rec_with_photo(client, "照片删除店")

    def boom(_pid):
        raise RuntimeError("db down")

    monkeypatch.setattr(main.repo, "delete_photo", boom)
    with pytest.raises(RuntimeError):
        client.delete(f"/api/photos/{pid}")

    assert client.get(f"/api/photos/{pid}").status_code == 200


def test_delete_then_files_are_removed(client):
    """正常路径仍要真的清掉文件，别把顺序改反了变成只删库。"""
    rid, pid = _rec_with_photo(client, "正常删除店")
    assert client.delete(f"/api/records/{rid}").status_code == 200
    assert client.get("/api/records").json() == []
    assert client.get(f"/api/photos/{pid}").status_code == 404


# ---------- 照片路径：统一正斜杠，跨系统可搬 ----------

def test_photo_path_uses_forward_slash(client):
    """path 不能存成 photos\\x.jpg：data/ 搬到 Linux/macOS 后反斜杠路径会失效。"""
    rid, pid = _rec_with_photo(client, "路径店")
    p = client.get(f"/api/records/{rid}").json()["photos"][0]
    assert p["path"] == f"photos/{pid}.jpg"
    assert "\\" not in p["path"]


def test_legacy_backslash_photo_path_is_normalized(client):
    """老库里可能存着 photos\\x.jpg：读的时候要能解析，init_db 时顺手改成 /。"""
    from app.db import init_db
    from app.main import _safe_photo_path

    # 读的时候两种写法解析到同一个文件
    assert _safe_photo_path("photos\\x.jpg") == _safe_photo_path("photos/x.jpg")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id,name,lng,lat,rating,tags,business_hours,avg_price,"
            "checkin_status,note,draft,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy-path", "路径店", 1, 1, 4, "[]", None, None, None, None, 0, 1, 1),
        )
        conn.execute(
            "INSERT INTO photos (id,record_id,path,thumb,created_at) VALUES (?,?,?,?,?)",
            ("legacy-pid", "legacy-path", "photos\\legacy.jpg", None, 1),
        )
    init_db()      # 幂等迁移：把反斜杠换成 /
    with get_conn() as conn:
        row = conn.execute("SELECT path FROM photos WHERE id='legacy-pid'").fetchone()
    assert row["path"] == "photos/legacy.jpg"


# ---------- 看板：照片数只统计非草稿 ----------

def test_dashboard_photo_total_excludes_drafts(client):
    rid = _create(client, name="有图店").json()["id"]
    client.post(f"/api/records/{rid}/photos",
                files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    did = _create(client, name="草稿店", draft=True).json()["id"]
    client.post(f"/api/records/{did}/photos",
                files={"file": ("b.jpg", _img_bytes(), "image/jpeg")})

    dash = client.get("/api/dashboard").json()
    assert dash["total"] == 1              # 记录数不含草稿
    assert dash["photos"]["total"] == 1    # 照片数也必须不含草稿照片
    assert dash["photos"]["records"] == 1
