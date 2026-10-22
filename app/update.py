# -*- coding: utf-8 -*-
"""应用内更新：查 GitHub Release、下载安装包、启动安装器。

三条硬约束，改动时不要放宽：

1. **绝不阻塞启动、绝不把异常抛给前端**。检查更新是前端主动发起的，连接超时 4 秒，
   任何失败都收敛成 `ok=false` + 原因。GitHub 在国内网络时通时不通，把它做成
   「打不开应用」或「每次弹一个网络错误」都是不可接受的。

2. **绝不信前端传来的 URL 或路径**。下载地址只从「缓存的最新 Release」里取，
   保存文件名由后端按版本号生成，启动安装器前再校验 realpath 必须在
   `data/downloads` 内。否则这个功能就是一个远程执行 + 任意文件覆盖的入口。

3. **先写 `.part`、校验 sha256、再原子改名**。25MB 的安装包下载中断很常见，
   把半个 exe 当成安装包启动，会留下一个装了一半、起不来的程序。
   校验值来自 GitHub Release API 的 `digest` 字段（`sha256:...`）。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

import httpx

from .pathconf import APP_DIR, DOWNLOADS_DIR, FROZEN, UPDATE_CACHE_PATH
from .version import VERSION

REPO = "perry466/foodie-trail"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
HTML_RELEASES = f"https://github.com/{REPO}/releases"

# 检查结果缓存 30 分钟。
# 定这个值权衡的是两件事：发新版之后用户多久能看到（太长会错过），以及
# 免认证接口 60 次/小时/IP 的限额（一天开 10 次应用也只有 10 次请求，远低于限额）。
# 曾经用 6 小时，结果刚发布的版本最多 6 小时都提示不出来。
CACHE_TTL = 30 * 60
# 检查用短超时：宁可这次不提示，也不能让启动变慢。
CHECK_TIMEOUT = 4.0
# 下载用长读超时：单个 chunk 之间允许停顿，整体不设上限（大小另有硬上限）。
DOWNLOAD_TIMEOUT = httpx.Timeout(15.0, read=60.0)
MAX_ASSET_BYTES = 200 * 1024 * 1024

_LOCK = threading.Lock()
# 下载进度：前端轮询 /api/update/download 读它
_DL = {
    "state": "idle",        # idle | downloading | verifying | done | error
    "received": 0,
    "total": 0,
    "version": "",
    "error": "",
    "path": "",
}

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class UpdateError(Exception):
    """带 HTTP 状态码的更新错误，由路由层转成 JSONResponse。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------- 版本号 ----------
def parse_version(value):
    """把 `v1.0.10` / `1.0.10` / `1.0.10-beta` 收敛成 (1, 0, 10)。

    必须按数字元组比较：字符串比较下 `"1.0.10" < "1.0.9"` 成立，
    这是更新功能最经典的一次翻车（1.0.10 发出来之后没人被提示）。
    """
    m = _VERSION_RE.search(str(value or ""))
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def compare_versions(a, b):
    """a > b 返回 1，相等 0，a < b 返回 -1；无法解析按相等处理。"""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        return 0
    return (pa > pb) - (pa < pb)


# ---------- 运行形态 ----------
def detect_mode():
    """source（源码）/ installer（Inno 安装版）/ portable（绿色版）。

    判据是 exe 同级有没有 Inno 生成的 unins000.exe。绿色版没有它，
    所以直接把 setup.exe 静默装下去会变成「悄悄多装了一份」，必须区分。
    """
    if not FROZEN:
        return "source"
    try:
        if os.path.exists(os.path.join(APP_DIR, "unins000.exe")):
            return "installer"
    except Exception:
        pass
    return "portable"


# ---------- 缓存 ----------
def _read_cache():
    try:
        with open(UPDATE_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_cache(payload):
    """写缓存失败不影响功能：下次重新查就是了，但绝不能让它抛出去。"""
    try:
        os.makedirs(os.path.dirname(UPDATE_CACHE_PATH), exist_ok=True)
        tmp = UPDATE_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, UPDATE_CACHE_PATH)
    except Exception:
        pass


# ---------- 查询 ----------
def _pick_asset(assets, suffix):
    """按文件名后缀挑资产；同时只认 sha256 digest 齐备的（下载后要校验）。"""
    for a in assets or []:
        name = str(a.get("name") or "")
        if not name.lower().endswith(suffix):
            continue
        digest = str(a.get("digest") or "")
        return {
            "name": name,
            "size": int(a.get("size") or 0),
            "url": str(a.get("browser_download_url") or ""),
            "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
        }
    return None


def _rate_limit_hint(r):
    """把 GitHub 的 403/429 翻成一句能指导下一步的话。

    GitHub 有两种 403，长得一模一样但原因不同：
    - **主额度用完**：`x-ratelimit-remaining: 0`，免认证每小时 60 次/IP；
    - **次级限流**：短时间内反复请求触发，`x-ratelimit-remaining` 还有余量也照样 403，
      有时带 `retry-after`。用户装好 v1.0.2 后连点几次「检查更新」撞上的就是这种。
    不把这两种区分开，用户只会看到一句没用的「HTTP 403」。
    """
    remain = r.headers.get("x-ratelimit-remaining")
    reset = r.headers.get("x-ratelimit-reset")
    retry = r.headers.get("retry-after")
    if remain == "0":
        wait = ""
        try:
            mins = max(1, int((int(reset) - time.time()) // 60) + 1)
            wait = f"，约 {mins} 分钟后恢复"
        except Exception:
            pass
        return f"GitHub 接口额度已用完（免认证每小时 60 次）{wait}"
    if retry:
        return f"GitHub 暂时限制了这个 IP，请 {retry} 秒后再试"
    return "GitHub 拒绝了这个请求（短时间内重复检查，或代理出口被限制）"


def _proxy_url():
    """读 Windows 注册表里的「系统代理」地址；读不到返回 None。

    为什么需要这个：Clash / V2Ray 的「系统代理」开关只改注册表，而 httpx 的
    `trust_env` **只认环境变量、不读注册表**。不补这一条，开了系统代理的机器上
    应用内请求其实一直在直连。
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            if not int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0):
                return None
        except (FileNotFoundError, ValueError, TypeError):
            return None
        server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
    except Exception:
        return None
    if not server:
        return None
    if "=" in server:            # "http=host:port;https=host:port" 这种写法
        parts = {}
        for seg in server.split(";"):
            if "=" in seg:
                k, v = seg.split("=", 1)
                parts[k.strip().lower()] = v.strip()
        server = parts.get("https") or parts.get("http") or ""
    if not server:
        return None
    return server if server.startswith(("http://", "https://")) else "http://" + server


def _client_candidates():
    """按优先级给出几组 httpx 构造参数，逐个试，哪个能通用哪个。

    为什么不是固定一个：一台机器上两个域名的可用路径可能是**相反**的。实测
    （开 Clash 系统代理 `127.0.0.1:7890`，且无环境变量代理）：

    | 域名 | 直连 | 走系统代理 |
    |---|---|---|
    | `api.github.com` | 200（0.6s） | **403** rate limit exceeded（出口 IP 被别人用光） |
    | `release-assets.githubusercontent.com` | **21 秒超时** | 206（1.0s） |

    写死直连，下载永远失败；写死代理，检查永远 403。所以两条都试。

    需要强制直连（例如企业网络里代理会拦截）时设 `FOODMAP_UPDATE_NO_PROXY=1`。
    """
    if os.environ.get("FOODMAP_UPDATE_NO_PROXY") == "1":
        return [{"trust_env": False}]
    cands = [{"trust_env": True}]          # 环境变量代理，没有就直连
    proxy = _proxy_url()
    if proxy:
        cands.append({"trust_env": False, "proxy": proxy})
    return cands


def _client(timeout, cand=None, follow_redirects=True):
    kw = dict(cand or {})
    kw["timeout"] = timeout
    kw["follow_redirects"] = follow_redirects
    return httpx.Client(**kw)


def _fetch_latest():
    """请求 GitHub latest release，逐个试 `_client_candidates()`。调用方兜异常。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"FoodieTrail/{VERSION}",
    }
    last_err = None
    for cand in _client_candidates():
        try:
            with _client(CHECK_TIMEOUT, cand=cand) as c:
                r = c.get(API_LATEST, headers=headers)
            if r.status_code != 200:
                raise _http_error(r)
            return _parse_release(r.json())
        except UpdateError as e:
            last_err = e
        except Exception as e:                # 超时/连接失败：换下一条路
            last_err = UpdateError(f"{type(e).__name__}: {e}", 502)
    raise last_err or UpdateError("无法连接 GitHub", 502)


def _http_error(r):
    """把非 200 响应翻译成人能看懂的 UpdateError。"""
    if r.status_code in (403, 429):
        hint = _rate_limit_hint(r)
        try:
            msg = str((r.json() or {}).get("message") or "").strip()
        except Exception:
            msg = ""
        return UpdateError(f"{hint}｜{msg}" if msg else hint, 502)
    return UpdateError(f"GitHub 返回 HTTP {r.status_code}", 502)


def _parse_release(d):
    tag = str(d.get("tag_name") or "")
    latest = tag[1:] if tag.lower().startswith("v") else tag
    if parse_version(latest) is None:
        raise UpdateError("Release 标签格式无法识别", 502)
    assets = d.get("assets") or []
    return {
        "checkedAt": int(time.time()),
        "latest": latest,
        "tag": tag,
        "notes": (d.get("body") or "").strip(),
        "publishedAt": d.get("published_at") or "",
        "htmlUrl": d.get("html_url") or HTML_RELEASES,
        "setup": _pick_asset(assets, "-setup.exe"),
        "zip": _pick_asset(assets, ".zip"),
    }


def _build_result(cache, cached=False, reason=""):
    mode = detect_mode()
    latest = cache.get("latest") or VERSION
    setup = cache.get("setup") or None
    result = {
        "ok": True,
        "current": VERSION,
        "latest": latest,
        "hasUpdate": compare_versions(latest, VERSION) > 0,
        "notes": cache.get("notes") or "",
        "publishedAt": cache.get("publishedAt") or "",
        "htmlUrl": cache.get("htmlUrl") or HTML_RELEASES,
        "checkedAt": cache.get("checkedAt") or 0,
        "cached": bool(cached),
        "mode": mode,
        # 只有安装版能自动装：绿色版/源码版没有 unins000.exe，
        # 静默跑 setup.exe 会在 {localappdata} 里再装一份，而不是升级当前这份。
        # 另外要求必须带 sha256——没有校验值就没法确认下载完整，宁可让用户手动装。
        "canAutoInstall": mode == "installer" and bool(
            setup and setup.get("url") and setup.get("sha256")),
        "hasSetup": bool(setup and setup.get("url")),
        "hasZip": bool(cache.get("zip") and cache["zip"].get("url")),
        # 直接给出安装包地址供前端「复制下载链接」用：
        # 到不了 release-assets 域名的网络下，应用内下载必然超时，
        # 用户拿链接丢进浏览器/下载工具反而能成。这个 URL 只用于展示与复制，
        # 安装接口仍然只认缓存里自己那份资产，不接受前端传地址。
        "downloadUrl": (setup or {}).get("url") or "",
        "downloadName": (setup or {}).get("name") or "",
        "downloadSize": int((setup or {}).get("size") or 0),
    }
    if cache.get("via"):
        result["via"] = cache["via"]
    if reason:
        result["reason"] = reason
    return result


def check(force=False):
    """检查更新。永远返回 dict，永远不抛异常。"""
    cache = _read_cache()
    now = time.time()
    if not force and cache and 0 <= now - int(cache.get("checkedAt") or 0) < CACHE_TTL:
        return _build_result(cache, cached=True)
    try:
        fresh = _fetch_latest()
    except Exception as e:
        msg = getattr(e, "message", None) or f"{type(e).__name__}: {e}"
        # 查不到但手里有旧结果：给出旧结果并标注过期，让用户仍能看到下载入口。
        # 没有走「网页版 releases/latest 兜底」：那条路只能回答"有没有新版"，
        # 拿不到 sha256 也就无法自动安装，实现成本换不来收益。
        if cache and parse_version(cache.get("latest")):
            out = _build_result(cache, cached=True, reason=msg)
            out["stale"] = True
            return out
        return {
            "ok": False,
            "reason": msg,
            "current": VERSION,
            "mode": detect_mode(),
            "htmlUrl": HTML_RELEASES,
        }
    _write_cache(fresh)
    return _build_result(fresh)


# ---------- 下载 ----------
def progress():
    with _LOCK:
        snap = dict(_DL)
    total = snap.get("total") or 0
    snap["percent"] = int(snap.get("received", 0) * 100 / total) if total > 0 else 0
    return snap


def _download_paths(asset_name):
    return (
        os.path.join(DOWNLOADS_DIR, asset_name),
        os.path.join(DOWNLOADS_DIR, asset_name + ".part"),
    )


def start_download():
    """启动后台下载，立即返回。真正的进度由 progress() 提供。"""
    mode = detect_mode()
    if mode != "installer":
        raise UpdateError("当前是绿色版或源码版，无法自动安装，请前往 Release 页面手动下载", 409)
    cache = _read_cache()
    setup = (cache or {}).get("setup") or {}
    url = setup.get("url") or ""
    if not url:
        raise UpdateError("还没有拿到安装包信息，请先检查更新", 409)
    with _LOCK:
        if _DL["state"] in ("downloading", "verifying"):
            return progress()
        _DL.update({
            "state": "downloading", "received": 0,
            "total": int(setup.get("size") or 0),
            "version": (cache or {}).get("latest") or "",
            "error": "", "path": "",
        })
    threading.Thread(target=_download_worker, args=(setup,), daemon=True).start()
    return progress()


def _cleanup_old_downloads(keep_name):
    """只保留本次要装的包：25MB × N 个版本累积起来很可观，用户不会自己去清。"""
    try:
        for f in os.listdir(DOWNLOADS_DIR):
            if f == keep_name:
                continue
            if f.lower().endswith((".exe", ".part")):
                try:
                    os.remove(os.path.join(DOWNLOADS_DIR, f))
                except OSError:
                    pass
    except OSError:
        pass


def _download_worker(asset):
    name = asset["name"]
    final, part = _download_paths(name)
    expect_sha = asset.get("sha256") or ""
    try:
        if not expect_sha:
            raise UpdateError("该版本没有提供 sha256 校验值，已停止自动安装，请手动下载", 400)
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        _cleanup_old_downloads(name)
        cands = _client_candidates()
        for idx, cand in enumerate(cands):
            sha = hashlib.sha256()
            received = 0
            try:
                with _client(DOWNLOAD_TIMEOUT, cand=cand) as c:
                    with c.stream("GET", asset["url"],
                                  headers={"User-Agent": f"FoodieTrail/{VERSION}"}) as r:
                        if r.status_code != 200:
                            raise UpdateError(f"下载失败：HTTP {r.status_code}", 502)
                        # 先用响应头纠正总量，服务端有时不给 content-length
                        clen = int(r.headers.get("content-length") or 0)
                        if clen > 0:
                            with _LOCK:
                                _DL["total"] = clen
                        with open(part, "wb") as f:
                            for chunk in r.iter_bytes(64 * 1024):
                                if not chunk:
                                    continue
                                f.write(chunk)
                                sha.update(chunk)
                                received += len(chunk)
                                if received > MAX_ASSET_BYTES:
                                    raise UpdateError("安装包超过 200MB，已中止", 400)
                                with _LOCK:
                                    _DL["received"] = received
                break        # 成功，跳出重试
            except Exception as e:
                # 还有下一种网络路径就重置再来一次；已经没有就抛出
                if received:
                    with _LOCK:
                        _DL["received"] = 0
                if idx == len(cands) - 1:
                    raise
                try:
                    if os.path.exists(part):
                        os.remove(part)
                except OSError:
                    pass
        with _LOCK:
            _DL["state"] = "verifying"
        if expect_sha and sha.hexdigest() != expect_sha:
            raise UpdateError("安装包校验失败（sha256 不匹配），已删除", 400)
        os.replace(part, final)          # 只有校验通过才让它变成正式文件名
        with _LOCK:
            _DL.update({"state": "done", "path": final, "received": received})
    except Exception as e:
        try:
            if os.path.exists(part):
                os.remove(part)
        except Exception:
            pass
        msg = getattr(e, "message", None) or f"{type(e).__name__}: {e}"
        with _LOCK:
            _DL.update({"state": "error", "error": msg})


# ---------- 安装 ----------
def _safe_download_path(name):
    """文件名只允许后端生成的那一种，且必须落在 downloads 目录内。"""
    # 分隔符单独判一次：Windows 下 basename 会吃掉 `..\\`，但换到 POSIX 跑测试时
    # 反斜杠不算分隔符，只靠 commonpath 会让 `..\\evil.exe` 混过去。
    if (not name or name != os.path.basename(name)
            or "/" in name or "\\" in name
            or not name.lower().endswith(".exe")):
        raise UpdateError("安装包文件名非法", 400)
    target = os.path.abspath(os.path.join(DOWNLOADS_DIR, name))
    root = os.path.abspath(DOWNLOADS_DIR)
    if os.path.commonpath([target, root]) != root:
        raise UpdateError("安装包路径越界", 400)
    return target


def install():
    """启动安装器并退出本进程。返回后调用方应立即响应前端。"""
    if detect_mode() != "installer":
        raise UpdateError("当前不是安装版，无法自动安装", 409)
    cache = _read_cache() or {}
    setup = cache.get("setup") or {}
    if not setup.get("name"):
        raise UpdateError("没有可用的安装包信息，请先检查更新", 409)
    target = _safe_download_path(setup["name"])
    if not os.path.exists(target):
        raise UpdateError("安装包还没下载完", 409)
    size = os.path.getsize(target)
    if setup.get("size") and size != int(setup["size"]):
        raise UpdateError("安装包大小不符，请重新下载", 400)

    exe = os.path.abspath(sys.executable)
    # 用 cmd 起一个延迟链，而不是直接 Popen 安装器：
    #   ping -n 4   等待约 3 秒，让本进程先干净退出（Inno 的 AppMutex 才不会撞上我们）
    #   start /wait 装完再返回，随后重新拉起应用
    #   /VERYSILENT /NORESTART /SUPPRESSMSGBOXES：无需交互，不自动重启系统
    # 装完后 Inno 的 [Run] 带 skipifsilent，静默模式不会自启，所以这里自己 start。
    delay = int(os.environ.get("FOODMAP_UPDATE_DELAY", "4") or 4)
    cmd = (
        f'ping -n {max(delay, 2)} 127.0.0.1 >nul & '
        f'start "" /wait "{target}" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES & '
        f'start "" "{exe}"'
    )
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS：父进程退出后这条 cmd 链要继续跑完
        flags = 0x00000008 | 0x08000000      # DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        subprocess.Popen(["cmd.exe", "/c", cmd], close_fds=True, creationflags=flags)
    except Exception as e:
        raise UpdateError(f"启动安装器失败：{e}", 500)

    _delayed_exit(1.2)
    return {"ok": True, "willExit": True}


def _delayed_exit(seconds):
    """先让 HTTP 响应发出去，再退出。

    用 os._exit 而不是 sys.exit：进程里还有 uvicorn 线程与托盘图标，
    sys.exit 只退当前线程。SQLite 都是短连接、事务已提交，WAL 崩溃安全，
    所以这里不需要额外的收尾。
    """
    def _boom():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    threading.Timer(seconds, _boom).start()
