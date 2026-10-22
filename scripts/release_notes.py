# -*- coding: utf-8 -*-
"""从 CHANGELOG.md 抽出当前版本的说明，生成 GitHub Release 的正文。

用法：
    python scripts/release_notes.py 2.0.0
    python scripts/release_notes.py v2.0.0      # 前缀 v 会被去掉
    python scripts/release_notes.py 2.0.0 --out release/release-notes.md

为什么要有这一步：Release 正文原来交给 GitHub 的自动生成（commit 列表），
用户点进下载页看到的是一堆「fix: xxx」的提交标题，既没有升级提示，也没说
哪个文件该下。现在正文统一来自 CHANGELOG，并且**抽不到就报错退出**，
当成一道发版闸门——没有变更说明的版本不放出去。

产物：`release/release-notes.md`（release/ 在 .gitignore 里，不入库）。
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
DEFAULT_OUT = ROOT / "release" / "release-notes.md"
REPO_URL = "https://github.com/perry466/foodie-trail"

# 正文尾部：下载哪个文件、怎么装、怎么校验。每个版本都一样，所以写死在脚本里，
# 而不是让每个 CHANGELOG 章节重复一遍。
FOOTER = """
---

### 下载哪个文件

| 文件 | 适合谁 |
| --- | --- |
| `FoodieTrail-{ver}-windows-x64-setup.exe` | 首次安装，或希望以后在应用内一键升级（**推荐**） |
| `FoodieTrail-{ver}-windows-x64.zip` | 绿色版，解压即用，不写注册表、不建开始菜单项 |

源码用户不需要下载：在项目目录 `git pull` 后重启服务即可。

### 怎么升级

打开应用 → 右上角「更多」→「设置」→「④ 关于与更新」→「检查更新」。
安装版会自己下载、校验、安装并重新打开；绿色版与源码版按提示手动替换。

> 如果你装的是 **1.0.2–1.0.7**，自动安装链路是坏的（会在安装阶段弹
> 「找不到 \\ 文件」），需要手动装一次 1.0.8 或更新的安装包，之后才能用应用内升级。

### 校验安装包

每个资产都带 GitHub 计算的 SHA-256（下载页的 digest），本地可以对一遍：

```powershell
Get-FileHash .\\FoodieTrail-{ver}-windows-x64-setup.exe -Algorithm SHA256
```

### 说明

- 安装包没有代码签名，Windows SmartScreen 可能提示一次：**更多信息 → 仍要运行**。
- 升级不会动 `data/` 目录（记录、照片、密钥都在里面），装完数据仍在。
- 本版本完整变更见 [CHANGELOG.md]({repo}/blob/v{ver}/CHANGELOG.md)。
"""


def _safe_console():
    """CI 的 Windows runner 是 cp1252，直接打印中文会 UnicodeEncodeError。"""
    ci = os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI")
    for stream in (sys.stdout, sys.stderr):
        try:
            if ci:
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def normalize_version(raw):
    v = (raw or "").strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    return v


def extract_section(text, version):
    """返回该版本章节的正文（不含标题行）；找不到返回 None。

    只认 `## [x.y.z]` 这种二级标题，`### 新增` 等三级标题属于章节内容。
    `## [Unreleased]` 永远不会被匹配到（版本号里不可能有字母）。
    """
    lines = text.splitlines()
    head = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]")
    start = end = None
    for i, line in enumerate(lines):
        m = head.match(line)
        if not m:
            continue
        if start is not None:            # 到了下一个版本，本节到此为止
            end = i
            break
        if m.group(1) == version:
            start = i + 1
    if start is None:
        return None
    body = lines[start:end] if end is not None else lines[start:]

    # 去掉章节尾部的空行与版本分隔线（---），它们在正文里没有意义；
    # 章节内部的空行要保留——Markdown 靠它分段。
    while body and (not body[-1].strip() or body[-1].strip() == "---"):
        body.pop()
    return "\n".join(body).strip() or None


def main():
    _safe_console()
    ap = argparse.ArgumentParser(description="按 CHANGELOG 生成 Release 正文")
    ap.add_argument("version", help="版本号，如 2.0.0（可带 v 前缀）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出文件路径")
    ap.add_argument("--print", dest="show", action="store_true", help="同时打印正文")
    args = ap.parse_args()

    version = normalize_version(args.version)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"[release-notes] 版本号不合法：{args.version}")
        return 2

    if not CHANGELOG.exists():
        print("::error::CHANGELOG.md 不存在，无法生成发布说明")
        return 1

    body = extract_section(CHANGELOG.read_text(encoding="utf-8"), version)
    if not body:
        print(f"::error::CHANGELOG.md 里没有 [{version}] 章节——"
              f"发版前请先补上这个版本的变更说明")
        return 1

    text = (f"## 本版本变更\n\n{body}\n"
            + FOOTER.format(ver=version, repo=REPO_URL)).lstrip() + "\n"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")

    print(f"[release-notes] v{version} 正文 {len(text)} 字符 → {out}")
    if args.show:
        print("-" * 60)
        print(text)
        print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
