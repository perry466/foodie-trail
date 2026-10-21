"""打包相关回归：路径解析、spec 关键配置、发布 zip 不夹带用户数据。

这几条防的是「打包后才发现」的问题——数据写进临时目录被删、
漏 collect_all 导致启动即崩、构建机把 data/ 打进 Release。
"""
import importlib
import sys as _sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ---------- 1. 打包后的路径解析 ----------
def test_frozen_paths_use_meipass_and_exe_dir(monkeypatch, tmp_path):
    import app.pathconf as pc

    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    fake_exe = exe_dir / "FoodieTrail.exe"
    fake_exe.write_text("", encoding="utf-8")
    bundle = tmp_path / "bundle"
    (bundle / "static").mkdir(parents=True)

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(_sys, "executable", str(fake_exe))
    monkeypatch.delenv("FOODMAP_DATA_DIR", raising=False)

    try:
        mod = importlib.reload(pc)
        assert mod.FROZEN is True
        assert Path(mod.STATIC_DIR) == bundle / "static"          # 资源在解包目录
        assert Path(mod.DATA_DIR) == exe_dir / "data"             # 数据在 exe 同级
        assert Path(mod.PHOTOS_DIR) == exe_dir / "data" / "photos"
    finally:
        monkeypatch.undo()
        importlib.reload(pc)                                      # 恢复源码模式常量


def test_source_mode_paths_unchanged(monkeypatch):
    import app.pathconf as pc

    monkeypatch.delenv("FOODMAP_DATA_DIR", raising=False)
    try:
        mod = importlib.reload(pc)
        assert mod.FROZEN is False
        assert Path(mod.STATIC_DIR) == ROOT / "static"
        assert Path(mod.DATA_DIR) == ROOT / "data"
    finally:
        # 必须先恢复环境变量再 reload，否则模块会停在「真实 data/」状态，
        # 后面的用例拿到的 PHOTOS_DIR 就指到真实目录去了（踩过一次）。
        monkeypatch.undo()
        importlib.reload(pc)


def test_pathconf_restored_for_other_tests():
    """兜底：上面两个用例跑完后，pathconf 必须仍指向测试临时目录。"""
    import os

    import app.pathconf as pc

    assert os.environ.get("FOODMAP_DATA_DIR"), "测试环境应设置 FOODMAP_DATA_DIR"
    assert Path(pc.DATA_DIR) == Path(os.environ["FOODMAP_DATA_DIR"])
    assert Path(pc.STATIC_DIR) == ROOT / "static"


# ---------- 2. spec 的关键配置不能被"顺手优化"掉 ----------
def test_spec_keeps_required_settings():
    text = (ROOT / "FoodieTrail.spec").read_text(encoding="utf-8")
    for needle in (
        '("static", "static")',      # 前端必须打进包
        '("assets", "assets")',      # 图标 / 托盘图
        "console=False",             # 无控制台
        "pydantic_core",             # v2 二进制扩展
        "uvicorn",
        "cryptography",
        "pystray",
    ):
        assert needle in text, f"spec 缺少 {needle}"


def test_launcher_guards_stdout_and_single_instance():
    text = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "devnull" in text                       # GUI 模式下 stderr 必须被替换
    assert "CreateMutexW" in text                  # 单实例
    assert "should_exit" in text                   # 托盘退出要能停掉 uvicorn
    assert "FOODMAP_HEADLESS" in text              # 冒烟测试用


# ---------- 3. 发布 zip 绝不夹带 data/ ----------
def test_release_zip_skips_user_data(tmp_path, monkeypatch):
    _sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import make_release_zip as mrz
    finally:
        _sys.path.pop(0)

    dist = tmp_path / "dist" / "FoodieTrail"
    (dist / "_internal").mkdir(parents=True)
    (dist / "FoodieTrail.exe").write_bytes(b"MZ")
    (dist / "_internal" / "python314.dll").write_bytes(b"dll")
    (dist / "data").mkdir()
    (dist / "data" / "foodmap.db").write_bytes(b"SQLite private data")
    (dist / "data" / "photos").mkdir()
    (dist / "data" / "photos" / "a.jpg").write_bytes(b"jpeg")
    (dist / "app.log").write_text("secret log", encoding="utf-8")

    out = tmp_path / "release"
    target, count = mrz.build_zip(dist, out, "v9.9.9")

    names = zipfile.ZipFile(target).namelist()
    assert "FoodieTrail/FoodieTrail.exe" in names
    assert "FoodieTrail/_internal/python314.dll" in names
    assert not any("/data/" in n or n.endswith("app.log") for n in names), names
    # 说明文件会被额外放到 exe 同级（存在才加），其余文件数 = 2
    assert count == (3 if "FoodieTrail/快速开始.txt" in names else 2), names
    assert target.name == "FoodieTrail-9.9.9-windows-x64.zip"


# ---------- 4. 发布脚本必须能跑在 cp1252 控制台上 ----------
def test_release_scripts_survive_cp1252_console(monkeypatch):
    """GitHub Actions 的 Windows runner 控制台是 cp1252。

    在那里 `print("[smoke] ✓ …")` 或打印中文都会 UnicodeEncodeError，
    整步直接失败——v1.0.0 首次发布就死在这（日志里是 cp1252.py: encode）。
    两个发布脚本都必须在开头调 `_safe_console()`：
    CI 里切 UTF-8（日志中文不乱码），本地只替换编不了的字符。
    """
    import io

    for name in ("smoke_packaged", "make_release_zip"):
        _sys.path.insert(0, str(ROOT / "scripts"))
        try:
            mod = __import__(name)
        finally:
            _sys.path.pop(0)
        assert hasattr(mod, "_safe_console"), f"{name} 缺少 _safe_console()"

        for is_ci in (False, True):
            if is_ci:
                monkeypatch.setenv("GITHUB_ACTIONS", "true")
            else:
                monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
                monkeypatch.delenv("CI", raising=False)

            buf = io.BytesIO()
            # 刻意用 strict：修复前这里会抛 UnicodeEncodeError
            stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict", newline="")
            monkeypatch.setattr(_sys, "stdout", stream)
            try:
                mod._safe_console()
                print(f"[{name}] ✓ 中文与符号")
                stream.flush()
                raw = buf.getvalue()
                assert raw, f"{name} 在 cp1252 下什么都没输出"
                if is_ci:
                    raw.decode("utf-8")          # CI 里必须是 UTF-8，日志才不乱码
            finally:
                stream.detach()
                monkeypatch.undo()
