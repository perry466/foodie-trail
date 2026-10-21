"""高德 Key 的 Fernet 对称加密存储（本地文件密钥）

启动健壮性约定：**钥匙文件坏掉绝不能让应用起不来**。
以前 `_load_or_create_key()` 把文件内容直接丢给 `Fernet()`，遇到空文件 / 被截断 /
杀软改写时抛 ValueError，而这个调用发生在 import 期——结果是整个进程连记录都
读不出来，直接崩掉。现在改成：留档坏钥匙 → 生成新钥匙 → 继续启动。代价只是
「此前保存的高德 Key 解不开，需要重填」，用户记录与照片不受影响。
"""
import os
import time

from cryptography.fernet import Fernet, InvalidToken

from .pathconf import FERNET_KEY_PATH

# 钥匙状态，供启动日志提示：ok 正常 / recreated 坏钥匙已换新 / ephemeral 目录不可写
KEY_STATE = "ok"
# 坏钥匙的留档路径（改名备份，便于事后找回旧 Key）
KEY_BACKUP = None


def _usable(key: bytes) -> bool:
    if not key:
        return False
    try:
        Fernet(key)
        return True
    except (ValueError, TypeError):
        return False


def _read_key(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read().strip()
    except OSError:
        return b""


def _load_or_create_key() -> bytes:
    global KEY_STATE, KEY_BACKUP
    if os.path.exists(FERNET_KEY_PATH):
        key = _read_key(FERNET_KEY_PATH)
        if _usable(key):
            return key
        # 坏钥匙：留档后换新，绝不因一个损坏的密钥文件让整个应用启动失败
        backup = f"{FERNET_KEY_PATH}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(FERNET_KEY_PATH, backup)
            KEY_BACKUP = backup
            KEY_STATE = "recreated"
        except OSError:
            pass                      # 连改名都失败：下面直接覆盖写

    key = Fernet.generate_key()
    try:
        os.makedirs(os.path.dirname(FERNET_KEY_PATH), exist_ok=True)
        # 仅本用户可读写
        with open(FERNET_KEY_PATH, "wb") as f:
            f.write(key)
        try:
            os.chmod(FERNET_KEY_PATH, 0o600)
        except OSError:
            pass
        return key
    except OSError:
        # 数据目录只读 / 无权限：退化成进程内临时钥匙，应用照常能跑
        # （已加密的 Key 读不出来，新存的 Key 重启后失效，但不影响记录本身）
        KEY_STATE = "ephemeral"
        return key


_FERNET = Fernet(_load_or_create_key())


def status_hint() -> str:
    """启动提示用的一句话；钥匙正常时返回空串。"""
    if KEY_STATE == "recreated":
        where = f"，坏文件已留档：{KEY_BACKUP}" if KEY_BACKUP else ""
        return ("加密钥匙文件损坏，已重新生成" + where +
                "。此前保存的高德 Key 无法解密，请在设置里重新填写（记录与照片不受影响）。")
    if KEY_STATE == "ephemeral":
        return "数据目录不可写，本次使用临时加密钥匙；保存的高德 Key 在重启后会失效。"
    return ""


def encrypt(plaintext: str) -> str:
    return _FERNET.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    try:
        return _FERNET.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError, AttributeError):
        return ""
