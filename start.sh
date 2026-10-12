#!/usr/bin/env bash
# 启动美食地图（优先使用本地 venv）
cd "$(dirname "$0")"
if [ -f venv/bin/python ]; then
    venv/bin/python -m app.main
elif [ -f venv/Scripts/python.exe ]; then
    venv/Scripts/python.exe -m app.main
else
    python3 -m app.main
fi
