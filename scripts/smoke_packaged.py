# -*- coding: utf-8 -*-
"""打包产物冒烟测试：验证「exe 双击能用 + 数据真的落在 exe 同级 data/」。

流程：
1. 以 headless 模式启动 dist/FoodieTrail/FoodieTrail.exe（不开浏览器、不建托盘）；
2. 等它监听端口 → 建一条记录 → 导出备份；
3. 结束进程，重启 → 确认记录还在（数据没被放进临时解包目录）；
4. 清理本次测试写入的 data/（只删自己建的，避免污染构建机）。

用法：
    python scripts/smoke_packaged.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE_DIR = ROOT / "dist" / "FoodieTrail"
EXE = EXE_DIR / "FoodieTrail.exe"
DATA = EXE_DIR / "data"


def _http(url, payload=None, timeout=5):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _start():
    # 不设 FOODMAP_DATA_DIR：要验证的正是「默认数据目录 = exe 同级 data/」
    env = dict(os.environ, FOODMAP_HEADLESS="1", FOODMAP_NO_BROWSER="1")
    env.pop("FOODMAP_DATA_DIR", None)
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE_DIR), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def _wait_port(seconds=40):
    port_file = DATA / ".last_port"
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            port = int(port_file.read_text().strip())
        except (OSError, ValueError):
            time.sleep(0.3)
            continue
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/records", timeout=2):
                return port
        except urllib.error.URLError:
            time.sleep(0.3)
    return None


def _kill(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    if not EXE.is_file():
        print(f"[smoke] 找不到 {EXE}，先运行 pyinstaller FoodieTrail.spec")
        return 1
    if DATA.exists():
        print(f"[smoke] {DATA} 已存在，为避免动到你的数据，请先移走再跑")
        return 1

    ok = True
    proc = _start()
    try:
        port = _wait_port()
        if not port:
            print("[smoke] ✗ 服务没起来（看 data/app.log）")
            return 1
        print(f"[smoke] ✓ 服务已监听 127.0.0.1:{port}")
        base = f"http://127.0.0.1:{port}"

        rec = _http(f"{base}/api/records", {"name": "冒烟测试店", "lng": 116.4, "lat": 39.9, "rating": 5})
        print(f"[smoke] ✓ 建记录 id={rec['id'][:8]}…")
        page = urllib.request.urlopen(f"{base}/", timeout=5).read()
        print(f"[smoke] ✓ 首页 {len(page)} 字节（静态资源已打进包）" if len(page) > 1000 else "[smoke] ✗ 首页异常")
        ok = ok and len(page) > 1000
        backup = json.loads(urllib.request.urlopen(f"{base}/api/export?mode=meta", timeout=10).read())
        print(f"[smoke] ✓ 导出 {len(backup.get('records', []))} 条")
        ok = ok and len(backup.get("records", [])) == 1
    finally:
        _kill(proc)

    print("[smoke] 重启验证数据持久化…")
    proc = _start()
    try:
        port = _wait_port()
        if not port:
            print("[smoke] ✗ 重启后服务没起来")
            return 1
        rows = _http(f"http://127.0.0.1:{port}/api/records")
        names = [r["name"] for r in rows]
        if "冒烟测试店" in names:
            print("[smoke] ✓ 重启后记录仍在 → 数据确实落在 exe 同级 data/")
        else:
            print(f"[smoke] ✗ 重启后数据丢了，当前记录：{names}")
            ok = False
        print(f"[smoke] 数据目录：{DATA}")
    finally:
        _kill(proc)
        shutil.rmtree(DATA, ignore_errors=True)     # 只清本次自建的目录

    print("\n[smoke] 结果：" + ("通过" if ok else "失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
