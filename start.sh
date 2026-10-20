#!/usr/bin/env bash
# 启动美食地图：优先用项目内 venv，但要先确认它真的能 import 依赖，
# 否则回退到系统 Python（venv 被拷坏/换机器后很常见）。
set -u
cd "$(dirname "$0")"

probe() { "$@" -c 'import fastapi, uvicorn, PIL' >/dev/null 2>&1; }

if [ -x venv/bin/python ] && probe venv/bin/python; then
    echo "[FoodMap] 使用解释器: venv/bin/python"
    exec venv/bin/python -m app.main
fi

if [ -x venv/Scripts/python.exe ] && probe venv/Scripts/python.exe; then
    echo "[FoodMap] 使用解释器: venv/Scripts/python.exe"
    exec venv/Scripts/python.exe -m app.main
fi

for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && probe "$candidate"; then
        echo "[FoodMap] 使用解释器: $candidate（未使用 venv）"
        exec "$candidate" -m app.main
    fi
done

cat >&2 <<'EOF'

[FoodMap] 没找到可用的 Python 环境（缺少 fastapi / uvicorn / Pillow）。
  1. 安装 Python 3.10 或更高版本
  2. 在本目录运行 ./setup.sh 创建 venv 并安装依赖
  3. 再运行 ./start.sh

EOF
exit 1
