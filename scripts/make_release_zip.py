# -*- coding: utf-8 -*-
"""把 dist/FoodieTrail 打成发布用 zip（保留顶层目录，解开就是一个文件夹）。

用法：
    python scripts/make_release_zip.py v1.0.0
    python scripts/make_release_zip.py            # 版本号回落成 dev

安全约定：**绝不把 exe 目录里的 data/ 打进包**——那是开发者自己跑过
之后留下的真实数据（库、照片、加密钥匙）。构建机上一旦漏掉这行过滤，
就等于把私人数据发到 Release 上。
"""
import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "FoodieTrail"
OUT_DIR = ROOT / "release"
SKIP_TOP = {"data", "app.log"}          # 运行产物，不进发布包


def build_zip(dist: Path, out_dir: Path, version: str) -> tuple:
    """把 dist 目录压成发布 zip，返回 (路径, 文件数)。

    `data/` 与 `app.log` 永远跳过：那是构建机跑过一次之后留下的真实数据。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ver = str(version).lstrip("vV")
    target = out_dir / f"FoodieTrail-{ver}-windows-x64.zip"

    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(dist.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(dist)
            if rel.parts and rel.parts[0] in SKIP_TOP:
                continue
            z.write(path, Path("FoodieTrail") / rel)
            count += 1
        guide = ROOT / "packaging" / "快速开始.txt"
        if guide.is_file():                     # 放在 exe 旁边，解开就能看到
            z.write(guide, Path("FoodieTrail") / guide.name)
            count += 1
    return target, count


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="打包 dist/FoodieTrail 为发布 zip")
    ap.add_argument("version", nargs="?", default="dev", help="版本号，如 v1.0.0 或 1.0.0")
    args = ap.parse_args(argv)

    if not DIST.is_dir():
        print(f"[zip] 找不到 {DIST}，请先运行：pyinstaller FoodieTrail.spec --noconfirm")
        return 1

    target, count = build_zip(DIST, OUT_DIR, args.version)
    size = target.stat().st_size / 1048576
    print(f"[zip] 已生成 {target}（{count} 个文件，{size:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
