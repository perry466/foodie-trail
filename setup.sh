#!/usr/bin/env bash
# 一键准备环境：创建 venv（已存在则复用）并安装运行/测试依赖。
set -u
cd "$(dirname "$0")"

BOOT=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        BOOT="$candidate"
        break
    fi
done

if [ -z "$BOOT" ]; then
    echo "[FoodMap] 没有找到 Python，请先安装 Python 3.10 或更高版本。" >&2
    exit 1
fi

echo "[FoodMap] 使用 $BOOT 准备 venv..."
if [ ! -x venv/bin/python ]; then
    "$BOOT" -m venv venv || exit 1
else
    echo "[FoodMap] 复用已存在的 venv"
fi

echo "[FoodMap] 安装依赖（requirements.txt + requirements-dev.txt）..."
venv/bin/python -m pip install --upgrade pip || exit 1
venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt || exit 1
venv/bin/python -c 'import fastapi, uvicorn, PIL, pytest; print("[FoodMap] 依赖就绪")' || exit 1

cat <<'EOF'

[FoodMap] 环境准备完成：
  启动应用：./start.sh
  运行测试：venv/bin/python -m pytest tests -q
  前端回归：node tests/front-check.js

EOF
