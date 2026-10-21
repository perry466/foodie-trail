# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Foodie Trail → Windows 绿色目录版）。

用法（项目根目录）：
    pip install -r requirements.txt -r requirements-build.txt
    pyinstaller FoodieTrail.spec --noconfirm

产物：

    dist/FoodieTrail/
    ├── FoodieTrail.exe       双击启动（无控制台，托盘常驻）
    ├── data/                 首次运行自动创建：库、照片、加密钥匙、日志
    ├── _internal/            依赖与静态资源，不要动
    └── 快速开始.txt

几条不能删的配置，删了就会在运行时炸：

- `static` / `assets` 必须以 datas 打进包：路径由 `app/pathconf.py` 的
  `BUNDLE_DIR`（= `_MEIPASS`）解析，源码模式则读仓库目录。
- `pydantic` / `pydantic_core`：v2 带二进制扩展，必须 collect_all。
- `uvicorn`：protocols / loops 按名字动态 import，漏了就是启动即崩。
- `cryptography`：Rust 扩展 + 后端按平台选择，让 PyInstaller 自己收集容易漏。
- `PIL` / `pystray`：托盘图标与图片处理，Pillow 的插件、pystray 的 win32 后端都是动态加载。
- `console=False`：GUI 子系统，没有黑窗口；配合 `launcher.py` 里对
  stdout/stderr 的重定向，否则 uvicorn 写日志会把服务线程写死。
"""
from PyInstaller.utils.hooks import collect_all

datas = [
    ("static", "static"),              # 前端（无需构建，原样带上）
    ("assets", "assets"),              # 应用 / 托盘图标
]
# 说明文件不放这里：PyInstaller 6 会把 datas 全部塞进 _internal/，用户看不到。
# 由 scripts/make_release_zip.py 与 installer/FoodieTrail.iss 放到 exe 旁边。
binaries = []
hiddenimports = []

for _pkg in ("pydantic", "pydantic_core", "uvicorn", "PIL", "cryptography", "pystray"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

hiddenimports += [
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "app.main",
    "app.db",
    "app.repository",
    "app.validate",
    "app.crypto",
    "app.coords",
    "app.pathconf",
]

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter", "unittest", "pydoc"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FoodieTrail",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # 无控制台窗口
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FoodieTrail",
)
