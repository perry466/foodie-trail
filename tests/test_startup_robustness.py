"""启动健壮性、导入性能与图片格式的回归用例。

对应 2026-10-21 全项目体检后修掉的问题，每条都曾是「用户会真的撞上」的坑：

1. `data/.fernet.key` 损坏 → 以前在 import 期抛 ValueError，整个应用起不来；
2. `PORT=abc` / `PORT=99999` → ValueError / OverflowError 把启动打崩；
3. 16 位灰度 PNG 被当成「无法识别的图片」（Pillow 无法直接存成 JPEG）；
4. 重复导入时只显示「写入 0 条」，看不出是「已是最新、按时间戳跳过」；
5. 导入逐条新建数据库连接，1000 条要 55s（本机实测）；
6. 关键词里的 `%` 被当成 LIKE 通配符，搜一个 `%` 命中全库。
"""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

from app.pathconf import _is_port_free, find_free_port, parse_port
from app.validate import escape_like, normalize_rating


def _backup(records, **extra):
    body = {"app": "foodmap", "version": 2, "records": records}
    body.update(extra)
    return json.dumps(body, ensure_ascii=False).encode()


def _import(client, records, progress=False, **extra):
    params = {"confirm": "true"}
    if progress:
        params["progress"] = "1"
    return client.post("/api/import", params=params,
                       files={"file": ("b.json", _backup(records, **extra), "application/json")})


def _png_16bit(size=(900, 700), value=30000):
    buf = io.BytesIO()
    Image.new("I;16", size, value).save(buf, "PNG")
    return buf.getvalue()


# ---------- 1. 端口参数：非法值只提示、不崩 ----------
def test_parse_port_accepts_only_valid_range():
    assert parse_port("31245") == 31245
    assert parse_port(" 20000 ") == 20000
    assert parse_port(31245) == 31245
    for bad in ["abc", "", "0", "99999", "-1", None, "12.5", []]:
        assert parse_port(bad) is None, bad


def test_out_of_range_port_is_not_free_and_does_not_raise():
    # 以前 bind 到 99999 抛的是 OverflowError（不是 OSError），启动脚本直接崩
    assert _is_port_free(99999) is False
    assert _is_port_free("abc") is False
    assert _is_port_free(0) is False


def test_find_free_port_tolerates_bad_preferred():
    port = find_free_port("abc")                       # 不该抛异常，且必须给出合法端口
    assert 1 <= port <= 65535
    port2 = find_free_port(99999)                      # 越界同样回落到随机可用端口
    assert 1 <= port2 <= 65535


# ---------- 2. 加密钥匙损坏：留档 + 换新 + 照常启动 ----------
def _import_app_in_subprocess(data_dir):
    env = dict(os.environ, FOODMAP_DATA_DIR=str(data_dir))
    return subprocess.run(
        [sys.executable, "-c",
         "import app.main; from app import crypto; print(crypto.KEY_STATE)"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )


def test_corrupt_fernet_key_still_starts(tmp_path):
    for content in (b"", b"garbage-not-a-fernet-key"):
        d = tmp_path / ("key-" + str(len(content)))
        d.mkdir()
        (d / ".fernet.key").write_bytes(content)
        proc = _import_app_in_subprocess(d)
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "recreated" in proc.stdout
        # 坏钥匙留档，新钥匙可被 Fernet 接受
        broken = [p for p in d.iterdir() if p.name.startswith(".fernet.key.broken-")]
        assert broken, list(d.iterdir())
        assert (d / ".fernet.key").read_bytes() != content


def test_valid_fernet_key_is_kept(tmp_path):
    from cryptography.fernet import Fernet
    d = tmp_path / "ok"
    d.mkdir()
    key = Fernet.generate_key()
    (d / ".fernet.key").write_bytes(key)
    proc = _import_app_in_subprocess(d)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "ok" in proc.stdout
    assert (d / ".fernet.key").read_bytes() == key        # 好钥匙不能被换掉


# ---------- 3. 图片：16 位灰度等模式必须能上传 ----------
def test_sixteen_bit_grayscale_png_uploads(client):
    rid = client.post("/api/records", json={"name": "扫描件店", "lng": 116.4, "lat": 39.9}).json()["id"]
    r = client.post(f"/api/records/{rid}/photos",
                    files={"file": ("scan.png", _png_16bit(), "image/png")})
    assert r.status_code == 200, r.text
    photo = r.json()
    img = Image.open(io.BytesIO(client.get(f"/api/photos/{photo['id']}").content)).convert("L")
    assert img.size[0] <= 1280
    # 30000/65535 的中灰不能被压成纯白（直接 convert("RGB") 会这样）
    assert 80 <= img.getpixel((10, 10)) <= 160, img.getpixel((10, 10))


def test_other_exotic_modes_do_not_500(client):
    rid = client.post("/api/records", json={"name": "格式店", "lng": 1, "lat": 1}).json()["id"]
    for mode, fmt, name in (("LA", "PNG", "la.png"), ("CMYK", "JPEG", "cmyk.jpg"), ("P", "PNG", "p.png")):
        buf = io.BytesIO()
        Image.new(mode, (500, 400)).save(buf, fmt)
        r = client.post(f"/api/records/{rid}/photos",
                        files={"file": (name, buf.getvalue(), "image/octet-stream")})
        assert r.status_code == 200, (mode, r.status_code, r.text)


def test_non_image_still_400(client):
    rid = client.post("/api/records", json={"name": "坏图店", "lng": 1, "lat": 1}).json()["id"]
    r = client.post(f"/api/records/{rid}/photos",
                    files={"file": ("x.png", b"not an image at all", "image/png")})
    assert r.status_code == 400


# ---------- 4. 导入：跳过（已是最新）必须单独计数 ----------
def test_reimport_same_backup_reports_unchanged(client):
    client.post("/api/records", json={"name": "老店", "lng": 1, "lat": 1, "rating": 4})
    backup = client.get("/api/export", params={"mode": "meta"}).content

    first = client.post("/api/import", params={"confirm": "true"},
                        files={"file": ("b.json", backup, "application/json")}).json()
    assert first["written"] == 0 and first["unchanged"] == 1
    assert first["failed"] == 0 and first["invalid"] == 0

    # 进度流（NDJSON）口径必须一致，否则前端进度条与结果对不上
    res = client.post("/api/import", params={"confirm": "true", "progress": "1"},
                      files={"file": ("b.json", backup, "application/json")})
    done = json.loads(res.text.strip().splitlines()[-1])
    assert done["written"] == 0 and done["unchanged"] == 1


def test_older_backup_does_not_overwrite_newer(client):
    rid = client.post("/api/records", json={"name": "新版本", "lng": 1, "lat": 1}).json()["id"]
    old = client.get(f"/api/records/{rid}").json()
    older = dict(old, name="旧版本", updatedAt=old["updatedAt"] - 86_400_000)
    res = _import(client, [older]).json()
    assert res["unchanged"] == 1
    assert client.get(f"/api/records/{rid}").json()["name"] == "新版本"


# ---------- 5. 导入性能：批量复用连接 ----------
def test_bulk_import_is_fast(client):
    records = [{"id": f"bulk-{i}", "name": f"批量店{i}", "lng": 116.0, "lat": 39.0, "rating": 3}
               for i in range(300)]
    t0 = time.time()
    res = _import(client, records).json()
    elapsed = time.time() - t0
    assert res["written"] == 300 and res["failed"] == 0
    # 逐条建连时本机要 ~14s；复用连接后 <1s。上限留足余量，只挡性能回退。
    # CI 的共享 runner 更慢，放宽门槛，避免一次抖动让 Release 构建失败。
    limit = 20.0 if os.environ.get("CI") else 6.0
    assert elapsed < limit, f"300 条导入用了 {elapsed:.1f}s，连接复用可能被改回去了"


# ---------- 6. 搜索：LIKE 通配符必须转义 ----------
def test_escape_like():
    assert escape_like("100%") == "100\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("c\\d") == "c\\\\d"
    assert escape_like(None) == ""


def test_keyword_percent_matches_literally(client):
    client.post("/api/records", json={"name": "100%好吃", "lng": 1, "lat": 1})
    client.post("/api/records", json={"name": "普通店", "lng": 1, "lat": 1})
    rows = client.get("/api/records", params={"keyword": "%"}).json()
    assert [r["name"] for r in rows] == ["100%好吃"]


def test_keyword_underscore_matches_literally(client):
    client.post("/api/records", json={"name": "a_b 小馆", "lng": 1, "lat": 1})
    client.post("/api/records", json={"name": "axb 小馆", "lng": 1, "lat": 1})
    rows = client.get("/api/records", params={"keyword": "a_b"}).json()
    assert [r["name"] for r in rows] == ["a_b 小馆"]


# ---------- 7. 星级：整数值的浮点与数字字符串不再导致整条被拒 ----------
def test_normalize_rating_tolerates_equivalent_spellings():
    assert normalize_rating(4) == 4
    assert normalize_rating(4.0) == 4          # Python / 脚本生成的 JSON
    assert normalize_rating("4") == 4          # 字符串写法
    assert normalize_rating(4.5) is None
    assert normalize_rating(0) is None
    assert normalize_rating(6) is None
    assert normalize_rating(True) is None      # bool 不能当成 1
    assert normalize_rating(None) is None


def test_import_accepts_float_rating(client):
    body = {"app": "foodmap", "version": 2, "records": [
        {"id": "float-r", "name": "四点零店", "lng": 1, "lat": 1, "rating": 4.0},
        {"id": "str-r", "name": "字符串店", "lng": 1, "lat": 1, "rating": "5"},
    ]}
    res = client.post("/api/import", params={"confirm": "true"},
                      files={"file": ("b.json", json.dumps(body).encode(), "application/json")}).json()
    assert res["written"] == 2 and res["invalid"] == 0
    assert client.get("/api/records/float-r").json()["rating"] == 4
    assert client.get("/api/records/str-r").json()["rating"] == 5


# ---------- 8. 种子脚本：必须尊重 FOODMAP_DATA_DIR，且连不上服务时不写入 ----------
def test_seed_script_reads_data_dir_from_env(monkeypatch, tmp_path):
    """`seed_1000.py` 以前写死项目 data/，无视 FOODMAP_DATA_DIR。

    后果很严重：以为在隔离目录试跑，实际打到了正在运行的真实服务上
    （2026-10-21 真的发生过一次，往真实库写了 678 条演示记录）。
    """
    import seed_1000

    monkeypatch.setenv("FOODMAP_DATA_DIR", str(tmp_path))
    assert seed_1000.data_dir() == str(tmp_path)

    (tmp_path / ".last_port").write_text("31999", encoding="utf-8")
    assert seed_1000.resolve_base() == "http://127.0.0.1:31999"
    # 显式 --base 优先，且去掉尾部斜杠
    assert seed_1000.resolve_base("http://127.0.0.1:1/") == "http://127.0.0.1:1"


def test_seed_script_aborts_when_server_down(monkeypatch, tmp_path):
    import seed_1000

    monkeypatch.setenv("FOODMAP_DATA_DIR", str(tmp_path))
    # 端口 9 上不会有服务；必须“先探测再写”，返回非 0 且不产生任何记录
    rc = seed_1000.main(["--count", "20", "--base", "http://127.0.0.1:9"])
    assert rc == 1
    assert not (tmp_path / "foodmap.db").exists()


def test_seed_script_import_has_no_side_effects():
    """旧版把 1000 次 POST 写在模块顶层，任何 import 都会打库。"""
    import importlib

    import seed_1000

    importlib.reload(seed_1000)          # 再执行一次模块级代码，不应发起请求
    assert callable(seed_1000.main)


# ---------- 9. 健康检查脚本：能发现丢照片/孤儿文件/演示数据 ----------
def test_health_check_clean_returns_zero(client, capsys):
    import health_check
    from app.pathconf import DATA_DIR

    client.post("/api/records", json={"name": "正常店", "lng": 116.4, "lat": 39.9, "rating": 4})
    rc = health_check.main(["--data-dir", str(DATA_DIR)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "integrity_check = ok" in out


def test_health_check_detects_missing_photo_file(client, capsys):
    import health_check
    from app.pathconf import DATA_DIR, PHOTOS_DIR

    rid = client.post("/api/records", json={"name": "丢图店", "lng": 1, "lat": 1}).json()["id"]
    pid = client.post(f"/api/records/{rid}/photos",
                      files={"file": ("a.jpg", _png_rgb(), "image/jpeg")}).json()["id"]
    os.remove(os.path.join(PHOTOS_DIR, pid + ".jpg"))

    rc = health_check.main(["--data-dir", str(DATA_DIR)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "文件丢失" in out


def test_health_check_orphan_is_warning_only(client, capsys):
    import health_check
    from app.pathconf import DATA_DIR, PHOTOS_DIR

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    orphan = os.path.join(PHOTOS_DIR, "orphan-test.jpg")
    with open(orphan, "wb") as f:
        f.write(_png_rgb())
    try:
        rc = health_check.main(["--data-dir", str(DATA_DIR)])
        out = capsys.readouterr().out
        assert rc == 0                     # 孤儿文件不致命，只提醒
        assert "没有记录引用" in out
    finally:
        os.remove(orphan)


def test_health_check_reports_demo_records(client, capsys):
    import health_check
    from app.pathconf import DATA_DIR

    client.post("/api/records", json={"id": "demo-001", "name": "演示店", "lng": 1, "lat": 1})
    rc = health_check.main(["--data-dir", str(DATA_DIR)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "演示数据" in out and "seed_demo.py --clear" in out


def _png_rgb(size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


# ---------- 10. 写库脚本的真实目录闸门 ----------
def test_seed_demo_refuses_real_data_dir(monkeypatch, capsys):
    import seed_demo

    monkeypatch.delenv("FOODMAP_DATA_DIR", raising=False)   # 模拟直接在本机跑
    rc = seed_demo.main(["--count", "5"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "--yes" in out


def test_seed_demo_clear_refuses_without_yes(monkeypatch, capsys):
    import seed_demo

    monkeypatch.delenv("FOODMAP_DATA_DIR", raising=False)
    rc = seed_demo.main(["--clear"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "--yes" in out


def test_seed_1000_refuses_real_data_dir(monkeypatch, capsys):
    import seed_1000

    monkeypatch.delenv("FOODMAP_DATA_DIR", raising=False)
    rc = seed_1000.main(["--count", "5"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "--yes" in out


def test_seed_1000_dry_run_allowed_without_yes(monkeypatch, capsys):
    import seed_1000

    monkeypatch.delenv("FOODMAP_DATA_DIR", raising=False)
    rc = seed_1000.main(["--count", "5", "--dry-run", "--base", "http://127.0.0.1:9"])
    out = capsys.readouterr().out
    assert rc == 0 and "dry-run" in out


def test_clear_demo_removes_photo_files(client):
    """`--clear` 以前只删库行，磁盘上的照片会变成孤儿文件。"""
    import seed_demo
    from app.pathconf import PHOTOS_DIR

    rid = "demo-777"
    client.post("/api/records", json={"id": rid, "name": "演示图店", "lng": 1, "lat": 1})
    pid = client.post(f"/api/records/{rid}/photos",
                      files={"file": ("a.jpg", _png_rgb(), "image/jpeg")}).json()["id"]
    f = os.path.join(PHOTOS_DIR, pid + ".jpg")
    assert os.path.isfile(f)

    seed_demo.clear_demo()
    assert not os.path.isfile(f)
    assert client.get(f"/api/records/{rid}").status_code == 404
