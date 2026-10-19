"""高德 Key 的 Fernet 对称加密存储（本地文件密钥）"""
import os
from cryptography.fernet import Fernet, InvalidToken

from .pathconf import FERNET_KEY_PATH


def _load_or_create_key() -> bytes:
    if os.path.exists(FERNET_KEY_PATH):
        with open(FERNET_KEY_PATH, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    # 全新目录（首次启动 / 打包后首次运行）时 data/ 还不存在，先建目录再写
    os.makedirs(os.path.dirname(FERNET_KEY_PATH), exist_ok=True)
    # 仅本用户可读写
    with open(FERNET_KEY_PATH, "wb") as f:
        f.write(key)
    try:
        os.chmod(FERNET_KEY_PATH, 0o600)
    except OSError:
        pass
    return key


_FERNET = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    return _FERNET.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    try:
        return _FERNET.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return ""
