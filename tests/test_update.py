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
    """GitHub 不通时返回 ok=false，绝不能让路由 500。

    reason 要是人话：异常名只做括号里的线索（"网络连接失败（RuntimeError）…"），
    不能像以前那样直接把 `RuntimeError: boom` 甩给用户。
    """
    _clear_cache()
    monkeypatch.setattr(upd, "_fetch_latest",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = upd.check(force=True)
    assert r["ok"] is False
    assert r["reason"].startswith("网络连接失败")
    assert "RuntimeError" in r["reason"]
    assert "boom" not in r["reason"]          # 异常详情不外泄
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


def test_install_spawns_cmd_chain_as_plain_string(monkeypatch, tmp_path):
    """cmd 链必须以**字符串**传给 Popen，且只用 CREATE_NO_WINDOW。

    v1.0.7 真机踩中：用列表传参时 Popen 做 list2cmdline，把链里的引号转义成
    `\\"`，而 cmd 不认 `\\"`，`start ""` 被拆成 `start \\`，
    用户看到「Windows 找不到 '\\' 文件」；DETACHED_PROCESS 与
    CREATE_NO_WINDOW 同用语义矛盾，还会弹出 ping 的黑窗。
    """
    target = tmp_path / "FoodieTrail-9.9.9-windows-x64-setup.exe"
    target.write_bytes(b"x" * 20)                      # 与 _release() 里的 size 一致
    monkeypatch.setattr(upd, "detect_mode", lambda: "installer")
    monkeypatch.setattr(upd, "_read_cache", lambda: _release())
    monkeypatch.setattr(upd, "_safe_download_path", lambda name: str(target))
    monkeypatch.setattr(upd.os, "name", "nt")
    monkeypatch.setattr(upd.sys, "executable", r"C:\app\FoodieTrail.exe")
    monkeypatch.setattr(upd, "_delayed_exit", lambda s: None)   # 不许真的退出
    captured = {}

    def fake_popen(cmdline, **kw):
        captured["cmdline"] = cmdline
        captured["flags"] = kw.get("creationflags")

    monkeypatch.setattr(upd.subprocess, "Popen", fake_popen)
    result = upd.install()

    line = captured["cmdline"]
    assert isinstance(line, str) and line.startswith("cmd.exe /c ")
    assert '\\"' not in line                    # 不允许二次转义
    assert 'start "" /wait' in line             # start 的空标题要原样保留
    assert str(target) in line and "/VERYSILENT" in line
    assert captured["flags"] == 0x08000000      # 只用 CREATE_NO_WINDOW
    # 前端靠 version 在安装遮罩上写「正在安装 vX」，并在新进程里判断是否已更新
    assert result["version"] == "9.9.9", result
    assert result["willExit"] is True


def test_reveal_download_opens_fixed_directory_only(monkeypatch, tmp_path):
    """「打开安装包位置」只能打开服务端定的目录，且不接收任何参数。

    v1.0.2–v1.0.7 因为 cmd 链 bug 全部装不上，用户一个手动出口都没有；
    这个接口就是兜底，所以绝不能变成"打开任意路径"的口子。
    """
    opened = {}
    monkeypatch.setattr(upd, "DOWNLOADS_DIR", str(tmp_path))
    monkeypatch.setattr(upd.os, "name", "nt")
    monkeypatch.setattr(upd.os, "startfile",
                        lambda p: opened.setdefault("path", p), raising=False)
    assert upd.reveal_download()["ok"] is True
    assert opened["path"] == str(tmp_path)
    # 目录不存在时不能瞎开
    monkeypatch.setattr(upd, "DOWNLOADS_DIR", str(tmp_path / "nope"))
    with pytest.raises(upd.UpdateError) as e:
        upd.reveal_download()
    assert e.value.status == 409


def test_reveal_download_rejected_on_non_windows(monkeypatch):
    monkeypatch.setattr(upd.os, "name", "posix")
    with pytest.raises(upd.UpdateError) as e:
        upd.reveal_download()
    assert e.value.status == 409


def test_download_error_messages_are_human():
    """下载失败提示里不许出现异常原文（v1.0.7 用户看到过 SSL: UNEXPECTED_EOF...）。"""
    assert upd._download_error_msg(upd.UpdateError("没有校验值")) == "没有校验值"
    ssl_err = RuntimeError("ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] "
                           "EOF occurred in violation of protocol (_ssl.c:1010)")
    msg = upd._download_error_msg(ssl_err)
    assert "SSL" not in msg and "EOF" not in msg and "中断" in msg
    assert "超时" in upd._download_error_msg(RuntimeError("read timed out"))
    assert "RuntimeError" in upd._download_error_msg(RuntimeError("weird thing"))


def test_settings_declares_no_proxy_escape_hatch():
    """必须留一个「强制直连」的开关：某些机器必须走代理，另一些必须绕过。"""
    text = open(os.path.join(os.path.dirname(upd.__file__), "update.py"), encoding="utf-8").read()
    assert "FOODMAP_UPDATE_NO_PROXY" in text


# ---------- 403 的三种原因要说清楚 ----------
def _resp(headers):
    class R:
        pass
    r = R()
    r.headers = headers
    r.status_code = 403
    return r


def test_rate_limit_hint_distinguishes_quota_from_burst():
    """GitHub 的两种 403 长得一样但处置完全不同，文案必须分开。

    用户装上 v1.0.2 后连点「检查更新」拿到的是次级限流（额度还有，照样 403），
    如果只显示「HTTP 403」，他会以为更新功能坏了。
    """
    burst = upd._rate_limit_hint(_resp({"x-ratelimit-remaining": "42", "retry-after": "60"}))
    assert "60" in burst and "限制" in burst

    quota = upd._rate_limit_hint(_resp({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}))
    assert "额度已用完" in quota

    other = upd._rate_limit_hint(_resp({}))
    assert "拒绝" in other


def test_fetch_latest_403_raises_with_actionable_message(monkeypatch):
    """403 时抛出的必须是能指导下一步的话，不是裸的状态码。

    v1.0.4 把 GitHub 的英文原文拼在了中文后面，用户看到一整段
    「API rate limit exceeded for 203.10.98.186. (But here's the good news:...)」
    ——那不是给人看的，还把用户 IP 泄露在了界面上。
    """
    class FakeClient:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, *a, **k):
            r = _resp({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"})
            r.json = lambda: {"message": "API rate limit exceeded for 203.0.113.9"}
            return r

    monkeypatch.setattr(upd.httpx, "Client", FakeClient)
    with pytest.raises(upd.UpdateError) as e:
        upd._fetch_latest()
    msg = e.value.message
    assert "额度" in msg
    assert "403" not in msg
    # 用户界面上不许出现 GitHub 的英文原文，也不许出现拼接分隔符
    assert "rate limit" not in msg.lower()
    assert "203.0.113.9" not in msg
    assert "｜" not in msg


def test_check_does_not_attempt_web_fallback(monkeypatch):
    """不做网页版兜底：国内网络下 github.com 整体不可达，只会多等 6–10 秒。"""
    assert not hasattr(upd, "_fetch_latest_from_web")


def test_cache_ttl_is_30_minutes():
    """6 小时太长：发版后最多 6 小时都提示不出来。有人改大之前先想想这一点。"""
    assert upd.CACHE_TTL == 30 * 60


def test_result_exposes_download_url_for_copying():
    """到不了 release-assets 域名的网络里，用户唯一的路是复制链接自己下。"""
    r = upd._build_result(_release())
    assert r["downloadUrl"] == "https://example.invalid/s.exe"
    assert r["downloadName"] == "FoodieTrail-9.9.9-windows-x64-setup.exe"
    assert r["downloadSize"] == 20


# ---------- 网络路径：直连与系统代理要都试 ----------
class _FakeResp:
    def __init__(self, status=200):
        self.status_code = status
        self.headers = {}

    def json(self):
        return {
            "tag_name": "v9.9.9", "body": "", "published_at": "",
            "html_url": "https://example.invalid/rel", "assets": [],
        }


class _FailingClient:
    """第一个候选（直连）必定超时，第二个（系统代理）正常。"""

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        if self.kw.get("proxy"):
            return _FakeResp(200)
        raise RuntimeError("ConnectTimeout")


def test_client_candidates_try_direct_then_system_proxy(monkeypatch):
    """两个域名的可用路径可能相反（api 直连通/代理 403，assets 直连超时/代理通），
    所以必须两条都留着，不能只留一条。"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "FOODMAP_UPDATE_NO_PROXY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(upd, "_proxy_url", lambda: "http://127.0.0.1:7890")
    cands = upd._client_candidates()
    assert cands[0] == {"trust_env": True}
    assert cands[1] == {"trust_env": False, "proxy": "http://127.0.0.1:7890"}


def test_no_proxy_env_forces_direct_only(monkeypatch):
    """企业网络里代理会拦截时，得留一个强制直连的出口。"""
    monkeypatch.setenv("FOODMAP_UPDATE_NO_PROXY", "1")
    monkeypatch.setattr(upd, "_proxy_url", lambda: "http://127.0.0.1:7890")
    assert upd._client_candidates() == [{"trust_env": False}]


def test_fetch_latest_falls_back_when_first_path_fails(monkeypatch):
    """直连超时不应该让检查失败——换代理再试一次就能成。"""
    monkeypatch.setattr(upd, "_client_candidates",
                        lambda: [{}, {"trust_env": False, "proxy": "http://p"}])
    monkeypatch.setattr(upd.httpx, "Client", _FailingClient)
    r = upd._fetch_latest()
    assert r["latest"] == "9.9.9"


def test_download_retries_over_other_network_paths(monkeypatch):
    """下载也要逐个试网络路径。

    实测：release-assets 域名直连 21 秒超时、走系统代理 1 秒拿到数据。
    只在检查阶段做回退、下载阶段不做，等于"提示得出新版却永远装不上"。
    """
    import hashlib

    body = b"setup-binary"
    expect = hashlib.sha256(body).hexdigest()

    class StreamResp:
        status_code = 200
        headers = {"content-length": str(len(body))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self, n):
            yield body

    class Client:
        def __init__(self, **kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            if not self.kw.get("proxy"):
                raise RuntimeError("ConnectTimeout")
            return StreamResp()

    monkeypatch.setattr(upd, "_client_candidates",
                        lambda: [{}, {"trust_env": False, "proxy": "http://p"}])
    monkeypatch.setattr(upd.httpx, "Client", Client)
    name = "FoodieTrail-9.9.9-windows-x64-setup.exe"
    upd._DL.update({"state": "downloading", "received": 0, "total": 0,
                    "version": "9.9.9", "error": "", "path": ""})
    upd._download_worker({"name": name, "url": "https://example.invalid/s.exe",
                          "sha256": expect, "size": len(body)})
    p = upd.progress()
    assert p["state"] == "done", p
    assert open(p["path"], "rb").read() == body
    os.remove(p["path"])


# ---------- 取消下载 ----------
# 用户反馈：点了「下载并安装」之后没有任何办法停下来（25MB 走代理有时要几分钟）。
# 取消必须满足三条：① 立刻有反馈（state 秒变 cancelling）；② 不留半个安装包；
# ③ 不能算失败——取消是正常操作，界面不该弹「下载失败」。
@pytest.fixture(autouse=True)
def _reset_download_state():
    with upd._LOCK:
        upd._CANCEL.clear()
        upd._DL.update({"state": "idle", "received": 0, "total": 0,
                        "version": "", "error": "", "path": ""})
    yield
    with upd._LOCK:
        upd._CANCEL.clear()
        upd._DL.update({"state": "idle", "received": 0, "total": 0,
                        "version": "", "error": "", "path": ""})


class _ChunkStream:
    """按块吐数据；吐到第 `cancel_after` 块之前触发一次 cancel_download()。

    把取消放在生成器里，是为了模拟「worker 正在写 .part 的同时，另一个请求线程
    调用了 /api/update/cancel」这个真实时序。
    """

    def __init__(self, chunks, cancel_after=None):
        self.chunks = chunks
        self.cancel_after = cancel_after

    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def headers(self):
        return {"content-length": str(sum(len(c) for c in self.chunks))}

    def iter_bytes(self, n):
        for i, c in enumerate(self.chunks):
            if self.cancel_after is not None and i == self.cancel_after:
                upd.cancel_download()
            yield c


def _patch_stream(monkeypatch, chunks, cancel_after=None, calls=None):
    calls = calls if calls is not None else []

    class Client:
        def __init__(self, **kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            calls.append(url)
            return _ChunkStream(chunks, cancel_after)

    monkeypatch.setattr(upd, "_client_candidates", lambda: [{}, {"proxy": "http://p"}])
    monkeypatch.setattr(upd.httpx, "Client", Client)
    return calls


def test_cancel_midway_marks_cancelled_and_removes_part(monkeypatch):
    chunks = [b"a" * 64, b"b" * 64, b"c" * 64]
    _patch_stream(monkeypatch, chunks, cancel_after=1)
    with upd._LOCK:
        upd._DL["state"] = "downloading"
    upd._download_worker({"name": "FoodieTrail-9.9.9-windows-x64-setup.exe",
                          "url": "https://example.invalid/s.exe",
                          "sha256": "0" * 64, "size": 192})
    p = upd.progress()
    assert p["state"] == "cancelled", p          # 不是 error，也不该是 done
    assert p["error"] == ""
    assert p["received"] == 0
    assert not os.path.exists(os.path.join(
        upd.DOWNLOADS_DIR, "FoodieTrail-9.9.9-windows-x64-setup.exe.part"))
    assert not os.path.exists(os.path.join(
        upd.DOWNLOADS_DIR, "FoodieTrail-9.9.9-windows-x64-setup.exe"))


def test_cancel_does_not_try_other_network_paths(monkeypatch):
    """取消就是取消：不能因为「还有一条网络路径没试」就接着下。"""
    calls = _patch_stream(monkeypatch, [b"x" * 64] * 3, cancel_after=0, calls=[])
    with upd._LOCK:
        upd._DL["state"] = "downloading"
    upd._download_worker({"name": "FoodieTrail-9.9.9-windows-x64-setup.exe",
                          "url": "https://example.invalid/s.exe",
                          "sha256": "0" * 64, "size": 192})
    assert len(calls) == 1, calls                # 第二条路径一次都没碰
    assert upd.progress()["state"] == "cancelled"


def test_cancel_flips_state_to_cancelling_immediately():
    with upd._LOCK:
        upd._DL.update({"state": "downloading", "received": 10, "total": 100})
    p = upd.cancel_download()
    assert p["state"] == "cancelling"            # 按钮立刻有反馈
    assert upd._CANCEL.is_set()


def test_cancel_is_idempotent_when_idle():
    assert upd.progress()["state"] == "idle"
    assert upd.cancel_download()["state"] == "idle"
    assert upd.cancel_download()["state"] == "idle"
    assert not upd._CANCEL.is_set()


def test_cancel_after_done_is_noop(monkeypatch):
    """已经下完了再点取消：不能把状态从 done 改掉，安装入口还得在。"""
    with upd._LOCK:
        upd._DL.update({"state": "done", "path": "x.exe", "received": 100})
    assert upd.cancel_download()["state"] == "done"


def test_start_download_clears_previous_cancel_flag(monkeypatch):
    """取消之后要能重新下载：上一轮的取消标志不能把新任务立刻掐掉。"""
    started = []
    monkeypatch.setattr(upd, "detect_mode", lambda: "installer")
    monkeypatch.setattr(upd, "_read_cache", lambda: {"latest": "9.9.9", "setup": {
        "name": "FoodieTrail-9.9.9-windows-x64-setup.exe",
        "url": "https://example.invalid/s.exe", "sha256": "0" * 64, "size": 192}})
    monkeypatch.setattr(upd.threading, "Thread",
                        lambda *a, **kw: type("T", (), {"start": lambda s: started.append(1)})())
    upd._CANCEL.set()
    p = upd.start_download()
    assert p["state"] == "downloading"
    assert not upd._CANCEL.is_set()
    assert started


def test_install_refuses_while_downloading(monkeypatch):
    """下载中允许安装会装到半个包，甚至静默装回旧版同名 exe。"""
    monkeypatch.setattr(upd, "detect_mode", lambda: "installer")
    with upd._LOCK:
        upd._DL.update({"state": "downloading"})
    with pytest.raises(upd.UpdateError) as e:
        upd.install()
    assert e.value.status == 409
    assert "下载" in e.value.message


def test_fetch_latest_reports_last_error_when_all_paths_fail(monkeypatch):
    """所有路径都失败时，抛出的应该是最后一条的原因，不是第一条的。"""
    class AllFail(_FailingClient):
        def get(self, *a, **k):
            raise RuntimeError("ConnectTimeout")

    monkeypatch.setattr(upd, "_client_candidates", lambda: [{}, {"proxy": "http://p"}])
    monkeypatch.setattr(upd.httpx, "Client", AllFail)
    with pytest.raises(upd.UpdateError) as e:
        upd._fetch_latest()
    assert "ConnectTimeout" in e.value.message


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


def test_cancel_endpoint_returns_progress_shape(client):
    """取消接口必须 200 + 进度结构：前端直接把它当 dl 用，缺字段模板就渲染不出来。"""
    r = client.post("/api/update/cancel")
    assert r.status_code == 200
    body = r.json()
    assert set(("state", "percent", "received", "total")).issubset(body)
    assert body["state"] in ("idle", "cancelling", "cancelled")


def test_update_cache_is_valid_json(tmp_path):
    """缓存必须是可解析的 JSON：写坏一次就会让下次检查读不到。"""
    upd._write_cache(_release())
    with open(upd.UPDATE_CACHE_PATH, encoding="utf-8") as f:
        assert json.load(f)["latest"] == "9.9.9"


# ---------- API 额度耗尽时的网页版兜底 ----------
# 背景：api.github.com 的匿名额度只有 60 次/小时且按出口 IP 计。发版日反复检查
# 很容易把额度用光，此时应用原来只会说「联网失败」并回退旧缓存，界面却显示
# 「已是最新版本」——明明发了新版也查不到（2026-10-22 用户实踩）。

class _HtmlResp:
    def __init__(self, status=302, location=""):
        self.status_code = status
        self.headers = {"location": location} if location else {}
        self.url = upd.HTML_LATEST
        self.text = ""


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None, **kw):
        if callable(self._resp):
            return self._resp(url)
        return self._resp


def test_html_fallback_reads_tag_from_redirect(monkeypatch):
    """302 的 Location 里带 tag —— 不占 API 额度也能知道最新版本。"""
    monkeypatch.setattr(upd, "_client_candidates", lambda: [{"trust_env": False}])
    monkeypatch.setattr(upd, "_client", lambda *a, **k: _FakeClient(
        _HtmlResp(302, "https://github.com/perry466/foodie-trail/releases/tag/v9.9.9")))
    d = upd._fetch_latest_html()
    assert d["latest"] == "9.9.9"
    assert d["tag"] == "v9.9.9"
    assert d["degraded"] is True
    assert d["setup"] is None and d["zip"] is None     # 拿不到资产，只能手动下载


def test_html_fallback_rejects_unparseable(monkeypatch):
    """没有 302、URL 里也没有 tag：宁可报错，也不能编一个版本号出来。"""
    monkeypatch.setattr(upd, "_client_candidates", lambda: [{"trust_env": False}])
    monkeypatch.setattr(upd, "_client", lambda *a, **k: _FakeClient(_HtmlResp(200, "")))
    with pytest.raises(upd.UpdateError):
        upd._fetch_latest_html()


def test_api_failure_falls_back_to_html(monkeypatch):
    """API 所有路都失败时，_fetch_latest 自己退到网页版，而不是直接抛错。"""
    monkeypatch.setattr(upd, "_client_candidates", lambda: [{"trust_env": False}])

    def resp(url):
        if "api.github.com" in str(url):
            raise RuntimeError("rate limit exceeded")
        return _HtmlResp(302, "https://github.com/perry466/foodie-trail/releases/tag/v9.9.9")

    monkeypatch.setattr(upd, "_client", lambda *a, **k: _FakeClient(resp))
    d = upd._fetch_latest()
    assert d["latest"] == "9.9.9" and d["degraded"] is True


def test_degraded_result_is_not_written_to_cache(monkeypatch):
    """降级结果只有版本号：写进缓存会让下次下载拿到空地址，还会冲掉完整的 Release 信息。"""
    _clear_cache()
    degraded = {
        "checkedAt": int(time.time()), "latest": "9.9.9", "tag": "v9.9.9",
        "notes": "", "publishedAt": "", "htmlUrl": upd.HTML_RELEASES,
        "setup": None, "zip": None, "degraded": True,
    }
    monkeypatch.setattr(upd, "_fetch_latest", lambda: degraded)
    writes = []
    monkeypatch.setattr(upd, "_write_cache", lambda payload: writes.append(payload))

    r = upd.check(force=True)

    assert r["hasUpdate"] is True                 # 至少要说清「有新版」
    assert r["degraded"] is True
    assert r["canAutoInstall"] is False           # 没有 sha256，绝不允许自动装
    assert r["downloadUrl"] == ""
    assert writes == []                           # 不落盘
