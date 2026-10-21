"""路径与全局常量配置"""
import os
import random
import socket

# 项目根目录：taste-map/（即仓库根目录，app/ 的上级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 数据目录：默认 <仓库>/data；设置 FOODMAP_DATA_DIR 可改到别处。
# 用途：便携部署（数据放 U 盘/用户目录）、自动化测试隔离（tests/ 用临时目录，不碰真实数据）。
DATA_DIR = os.path.abspath(os.environ.get("FOODMAP_DATA_DIR") or os.path.join(BASE_DIR, "data"))
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")
DB_PATH = os.path.join(DATA_DIR, "foodmap.db")
FERNET_KEY_PATH = os.path.join(DATA_DIR, ".fernet.key")
STATIC_DIR = os.path.join(BASE_DIR, "static")

DB_VERSION = 1

# 照片压缩参数：长边上限、JPEG 质量、单张字节上限、单条记录张数上限（经验取值，可按需调整）
PHOTO_MAX_EDGE = 1280
PHOTO_QUALITY = 82
PHOTO_MAX_BYTES = 500 * 1024
PHOTO_MAX_COUNT = 9

# 端口
DEFAULT_PORT = 20000
PORT_RANGE = (20000, 65535)
LAST_PORT_FILE = os.path.join(DATA_DIR, ".last_port")


def parse_port(value, low=1024, high=65535):
    """把外部端口值（环境变量 / .last_port 文件 / 手工输入）收敛成 int。

    非法内容、越界数值一律返回 None，绝不抛异常：`PORT=abc` 曾经让
    `int()` 直接 ValueError 把进程打崩，`PORT=99999` 则在 bind 时抛
    OverflowError（不是 OSError，原来的 except 拦不住）。
    """
    if value is None:
        return None
    try:
        p = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return p if low <= p <= high else None


def load_last_port():
    """读取上次成功使用的端口（data/.last_port），不存在/非法则返回 None。"""
    try:
        with open(LAST_PORT_FILE) as f:
            return parse_port(f.read())
    except Exception:
        return None


def save_last_port(port):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LAST_PORT_FILE, "w") as f:
            f.write(str(port))
    except Exception:
        pass


def _is_port_free(port):
    """端口是否可绑定；非法端口（非数字 / 越界）按「不可用」处理，不抛异常。"""
    p = parse_port(port, 1, 65535)
    if p is None:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", p))
        return True
    except (OSError, ValueError):
        return False


def find_free_port(preferred=None, low=PORT_RANGE[0], high=PORT_RANGE[1]):
    """优先用 preferred（上次端口），否则高端口随机；被占用则 +1 探测；极端情况回退系统分配。"""
    candidates = []
    p = parse_port(preferred, 1, 65535)
    if p:
        candidates.append(p)
    candidates.append(random.randint(low, high))
    for port in candidates:
        if _is_port_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

# 高德 Web 服务 API 基础
AMAP_REST = "https://restapi.amap.com"
