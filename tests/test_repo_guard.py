"""提交前守卫（repo_guard.py）的回归：**绝不能误伤核心文件**。

这个守卫的价值全在"只拦数据、不拦代码"。所以第一优先的断言是：
仓库里所有已跟踪文件（51 个：源码/测试/文档/截图/脚本）都必须放行。
"""
import subprocess

import pytest

import repo_guard

CORE_FILES = [
    "app/main.py", "app/repository.py", "app/validate.py", "app/crypto.py", "app/db.py",
    "app/pathconf.py", "app/coords.py", "app/__init__.py",
    "static/index.html", "static/js/app.js", "static/css/style.css",
    "static/lib/vue/vue.global.min.js", "static/lib/leaflet/leaflet.js",
    "static/lib/leaflet/images/marker-icon.png", "static/favicon.svg", "static/favicon.ico",
    "tests/test_backup_roundtrip.py", "tests/test_api_crud.py", "tests/front-check.js",
    "tests/conftest.py", "tests/run-tests.bat", "tests/README.md",
    "docs/screenshots/04-dashboard.jpg",
    "README.md", "requirements.txt", "requirements-dev.txt", "pytest.ini",
    "seed_1000.py", "seed_demo.py", "health_check.py", "repo_guard.py",
    "start.bat", "start.sh", "setup.bat", "setup.sh",
    ".gitignore", ".gitattributes", "hooks/pre-commit",
]

FORBIDDEN = [
    ("data/foodmap.db", "库"),
    ("data/photos/abc.jpg", "照片"),
    ("data/.fernet.key", "加密钥匙"),
    ("data/backups/foodmap-before-seed.db", "旧备份"),
    ("dev-context/AI.md", "交接文档"),
    (".workbuddy/memory/MEMORY.md", "AI 记忆"),
    ("docs/ux/ux-plan.html", "原型页"),
    ("UPLOAD_RULES.md", "本机上传说明"),
    ("foodmap-backup-20261021-184900.json", "备份 JSON"),
    ("backup.json", "备份 JSON"),
    ("foo.json", "根目录 JSON"),
    (".env", "环境变量"),
    (".env.local", "环境变量"),
    ("server.key", "私钥"),
    ("cert.pem", "证书"),
    ("a.db-wal", "WAL"),
    ("dump.sqlite3", "数据库"),
    (".tmp-src/foodmap.db", "临时目录"),
    ("tmp/x.txt", "临时目录"),
    ("venv/Lib/site-packages/x.py", "虚拟环境"),
    ("tests/__pycache__/x.pyc", "缓存"),
    ("dist/foodmap.exe", "打包产物"),
]


def test_rules_never_block_core_files():
    for p in CORE_FILES:
        assert repo_guard.blocked_reason(p) is None, f"核心文件被误拦：{p}"


def test_every_tracked_file_passes():
    """以 git 实际索引为准，不靠手写清单——新增核心文件也不会被误伤。"""
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    if out.returncode != 0:
        pytest.skip("非 git 环境")
    files = [x for x in out.stdout.splitlines() if x.strip()]
    assert files, "没拿到已跟踪文件列表"
    blocked = [(p, repo_guard.blocked_reason(p)) for p in files if repo_guard.blocked_reason(p)]
    assert not blocked, f"已跟踪文件被守卫误拦：{blocked}"


def test_forbidden_patterns_are_blocked():
    missed = [p for p, _ in FORBIDDEN if repo_guard.blocked_reason(p) is None]
    assert not missed, f"这些应当被拦住：{missed}"


def test_path_normalization():
    assert repo_guard.blocked_reason("./data/x.db") is not None
    assert repo_guard.blocked_reason("data\\photos\\a.jpg") is not None   # 反斜杠路径
    assert repo_guard.blocked_reason("./app/main.py") is None


def test_staged_check_passes_on_clean_index(capsys):
    # 干净索引（无暂存）时应直接放行，返回 0
    rc = repo_guard.main(["--staged"])
    assert rc in (0,)


def test_report_exit_codes(capsys):
    """0 = 通过；2 = 发现问题（钩子据此拦截）；1 留给「脚本自身出错」。"""
    assert repo_guard.report([]) == 0
    assert repo_guard.report(["app/main.py", "README.md"]) == 0
    assert repo_guard.report(["data/foodmap.db"]) == 2
