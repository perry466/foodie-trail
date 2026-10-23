# -*- coding: utf-8 -*-
"""生成 latest.json——应用内检查更新的**不依赖 GitHub API 额度**的数据源。

背景（2026-10-22/23 实踩）：`api.github.com` 的匿名额度只有 60 次/小时、按出口 IP 计。
发版日轮询 CI、代理共享出口被别人用光，都会让检查更新拿到 403；网页 302 兜底只能拿
到版本号、拿不到资产地址与 sha256，应用就无法自动安装——用户被迫手动下载。

解法：发版时把版本号、资产下载地址、体积、sha256、变更说明写进一个 `latest.json`，
**作为 Release 资产一并上传**。应用改走
`https://github.com/{REPO}/releases/latest/download/latest.json`
——这个固定地址由 GitHub 重定向到最新 Release 的同名资产，走的是普通下载域名，
**不消耗 API 额度**，而应用下载 25MB 安装包走的就是同一批域名，可达性已被验证。

用法（CI 里在 Publish 之前）：
    python scripts/make_latest_json.py 2.0.4 \\
        --setup installer/Output/FoodieTrail-2.0.4-windows-x64-setup.exe \\
        --zip release/FoodieTrail-2.0.4-windows-x64.zip

产物：`release/latest.json`（release/ 在 .gitignore 里，不入库）。
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "release" / "latest.json"
REPO_URL = "https://github.com/perry466/foodie-trail"


def _safe_console():
    """CI 控制台常是 cp1252，中文与 ✓ 会 UnicodeEncodeError（老坑，见 release_notes.py）。"""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _asset(path: Path, version: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"[latest] 找不到 {path}，请先完成构建")
    digest = _sha256(path)
    print(f"[latest] {path.name}: {path.stat().st_size} bytes, sha256={digest[:16]}…")
    return {
        "name": path.name,
        "url": f"{REPO_URL}/releases/download/v{version}/{path.name}",
        "size": path.stat().st_size,
        "sha256": digest,
    }


def build(version: str, setup: Path, zip_path: Path, user_notes: str) -> dict:
    # 版本号是唯一防线：latest.json 里的 version 与 tag 不一致时，装好的新版本
    # 仍会认为自己是旧版、每次启动都提示更新（CI 的 tag 闸门只管 tag，管不到这里）。
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"[latest] 版本号格式不对：{version!r}（应为 x.y.z）")
    published = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {
        "version": version,
        "publishedAt": published,
        "setup": _asset(setup, version),
        "zip": _asset(zip_path, version),
        # notes 是应用内「可升级到 vX」面板显示的内容——必须是用户视角的人话
        # （加了什么功能、修了什么），不是 CHANGELOG 的技术全文。
        # 2026-10-23 用户反馈：把开发者日志全文塞给用户看是错的。
        "notes": user_notes,
    }
    if not data["setup"]["sha256"]:
        raise SystemExit("[latest] setup 缺少 sha256，拒绝生成（没有校验值就不能自动安装）")
    return data


def _user_notes(version: str, explicit: str | None) -> str:
    """应用内更新面板显示的说明：只给用户视角的人话。

    优先级：显式文件 > CHANGELOG 的「### 给用户的说明」小节 > 兜底一句话。
    绝不把 CHANGELOG 技术全文塞给用户（2026-10-23 用户反馈定下的规矩）。
    """
    fallback = "本次更新修复了一些问题，提升了稳定性。"
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise SystemExit(f"[latest] 找不到用户说明文件 {p}")
        body = p.read_text(encoding="utf-8").strip()
        return body or fallback
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.release_notes import extract_user_notes
        body = extract_user_notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
        return body or fallback
    except SystemExit:
        raise
    except Exception as e:
        print(f"[latest] 抽取用户说明失败（{e}），使用兜底文案")
        return fallback


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 Release 的 latest.json")
    ap.add_argument("version", help="版本号，如 2.0.4 或 v2.0.4")
    ap.add_argument("--setup", required=True, help="setup.exe 路径")
    ap.add_argument("--zip", dest="zip_path", required=True, help="portable zip 路径")
    ap.add_argument("--user-notes", dest="user_notes", default=None,
                    help="用户版说明文本文件；缺省时自动从 CHANGELOG 的「给用户的说明」小节抽取")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    _safe_console()

    version = args.version.lstrip("v")
    notes = _user_notes(version, args.user_notes)
    print(f"[latest] 用户说明：{notes.splitlines()[0][:60]}…")
    data = build(version, Path(args.setup), Path(args.zip_path), notes)
    out = Path(args.out)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[latest] 已写入 {out}（version={version}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
