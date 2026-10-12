"""路径与全局常量配置"""
import os
import random
import socket

# 项目根目录：taste-map/（即仓库根目录，app/ 的上级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")
DB_PATH = os.path.join(DATA_DIR, "foodmap.db")
FERNET_KEY_PATH = os.path.join(DATA_DIR, ".fernet.key")
STATIC_DIR = os.path.join(BASE_DIR, "static")

DB_VERSION = 1

# 照片压缩参数（来自需求文档 FR-6.2 / 第10节假设）
PHOTO_MAX_EDGE = 1280
PHOTO_QUALITY = 82
PHOTO_MAX_BYTES = 500 * 1024
PHOTO_MAX_COUNT = 9

# 端口
DEFAULT_PORT = 20000
PORT_RANGE = (20000, 65535)
LAST_PORT_FILE = os.path.join(DATA_DIR, ".last_port")


def load_last_port():
    """读取上次成功使用的端口（data/.last_port），不存在/非法则返回 None。"""
    try:
        with open(LAST_PORT_FILE) as f:
            p = int(f.read().strip())
            if 1024 <= p <= 65535:
                return p
    except Exception:
        return None
    return None


def save_last_port(port):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LAST_PORT_FILE, "w") as f:
            f.write(str(port))
    except Exception:
        pass


def _is_port_free(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def find_free_port(preferred=None, low=PORT_RANGE[0], high=PORT_RANGE[1]):
    """优先用 preferred（上次端口），否则高端口随机；被占用则 +1 探测；极端情况回退系统分配。"""
    candidates = []
    if preferred:
        candidates.append(int(preferred))
    candidates.append(random.randint(low, high))
    for port in candidates:
        if _is_port_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

# 高德 Web 服务 API 基础
AMAP_REST = "https://restapi.amap.com"
