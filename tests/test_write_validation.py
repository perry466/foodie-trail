"""写接口校验：API 与导入必须共用同一套规则。

之前 RecordIn 只严格校验店名/坐标/星级，avgPrice、checkinStatus、note
都是「先写进去、读出来再变 null」——用户会以为数据丢了；重复 id 直接 500。
"""
import base64
import io
import json
import time

from PIL import Image


def _img_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (24, 18), (10, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def _create(client, **over):
    payload = {"name": "测试店", "lng": 116.4, "lat": 39.9, "rating": 4}
    payload.update(over)
    return client.post("/api/records", json=payload)


# ---------- 人均价位 ----------

def test_out_of_range_price_is_rejected_not_silently_nulled(client):
    """-5 / 100001 以前返回 201，但读回来是 null；现在必须在入口 422。"""
    for bad in (-5, 100001, -100000):
        r = _create(client, avgPrice=bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)
        detail = json.dumps(r.json(), ensure_ascii=False)
        assert "人均" in detail
    assert client.get("/api/records").json() == []      # 一条都没写进去


def test_price_boundaries_are_accepted(client):
    for price in (0, 100000):
        assert _create(client, avgPrice=price).status_code == 201
    rows = client.get("/api/records").json()
    assert sorted(r["avgPrice"] for r in rows) == [0, 100000]


def test_price_string_is_normalized(client):
    r = _create(client, avgPrice="88")
    assert r.status_code == 201, r.text
    assert r.json()["avgPrice"] == 88


# ---------- 打卡状态 ----------

def test_unknown_checkin_status_is_rejected(client):
    r = _create(client, checkinStatus="nonsense")
    assert r.status_code == 422
    assert "want" in json.dumps(r.json(), ensure_ascii=False)


def test_checkin_status_case_and_blank(client):
    assert _create(client, checkinStatus="VISITED ").json()["checkinStatus"] == "visited"
    assert _create(client, checkinStatus="").json()["checkinStatus"] is None
    assert _create(client, checkinStatus=None).json()["checkinStatus"] is None


# ---------- 文本长度 ----------

def test_overlong_note_is_rejected(client):
    r = _create(client, note="长" * 5000)
    assert r.status_code == 422
    assert "2000" in json.dumps(r.json(), ensure_ascii=False)

    ok = _create(client, note="长" * 2000)
    assert ok.status_code == 201
    assert len(ok.json()["note"]) == 2000


def test_overlong_business_hours_is_rejected(client):
    r = _create(client, businessHours="0" * 200)
    assert r.status_code == 422


def test_text_is_trimmed(client):
    rec = _create(client, note="  好吃  ").json()
    assert rec["note"] == "好吃"


# ---------- 记录 id ----------

def test_duplicate_id_returns_409(client):
    assert _create(client, id="fixed-1").status_code == 201
    r = _create(client, id="fixed-1")
    assert r.status_code == 409, r.text


def test_unsafe_id_is_rejected(client):
    for bad in ("a/b", "a b", "a?b", "a#b", "x" * 65):
        r = _create(client, id=bad)
        assert r.status_code == 422, (bad, r.status_code)


def test_safe_id_is_accepted(client):
    assert _create(client, id="ok_ID-123").status_code == 201
    assert client.get("/api/records/ok_ID-123").status_code == 200


# ---------- 坐标转换 ----------

def test_coords_convert_rejects_bad_numbers(client):
    for body in ({"lng": "abc", "lat": 39.9}, {"lng": 116.4, "lat": None},
                 {"lng": 999, "lat": 39.9}, {"lng": 116.4, "lat": "NaN"}):
        r = client.post("/api/coords/convert", json=body)
        assert r.status_code == 400, (body, r.status_code, r.text)


def test_coords_convert_still_works(client):
    r = client.post("/api/coords/convert", json={"lng": 116.404, "lat": 39.915})
    assert r.status_code == 200
    assert abs(r.json()["lng"] - 116.404) < 0.01


# ---------- 导入侧：id 与时间戳 ----------

def _import(client, records, confirm=True, progress=False):
    body = {"app": "foodmap", "version": 2, "photosIncluded": True, "records": records}
    params = {}
    if confirm:
        params["confirm"] = "true"
    if progress:
        params["progress"] = "1"
    return client.post("/api/import", params=params,
                       files={"file": ("b.json", json.dumps(body).encode(), "application/json")})


def test_import_replaces_unsafe_id_with_new_one(client):
    """id 含 `/` 会让详情接口 404（`a/b` 被当成两段路径），导入时换成 uuid。"""
    body = _import(client, [{"id": "a/b", "name": "斜杠店", "lng": 1, "lat": 1, "rating": 4}]).json()
    assert body["written"] == 1
    assert body["idsRenamed"] == 1

    rows = client.get("/api/records").json()
    assert len(rows) == 1
    new_id = rows[0]["id"]
    assert "/" not in new_id
    assert client.get(f"/api/records/{new_id}").status_code == 200


def test_import_keeps_safe_id(client):
    body = _import(client, [{"id": "keep-1", "name": "正常店", "lng": 1, "lat": 1, "rating": 4}]).json()
    assert body["idsRenamed"] == 0
    assert client.get("/api/records/keep-1").status_code == 200


def test_huge_timestamp_does_not_break_dashboard(client):
    """10^17 毫秒超出 datetime 范围，以前会写进库、然后把 /api/dashboard 打成 500。"""
    body = _import(client, [{
        "id": "ts1", "name": "时间戳店", "lng": 1, "lat": 1, "rating": 4,
        "createdAt": 10 ** 17, "updatedAt": 10 ** 17,
    }]).json()
    assert body["written"] == 1
    assert client.get("/api/dashboard").status_code == 200
    rec = client.get("/api/records/ts1").json()
    assert rec["createdAt"] <= int(time.time() * 1000) + 60_000   # 回落成 now


def test_normal_timestamps_survive(client):
    ts = int(time.time() * 1000) - 86_400_000
    _import(client, [{"id": "ts2", "name": "昨天店", "lng": 1, "lat": 1,
                      "rating": 4, "createdAt": ts, "updatedAt": ts}])
    assert client.get("/api/records/ts2").json()["createdAt"] == ts
    assert client.get("/api/dashboard").status_code == 200


def test_non_progress_import_reports_failed_count(client, monkeypatch):
    """非进度导入以前遇到写入异常只打印日志，返回 written=0 invalid=0，调用方无从判断。"""
    from app import main

    real = main._write_import_record

    def flaky(payload, photos, photos_included=False):
        if payload["name"] == "会失败":
            raise RuntimeError("boom")
        return real(payload, photos, photos_included)

    monkeypatch.setattr(main, "_write_import_record", flaky)
    body = _import(client, [
        {"id": "f1", "name": "会失败", "lng": 1, "lat": 1, "rating": 4},
        {"id": "f2", "name": "能成功", "lng": 1, "lat": 1, "rating": 4},
    ]).json()
    assert body["written"] == 1
    assert body["failed"] == 1
    assert body["invalid"] == 0


def test_progress_import_reports_failed_count(client, monkeypatch):
    from app import main

    real = main._write_import_record

    def flaky(payload, photos, photos_included=False):
        if payload["name"] == "会失败":
            raise RuntimeError("boom")
        return real(payload, photos, photos_included)

    monkeypatch.setattr(main, "_write_import_record", flaky)
    res = _import(client, [
        {"id": "g1", "name": "会失败", "lng": 1, "lat": 1, "rating": 4},
        {"id": "g2", "name": "能成功", "lng": 1, "lat": 1, "rating": 4},
    ], progress=True)
    events = [json.loads(x) for x in res.text.strip().splitlines() if x.strip()]
    assert events[-1]["type"] == "done"
    assert events[-1]["written"] == 1
    assert events[-1]["failed"] == 1


# ---------- 边界：导出仍可用（回归保护） ----------

def test_export_still_works_after_validation_changes(client):
    rid = _create(client, name="导出店", avgPrice=88, note="备注").json()["id"]
    client.post(f"/api/records/{rid}/photos",
                files={"file": ("a.jpg", _img_bytes(), "image/jpeg")})
    backup = json.loads(client.get("/api/export", params={"mode": "full"}).content)
    rec = next(r for r in backup["records"] if r["id"] == rid)
    assert rec["avgPrice"] == 88
    assert rec["photos"] and base64.b64decode(rec["photos"][0]["data"])[:2] == b"\xff\xd8"


# ---------- 营业时间：完整一周排班必须能存、能读、能导出导入 ----------
WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _week(slots_per_day=1):
    """前端 serializeHours() 的真实格式：紧凑 JSON、周一到周日。"""
    if slots_per_day == 1:
        day = [{"s": "10:00", "e": "21:00"}]
    else:
        day = [{"s": "11:00", "e": "14:00"}, {"s": "17:00", "e": "21:00"}]
    return json.dumps({k: day for k in WEEK}, separators=(",", ":"))


def test_full_week_schedule_can_be_saved(client):
    """回归：MAX_HOURS_LEN=120 曾把 239/421 字的正常排班直接 422。"""
    for n in (1, 2):
        hours = _week(n)
        assert len(hours) > 120
        r = _create(client, name=f"排班{n}", businessHours=hours)
        assert r.status_code == 201, (n, r.status_code, r.text)
        assert client.get(f"/api/records/{r.json()['id']}").json()["businessHours"] == hours


def test_full_week_schedule_editing_existing_record(client):
    """已有排班记录重新编辑保存也不能失败。"""
    rid = _create(client, name="老排班", businessHours=_week(2)).json()["id"]
    body = {"name": "老排班", "lng": 116.4, "lat": 39.9, "rating": 4, "businessHours": _week(2)}
    r = client.put(f"/api/records/{rid}", json=body)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/records/{rid}").json()["businessHours"] == _week(2)


def test_full_week_schedule_export_import_roundtrip(client):
    hours = _week(2)
    _create(client, id="hours-1", name="排班店", businessHours=hours)

    backup = json.loads(client.get("/api/export", params={"mode": "meta"}).content)
    exported = next(r for r in backup["records"] if r["id"] == "hours-1")
    assert exported["businessHours"] == hours          # 导出不截断

    for rec in client.get("/api/records").json():
        client.delete(f"/api/records/{rec['id']}")
    assert client.get("/api/records").json() == []

    body = _import(client, backup["records"]).json()
    assert body["written"] == 1
    assert client.get("/api/records/hours-1").json()["businessHours"] == hours


def test_hours_structure_is_sanitized(client):
    """越界时间、坏时段、未知星期都要被结构校验清掉，而不是整条拒收。"""
    messy = json.dumps({
        "mon": [{"s": "09:00", "e": "18:00"}, {"s": "25:00", "e": "26:00"}, "junk"],
        "tue": [{"s": "bad", "e": "x"}],
        "xyz": [{"s": "01:00", "e": "02:00"}],
    }, separators=(",", ":"))
    rec = _create(client, name="脏排班", businessHours=messy)
    assert rec.status_code == 201, rec.text
    saved = json.loads(rec.json()["businessHours"])
    assert saved["mon"] == [{"s": "09:00", "e": "18:00"}]
    assert saved["tue"] == []
    assert "xyz" not in saved
    assert set(saved) == set(WEEK)


def test_hours_rejects_broken_json(client):
    r = _create(client, businessHours='{"mon":[{"s":"10:0')
    assert r.status_code == 422
    assert "营业时间" in json.dumps(r.json(), ensure_ascii=False)


def test_hours_plain_text_still_capped(client):
    assert _create(client, businessHours="10:00-21:00").status_code == 201
    assert _create(client, businessHours="周一至周日 " + "0" * 200).status_code == 422


# ---------- 不安全 id：重复导入必须落回同一条记录 ----------

def test_unsafe_id_is_stable_across_repeated_imports(client):
    """uuid4 每次不同会每导一次多一条同名记录；现在用 uuid5 派生确定性 id。"""
    rec = {"id": "a/b", "name": "斜杠店", "lng": 1, "lat": 1, "rating": 4,
           "updatedAt": int(time.time() * 1000) + 60_000}
    first = _import(client, [rec]).json()
    assert first["written"] == 1 and first["idsRenamed"] == 1
    second = _import(client, [rec]).json()
    # 第二次要么被 updatedAt 判为「不必更新」（written=0），要么覆盖同一条；
    # 关键是不能多出一条同名记录
    assert second["idsRenamed"] == 1

    rows = client.get("/api/records").json()
    assert len(rows) == 1, [r["id"] for r in rows]
    assert rows[0]["name"] == "斜杠店"


def test_unsafe_id_mapping_is_deterministic():
    from app.validate import stable_record_id

    assert stable_record_id("a/b") == stable_record_id("a/b")
    assert stable_record_id("a/b") != stable_record_id("a?b")
    assert "/" not in stable_record_id("a/b")
    assert stable_record_id("safe-1") == "safe-1"


# ---------- 0 元：API / 看板 / 表单同口径 ----------

def test_zero_price_is_a_real_price(client):
    _create(client, name="免费店", avgPrice=0)
    _create(client, name="收费店", avgPrice=50)

    rows = client.get("/api/records").json()
    assert sorted(r["avgPrice"] for r in rows) == [0, 50]

    dash = client.get("/api/dashboard").json()
    assert dash["price"]["min"] == 0                      # 0 参与统计
    assert dash["quality"]["noPrice"] == 0                # 不算"缺人均"
    assert sum(b["count"] for b in dash["price"]["buckets"]) == 2


# ---------- 坐标转换：错误 body 不能 500 ----------

def test_coords_convert_bad_bodies_are_4xx(client):
    for raw in (b"null", b"[]", b'"abc"', b"", b"{bad json"):
        r = client.post("/api/coords/convert", content=raw,
                        headers={"Content-Type": "application/json"})
        assert r.status_code in (400, 422), (raw, r.status_code)
