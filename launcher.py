# -*- coding: utf-8 -*-
"""打包版启动入口：无控制台窗口、托盘常驻、单实例。

为什么不能直接打包 `app.main`：
1. GUI 子系统（`console=False`）下 `sys.stdout` / `sys.stderr` 是无效句柄，
   uvicorn 默认日志配置会写 stderr，一写就把服务线程写崩，表现为「浏览器打不开、
   日志里什么都没有」。所以先把两个流指向 devnull，并单独把日志落盘到 data/app.log。
2. 双击两次会起两个进程，抢同一个 SQLite 文件。用命名互斥量做单实例，
   第二次启动直接打开已在运行的那个页面。
3. 没有控制台就没法看「服务起没起来」，所以等端口真的可连接后再开浏览器，
   并提供一个托盘图标作为唯一的交互入口。

源码运行仍然走 `python -m app.main`，本文件只在打包产物里使用。
"""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

# ---- 1. 先把无效的标准流替换掉（必须在 import uvicorn 之前） ----
if getattr(sys, "frozen", False):
    try:
        _devnull = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = _devnull
        sys.stderr = _devnull
    except OSError:
        pass

from app.pathconf import (  # noqa: E402  (必须在流重定向之后)
    APP_DIR, DATA_DIR, find_free_port, load_last_port, save_last_port,
)

APP_NAME = "Foodie Trail"
MUTEX_NAME = "FoodieTrail.SingleInstance"
LOG_PATH = os.path.join(DATA_DIR, "app.log")
URL = ""          # 由 main() 填充，托盘菜单读取
SERVER = None     # uvicorn.Server 实例


def _icon_path():
    """图标：打包后在 _MEIPASS/assets，源码模式在仓库 assets/。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "icon.ico")


def _message_box(title, text):
    """无控制台时的唯一可见报错通道。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass


def _setup_logging():
    os.makedirs(DATA_DIR, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        encoding="utf-8",
    )
    logging.info("---- 启动 %s ----", APP_NAME)
    logging.info("exe 目录: %s", APP_DIR)
    logging.info("数据目录: %s", DATA_DIR)


def _acquire_single_instance():
    """Windows 命名互斥量；已有实例返回 (False, handle)。"""
    if os.name != "nt":
        return True, None
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        already = kernel32.GetLastError() == 183      # ERROR_ALREADY_EXISTS
        return (not already), handle
    except Exception:
        logging.exception("单实例检测失败，按允许启动处理")
        return True, None


def _port_open(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_ready(port, seconds=20.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.25)
    return False


def _open_browser():
    if os.environ.get("FOODMAP_NO_BROWSER") == "1":      # 冒烟测试 / CI 用
        logging.info("FOODMAP_NO_BROWSER=1，跳过打开浏览器")
        return
    try:
        # 带时间戳，避免浏览器复用旧页面缓存
        webbrowser.open(f"{URL}/?t={int(time.time())}")
    except Exception:
        logging.exception("打开浏览器失败")
        _message_box(APP_NAME, f"服务已启动，请手动打开：\n{URL}")


def _run_server(port):
    """在后台线程里跑 uvicorn；异常一定要落盘，否则无控制台下什么都看不到。"""
    global SERVER
    import uvicorn

    from app.main import app

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_config=None,              # 不要让它再建一套写 stdout/stderr 的 handler
        log_level="info",
    )
    SERVER = uvicorn.Server(config)
    try:
        SERVER.run()
    except Exception:
        logging.exception("服务异常退出")
        _message_box(APP_NAME, f"服务异常退出，详情见日志：\n{LOG_PATH}")
    finally:
        logging.info("服务已停止")


def _open_data_dir():
    try:
        if os.name == "nt":
            os.startfile(DATA_DIR)          # noqa: S606
        else:
            webbrowser.open("file://" + DATA_DIR)
    except Exception:
        logging.exception("打开数据目录失败")


def _quit(icon=None):
    logging.info("用户从托盘退出")
    try:
        if SERVER is not None:
            SERVER.should_exit = True
    except Exception:
        pass
    if icon is not None:
        icon.stop()


def _tray():
    """托盘常驻。没有 pystray 时退回「前台阻塞」模式（源码调试用）。"""
    try:
        import pystray
        from PIL import Image
    except Exception:
        logging.warning("pystray 不可用，改为前台运行")
        return None

    try:
        image = Image.open(_icon_path())
    except Exception:
        image = Image.new("RGBA", (64, 64), (240, 80, 47, 255))

    menu = pystray.Menu(
        pystray.MenuItem("打开美食地图", lambda: _open_browser(), default=True),
        pystray.MenuItem("打开数据目录", lambda: _open_data_dir()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda icon, item: _quit(icon)),
    )
    return pystray.Icon("foodie-trail", image, APP_NAME, menu)


def main() -> int:
    global URL

    ok, _handle = _acquire_single_instance()
    if not ok:
        # 已有实例：直接打开它，不再起第二个服务
        port = load_last_port()
        if port:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        else:
            _message_box(APP_NAME, "美食地图已经在运行，请查看任务栏右下角的托盘图标。")
        return 0

    _setup_logging()

    port = find_free_port(load_last_port())
    save_last_port(port)
    URL = f"http://127.0.0.1:{port}"
    logging.info("监听 %s", URL)

    thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    thread.start()

    if not _wait_ready(port):
        logging.error("服务在 20 秒内没有就绪")
        _message_box(APP_NAME, f"服务启动超时。\n日志：{LOG_PATH}\n数据目录：{DATA_DIR}")
        return 1

    _open_browser()

    if os.environ.get("FOODMAP_HEADLESS") == "1":       # 冒烟测试 / CI：不建托盘，直接前台阻塞
        logging.info("FOODMAP_HEADLESS=1，不创建托盘图标")
        try:
            while thread.is_alive():
                thread.join(0.5)
        except KeyboardInterrupt:
            _quit()
        return 0

    icon = _tray()
    if icon is None:
        try:
            while thread.is_alive():
                thread.join(0.5)
        except KeyboardInterrupt:
            _quit()
        return 0

    icon.run()                  # 阻塞直到用户选择「退出」
    thread.join(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
