"""应用内更新：版本比较、缓存策略、失败静默、安装前置校验。

这一组用例**全部不联网**——一律 monkeypatch `update._fetch_latest`。
更新功能最怕两件事：GitHub 不通时把应用搞崩，以及版本号比错导致永久提示。
"""
import json
import os
import time

import pytest

import app.update as upd
from app.version import VERSION

ASSETS = [
    {"name": "FoodieTrail-9.9.9-windows-x64.zip", "size": 10,
     "browser_download_url": "https://example.invalid/z.zip", "digest": "sha256:aa"},
    {"name": "FoodieTrail-9.9.9-windows-x64-setup.exe", "size": 20,
     "browser_download_url": "https://example.invalid/s.exe", "digest": "sha256:bb"},
]


def _release(latest="9.9.9", checked_at=None):
    return {
        "checkedAt": int(checked_at if checked_at is not None else time.time()),
        "latest": latest,
        "tag": "v" + latest,
        "notes": "修了几个问题",
        "publishedAt": "2026-10-21T00:00:00Z",
        "htmlUrl": f"https://example.invalid/releases/tag/v{latest}",
        "setup": upd._pick_asset(ASSETS, "-setup.exe"),
        "zip": upd._pick_asset(ASSETS, ".zip"),
    }


def _clear_cache():
    try:
        os.remove(upd.UPDATE_CACHE_PATH)
    except OSError:
        pass


# ---------- 版本比较 ----------
def test_version_compare_is_numeric_not_string():
    """1.0.10 必须大于 1.0.9。

    字符串比较下 "1.0.10" < "1.0.9" 成立，第 10 个补丁版本发出来之后
    用户永远收不到提示——这是更新功能最经典的翻车方式。
    """
    assert upd.compare_versions("1.0.10", "1.0.9") == 1
    assert upd.compare_versions("1.0.9", "1.0.10") == -1
    assert upd.compare_versions("v1.0.1", "1.0.1") == 0
    assert upd.compare_versions("1.1", "1.1.0") == 0
    assert upd.compare_versions("2.0.0", "1.99.99") == 1


def test_parse_version_tolerates_prefix_and_suffix():
    assert upd.parse_version("v1.2.3") == (1, 2, 3)
    assert upd.parse_version("1.0.1-beta") == (1, 0, 1)
    assert upd.parse_version("") is None
    assert upd.parse_version(None) is None
    assert upd.parse_version("dev") is None


def test_unparsable_versions_are_treated_as_equal():
    """解析不出来时按"相同"处理：宁可这次不提示，也不能抛异常打断检查。"""
    assert upd.compare_versions("dev", "1.0.0") == 0


# ---------- 资产匹配 ----------
def test_pick_asset_matches_by_suffix():
    exe = upd._pick_asset(ASSETS, "-setup.exe")
    assert exe["name"].endswith("-setup.exe")
    assert exe["sha256"] == "bb"
    assert exe["size"] == 20
    zipf = upd._pick_asset(ASSETS, ".zip")
    assert zipf["name"].endswith(".zip")
    assert upd._pick_asset(ASSETS, ".tar.gz") is None
    assert upd._pick_asset(None, ".zip") is None


def test_missing_digest_blocks_auto_install(monkeypatch):
    """没有 sha256 就不允许自动装：下载完整性无法确认。"""
    rel = _release()
    rel["setup"] = {**rel["setup"], "sha256": ""}
    assert upd._build_result(rel)["canAutoInstall"] is False


# ---------- 缓存 ----------
def test_check_uses_cache_within_ttl(monkeypatch):
    calls = []

    def fake():
        calls.append(1)
        return _release()

    monkeypatch.setattr(upd, "_fetch_latest", fake)
    upd._write_cache(_release())
    r = upd.check()
    assert r["cached"] is True
    assert r["hasUpdate"] is True
    assert calls == []          # TTL 内一次网络请求都不发


def test_force_bypasses_cache(monkeypatch):
    calls = []

    def fake():
        calls.append(1)
        return _release()

    monkeypatch.setattr(upd, "_fetch_latest", fake)
    upd._write_cache(_release(latest="1.0.0"))
    r = upd.check(force=True)
    assert calls == [1]
    assert r["cached"] is False
    assert r["latest"] == "9.9.9"


def test_expired_cache_triggers_refresh(monkeypatch):
    """超过 6 小时的缓存必须重查，否则新版发布后第二天也不会提示。"""
    monkeypatch.setattr(upd, "_fetch_latest", lambda: _release(latest="9.9.9"))
    upd._write_cache(_release(latest="1.0.0", checked_at=0))
    r = upd.check()
    assert r["latest"] == "9.9.9" and r["cached"] is False


# ---------- 失败必须静默 ----------
def test_check_never_raises_on_network_error(monkeypatch):
    """GitHub 不通时返回 ok=false，绝不能让路由 500。"""
    _clear_cache()
    monkeypatch.setattr(upd, "_fetch_latest",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = upd.check(force=True)
    assert r["ok"] is False
    assert "boom" in r["reason"]
    assert r["current"] == VERSION


def test_stale_cache_used_when_refresh_fails(monkeypatch):
    """查不到但手里有旧结果：给旧结果并标记 stale，用户仍能看到下载入口。"""
    upd._write_cache(_release(latest="9.9.9", checked_at=0))
    monkeypatch.setattr(upd, "_fetch_latest",
                        lambda: (_ for _ in ()).throw(OSError("offline")))
    r = upd.check(force=True)
    assert r["ok"] is True and r.get("stale") is True
    assert r["hasUpdate"] is True


# ---------- 安装前置校验 ----------
def test_install_rejected_outside_installer_mode():
    if upd.detect_mode() == "installer":
        pytest.skip("当前是安装版环境，此用例不适用")
    with pytest.raises(upd.UpdateError) as e:
        upd.install()
    assert e.value.status == 409


def test_download_rejected_outside_installer_mode():
    if upd.detect_mode() == "installer":
        pytest.skip("当前是安装版环境，此用例不适用")
    with pytest.raises(upd.UpdateError) as e:
        upd.start_download()
    assert e.value.status == 409


def test_safe_download_path_rejects_traversal():
    for bad in ("../evil.exe", "..\\evil.exe", "/etc/passwd",
                "a/b.exe", "a\\b.exe", "FoodieTrail.zip", ""):
        with pytest.raises(upd.UpdateError):
            upd._safe_download_path(bad)


def test_safe_download_path_accepts_generated_name():
    p = upd._safe_download_path("FoodieTrail-9.9.9-windows-x64-setup.exe")
    assert os.path.dirname(p) == os.path.abspath(upd.DOWNLOADS_DIR)


def test_settings_declares_no_proxy_escape_hatch():
    """必须留一个「强制直连」的开关：某些机器必须走代理，另一些必须绕过。"""
    text = open(os.path.join(os.path.dirname(upd.__file__), "update.py"), encoding="utf-8").read()
    assert "FOODMAP_UPDATE_NO_PROXY" in text


# ---------- 接口 ----------
def test_version_endpoint(client):
    r = client.get("/api/app/version")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == VERSION
    assert body["mode"] in ("source", "portable", "installer")


def test_check_endpoint_returns_200_even_when_offline(client, monkeypatch):
    monkeypatch.setattr(upd, "check",
                        lambda force=False: {"ok": False, "reason": "offline", "current": VERSION})
    r = client.get("/api/update/check")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_install_endpoint_409_on_non_installer(client):
    if upd.detect_mode() == "installer":
        pytest.skip("当前是安装版环境，此用例不适用")
    r = client.post("/api/update/install")
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_download_progress_shape(client):
    r = client.get("/api/update/download")
    assert r.status_code == 200
    body = r.json()
    assert set(("state", "percent", "received", "total")).issubset(body)


def test_update_cache_is_valid_json(tmp_path):
    """缓存必须是可解析的 JSON：写坏一次就会让下次检查读不到。"""
    upd._write_cache(_release())
    with open(upd.UPDATE_CACHE_PATH, encoding="utf-8") as f:
        assert json.load(f)["latest"] == "9.9.9"
