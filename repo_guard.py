# -*- coding: utf-8 -*-
"""提交前守卫：阻止把本地数据 / 密钥 / 临时产物带进仓库。

设计原则：**只按「路径」拦数据类文件，默认放行一切源码与资源**，
避免误伤核心文件（`app/`、`static/`、`tests/`、文档、截图、脚本都不在规则里）。

用途：
    python repo_guard.py            # 检查当前所有已跟踪文件（正常应为 0 命中）
    python repo_guard.py --staged   # 检查暂存区（pre-commit 钩子调用）
    python repo_guard.py --all      # 同默认，显式写法

退出码：0 = 没问题；2 = 发现不该提交的文件（钩子据此阻止提交）；
1 = 脚本自身出错（钩子会放行并提示，避免守卫自己的 bug 把人锁死）。
想强行提交：`git commit --no-verify`（不推荐）。
"""
import argparse
import os
import re
import subprocess
import sys

# (正则, 说明)。路径统一用正斜杠、相对仓库根。
RULES = [
    (re.compile(r"^data/"), "本地数据目录（库 / 照片 / 密钥 / 备份）"),
    (re.compile(r"^dev-context/"), "本地交接文档（含内部细节）"),
    (re.compile(r"^\.workbuddy/"), "AI 会话数据与记忆"),
    (re.compile(r"^docs/ux/"), "本地交互原型页"),
    (re.compile(r"^UPLOAD_RULES\.md$"), "本机上传说明"),
    (re.compile(r"^(venv|\.venv|env|ENV)/|(^|/)__pycache__/|\.py[co]$"), "虚拟环境 / 字节码缓存"),
    (re.compile(r"\.(db|sqlite|sqlite3|db-wal|db-shm)$", re.I), "数据库文件"),
    (re.compile(r"\.(key|pem|p12|pfx)$", re.I), "密钥 / 证书"),
    (re.compile(r"(^|/)\.env($|\.)"), "环境变量文件"),
    (re.compile(r"^(foodmap-)?backup[^/]*\.json$", re.I), "备份 JSON"),
    # 仓库里没有任何 .json 源码文件，根目录出现 json 基本都是导出备份
    (re.compile(r"^[^/]+\.json$", re.I), "根目录 JSON（多为备份导出）"),
    (re.compile(r"^\.tmp[^/]*(/|$)|^tmp[^/]*(/|$)"), "临时验证目录"),
    (re.compile(r"^(build|dist)/|\.(exe|msi)$", re.I), "打包产物"),
]

# 单个文件超过这个体积只提醒、不拦截（避免误伤大截图/资源）
SIZE_WARN = 5 * 1024 * 1024


def blocked_reason(path: str):
    """命中规则返回说明，否则返回 None。"""
    p = str(path).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    for pattern, why in RULES:
        if pattern.search(p):
            return why
    return None


def _git(*args) -> list:
    out = subprocess.run(["git", *args], capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [line for line in out.stdout.splitlines() if line.strip()]


def staged_files() -> list:
    # ACMR：新增/复制/修改/重命名；删除的文件不必检查
    return _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")


def tracked_files() -> list:
    return _git("ls-files")


def report(paths: list) -> int:
    blocked = [(p, blocked_reason(p)) for p in paths]
    blocked = [(p, why) for p, why in blocked if why]
    big = []
    for p in paths:
        try:
            size = os.path.getsize(p)
            if size > SIZE_WARN:
                big.append((p, size))
        except OSError:
            pass

    for p, size in big:
        print(f"[guard] 提醒：{p} 有 {size / 1048576:.1f} MB（可能是大资源，确认后再提交）")

    if not blocked:
        return 0
    print("[guard] 以下文件不该提交：")
    for p, why in blocked:
        print(f"  ✗ {p}   ← {why}")
    print("[guard] 这些是本地数据/密钥/临时产物。确认无误可用 git commit --no-verify 跳过（不建议）。")
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="提交前守卫生：拦截数据与密钥文件")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="检查暂存区（钩子用）")
    g.add_argument("--all", action="store_true", help="检查全部已跟踪文件（默认）")
    args = ap.parse_args(argv)

    paths = staged_files() if args.staged else tracked_files()
    if not paths:
        return 0
    return report(paths)


if __name__ == "__main__":
    sys.exit(main())
