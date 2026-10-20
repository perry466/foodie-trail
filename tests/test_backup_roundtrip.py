"""备份往返测试：导出 → 清库 → 导入，记录字段与照片字节必须能完整回来。

这是用户真正的灾备路径，之前只测了「导出里包含草稿」，没有测过导入能否还原。
"""
import base64
import io
import json

from PIL import Image


def _img_bytes(size=(40, 30), color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _export(client, mode="full") -> dict:
    r = client.get("/api/export", params={"mode": mode})
    assert r.status_code == 200, r.text
    return json.loads(r.content)


def _import(client, data: dict, confirm=True, progress=False):
    body = json.dumps(data, ensure_ascii=False).encode()
    params = {}
    if confirm:
        params["confirm"] = "true"
    if progress:
        params["progress"] = "1"
    return client.post("/api/import", params=params,
                       files={"file": ("backup.json", body, "application/json")})


def test_export_import_roundtrip_keeps_fields_and_photos(client):
    rid = client.post("/api/records", json={
        "name": "往返老店", "lng": 121.47, "lat": 31.23, "rating": 5,
        "tags": ["本帮菜", "老字号"], "avgPrice": 88,
        "businessHours": "10:00-21:00", "checkinStatus": "visited",
        "note": "红烧肉很好", "draft": False,
    }).json()["id"]
    client.post(f"/api/records/{rid}/photos",
                files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    client.post("/api/records", json={
        "name": "草稿店", "lng": 121.5, "lat": 31.24, "rating": 3, "draft": True,
    })

    backup = _export(client)
    assert len(backup["records"]) == 2
    exported = next(r for r in backup["records"] if r["name"] == "往返老店")
    assert exported["photos"] and exported["photos"][0]["data"]

    # 清库：模拟换机/重装后从备份恢复
    for rec in client.get("/api/records", params={"includeDrafts": 1}).json():
        client.delete(f"/api/records/{rec['id']}")
    assert client.get("/api/records", params={"includeDrafts": 1}).json() == []

    res = _import(client, backup)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["written"] == 2, body
    assert body["invalid"] == 0
    assert body["photosSkipped"] == 0

    rows = client.get("/api/records", params={"includeDrafts": 1}).json()
    assert sorted(r["name"] for r in rows) == sorted(["往返老店", "草稿店"])
    back = next(r for r in rows if r["name"] == "往返老店")
    assert back["tags"] == ["本帮菜", "老字号"]
    assert back["avgPrice"] == 88
    assert back["businessHours"] == "10:00-21:00"
    assert back["checkinStatus"] == "visited"
    assert back["note"] == "红烧肉很好"
    assert back["rating"] == 5
    # 草稿标记必须保留，否则"恢复备份"会把草稿偷偷转正
    assert next(r for r in rows if r["name"] == "草稿店")["draft"] is True

    # 照片不仅记录要回来，实际字节也要能取到
    assert back.get("cover")
    photo = client.get(f"/api/photos/{back['cover']}")
    assert photo.status_code == 200
    assert photo.content[:2] == b"\xff\xd8"


def test_import_preview_does_not_write(client):
    backup = {"app": "foodmap", "version": 2, "records": [
        {"id": "p1", "name": "预览店", "lng": 1, "lat": 1, "rating": 4},
    ]}
    res = _import(client, backup, confirm=False)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["preview"] is True
    assert body["append"] == 1
    assert client.get("/api/records").json() == []


def test_import_skips_missing_photo_data_without_losing_record(client):
    backup = {"app": "foodmap", "records": [
        {"id": "x1", "name": "缺照片店", "lng": 1, "lat": 1, "rating": 4,
         "photos": [{"id": "p"}, {"data": ""}, {"data": "!!!"}]},
    ]}
    body = _import(client, backup).json()
    assert body["written"] == 1
    assert body["photosSkipped"] == 3
    rec = client.get("/api/records/x1").json()
    assert rec["name"] == "缺照片店"
    assert rec.get("cover") is None


def test_import_progress_stream_reports_counts(client):
    backup = {"app": "foodmap", "records": [
        {"id": f"g{i}", "name": f"店{i}", "lng": 1, "lat": 1, "rating": 4}
        for i in range(3)
    ]}
    res = _import(client, backup, progress=True)
    assert res.status_code == 200
    events = [json.loads(line) for line in res.text.strip().splitlines() if line.strip()]
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert events[-1]["written"] == 3
    assert events[-1]["photosSkipped"] == 0


# ---------- 照片替换必须「先校验后替换」 ----------

def _record_with_photo(client, rid="keep1"):
    """建一条带 1 张真实照片的记录，返回照片 id。"""
    client.post("/api/records", json={
        "id": rid, "name": "有照片的店", "lng": 121.4, "lat": 31.2, "rating": 4,
    })
    client.post(f"/api/records/{rid}/photos",
                files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    photos = client.get(f"/api/records/{rid}").json()["photos"]
    assert len(photos) == 1
    return photos[0]["id"]


def _newer(**over):
    """构造一份 updatedAt 比库里更新的记录（保证会覆盖，而不是被 skip）。"""
    import time

    rec = {
        "lng": 1.0, "lat": 1.0, "rating": 4,
        "updatedAt": int(time.time() * 1000) + 60_000,
    }
    rec.update(over)
    return rec


def test_corrupt_photos_in_backup_keep_existing_photos(client):
    """P1 回归：备份照片损坏时，原有照片必须原样保留。

    复现：已有 1 张照片 + 一份 updatedAt 更新但照片 base64 损坏的完整备份。
    旧实现先删旧照片再逐张解码，损坏被跳过 → 照片归零。现在必须 still 1 张。
    """
    pid = _record_with_photo(client)
    backup = {"app": "foodmap", "version": 2, "photosIncluded": True, "records": [
        _newer(id="keep1", name="改名后的店", photosIncluded=True,
               photos=[{"data": "!!!not-base64!!!"}]),
    ]}
    body = _import(client, backup).json()
    assert body["written"] == 1
    assert body["photosSkipped"] == 1
    assert body["photosKept"] == 1

    rec = client.get("/api/records/keep1").json()
    assert rec["name"] == "改名后的店"          # 记录字段照常更新
    assert [p["id"] for p in rec["photos"]] == [pid]   # 旧照片还在
    assert client.get(f"/api/photos/{pid}").status_code == 200   # 文件也没被删


def test_non_image_photo_in_backup_also_keeps_existing(client):
    """伪装成图片的 HTML 同样属于「照片集不完整」，不能因此清空旧照片。"""
    pid = _record_with_photo(client, "keep2")
    payload = base64.b64encode(b"<html><script>alert(1)</script></html>").decode()
    backup = {"app": "foodmap", "photosIncluded": True, "records": [
        _newer(id="keep2", name="有照片的店", photos=[{"data": payload}]),
    ]}
    body = _import(client, backup).json()
    assert body["photosKept"] == 1
    assert client.get(f"/api/photos/{pid}").status_code == 200


def test_partial_photo_set_is_not_applied(client):
    """3 张里 1 张损坏 → 整批不采用（不留半套照片），旧照片保留。"""
    pid = _record_with_photo(client, "keep3")
    good = base64.b64encode(_img_bytes()).decode()
    backup = {"app": "foodmap", "photosIncluded": True, "records": [
        _newer(id="keep3", name="有照片的店", photos=[
            {"data": good}, {"data": "!!!"}, {"data": good},
        ]),
    ]}
    body = _import(client, backup).json()
    assert body["photosSkipped"] == 1
    assert body["photosKept"] == 1
    rec = client.get("/api/records/keep3").json()
    assert [p["id"] for p in rec["photos"]] == [pid]


def test_valid_photos_still_replace_old_ones(client):
    """健康备份仍要正常覆盖：新照片生效、旧文件真的删掉。"""
    pid = _record_with_photo(client, "swap1")
    good = base64.b64encode(_img_bytes(color=(200, 30, 30))).decode()
    backup = {"app": "foodmap", "photosIncluded": True, "records": [
        _newer(id="swap1", name="有照片的店", photosIncluded=True,
               photos=[{"data": good}]),
    ]}
    body = _import(client, backup).json()
    assert body["photosSkipped"] == 0
    assert body["photosKept"] == 0
    rec = client.get("/api/records/swap1").json()
    assert len(rec["photos"]) == 1
    assert rec["photos"][0]["id"] != pid
    assert client.get(f"/api/photos/{pid}").status_code == 404   # 旧文件已清理


def test_explicit_empty_photo_set_clears_old_photos(client):
    """photosIncluded=true + 空数组 = 用户确实删光了照片，此时才允许清空。"""
    pid = _record_with_photo(client, "clear1")
    backup = {"app": "foodmap", "photosIncluded": True, "records": [
        _newer(id="clear1", name="有照片的店", photosIncluded=True, photos=[]),
    ]}
    body = _import(client, backup).json()
    assert body["photosKept"] == 0
    assert client.get("/api/records/clear1").json()["photos"] == []
    assert client.get(f"/api/photos/{pid}").status_code == 404


def test_meta_backup_does_not_touch_photos(client):
    """mode=meta 导出（photosIncluded=false）只恢复元数据，不动照片。"""
    pid = _record_with_photo(client, "meta1")
    backup = {"app": "foodmap", "version": 2, "photosIncluded": False, "records": [
        _newer(id="meta1", name="改名后的店", photosIncluded=False, photos=[]),
    ]}
    body = _import(client, backup).json()
    assert body["photosKept"] == 1
    rec = client.get("/api/records/meta1").json()
    assert rec["name"] == "改名后的店"
    assert [p["id"] for p in rec["photos"]] == [pid]
    assert client.get(f"/api/photos/{pid}").status_code == 200


def test_legacy_backup_with_empty_photos_keeps_existing(client):
    """更早的备份没有 photosIncluded 标记、photos 为空 → 保守保留旧照片。"""
    pid = _record_with_photo(client, "legacy1")
    backup = {"app": "foodmap", "version": 2, "records": [
        _newer(id="legacy1", name="改名后的店", photos=[]),
    ]}
    body = _import(client, backup).json()
    assert body["photosKept"] == 1
    assert client.get(f"/api/photos/{pid}").status_code == 200


def test_export_declares_photos_included(client):
    """导出必须带「是否含照片」的契约，导入方才有依据决定能否清空旧照片。"""
    rid = client.post("/api/records", json={
        "name": "契约店", "lng": 1, "lat": 1, "rating": 4,
    }).json()["id"]
    client.post(f"/api/records/{rid}/photos",
                files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})

    full = _export(client, "full")
    assert full["photosIncluded"] is True
    assert full["records"][0]["photosIncluded"] is True

    meta = _export(client, "meta")
    assert meta["photosIncluded"] is False
    assert meta["records"][0]["photosIncluded"] is False
    assert meta["records"][0]["photos"] == []


def test_import_leaves_no_part_temp_files(client):
    """暂存文件必须清理干净，photos/ 里只留正式 .jpg。"""
    import os

    from app.pathconf import PHOTOS_DIR

    _record_with_photo(client, "tmp1")
    backup = {"app": "foodmap", "photosIncluded": True, "records": [
        _newer(id="tmp1", name="有照片的店", photos=[{"data": "!!!"}]),
    ]}
    _import(client, backup)
    assert [n for n in os.listdir(PHOTOS_DIR) if n.endswith(".part")] == []
