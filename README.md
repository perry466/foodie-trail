# 美食地图 Foodie Trail

本地运行的个人美食记录应用：在地图上标记吃过的、想去的店，记录评分、标签、人均与照片，用列表和看板回看自己的口味分布。

数据全部保存在本机，不登录、不上云、不需要外部数据库。

![主界面：地图打点与聚合](docs/screenshots/01-map.jpg)

## 功能

- **地图记录**：点击地图选点，或用地址联想（输入即出候选，↑↓ 选择、Enter 确认）；支持「定位我」。
- **完整字段**：名称、评分（1–5 星）、标签、营业时间（按周设置时段）、人均消费、打卡状态（想去 / 去过 / 收藏）、备注、照片。
- **精确筛选**：关键词、星级、标签多选、打卡状态、人均区间、视野内、草稿范围；条件可叠加，结果实时联动地图。
- **记录列表**：搜索、排序、滚动加载（超长列表不会一次性塞进 DOM），支持多选后批量删除（全选 / 反选 / 清空）。
- **数据看板**：总记录、打卡率、待拔草、人均中位数、状态构成、评分与价位分布、高频标签、近 12 个月录入趋势，图表可点击直接筛到列表。
- **照片**：上传后自动校正方向并压缩，详情页支持灯箱浏览。
- **草稿**：未完成的记录可存为草稿，仍显示在列表中并带角标，可单独筛选。
- **备份**：导出 JSON（可含照片），换机或重装后可完整导入。
- **主题**：深色 / 浅色切换；快捷键 `n` 新建、`/` 搜索、`Esc` 关闭面板。

## 界面

筛选面板：星级、标签、打卡状态、人均价位、草稿范围，条件即时生效。

![筛选面板](docs/screenshots/03-filter.jpg)

数据看板：从总量、分布到标签偏好，图表点击即可下钻。

![数据看板](docs/screenshots/04-dashboard.jpg)

记录详情：点击图钉或列表项打开，卡片锚定在对应位置。

![记录详情](docs/screenshots/05-detail.jpg)

> 截图使用虚构的演示数据。未配置高德 Key 时地图自动使用本地 Leaflet 渲染，底图为高德瓦片。

## 技术栈

- 后端：FastAPI、SQLite、cryptography（Fernet 加密）、Pillow、httpx。
- 前端：原生 JavaScript + Vue 3（本地生产版）、Leaflet 与 Leaflet.markercluster；高德 JS API 可选。
- 形态：前后端同进程，无外部服务依赖；服务只监听 `127.0.0.1`，仅接受本机页面来源。

## 目录结构

```
foodie-trail/
├── app/                  # FastAPI 后端
│   ├── main.py           # 路由、请求模型、图片压缩、高德代理
│   ├── repository.py     # 数据访问层（SQLite 实现）
│   ├── db.py             # 建表与连接管理（WAL、外键）
│   ├── crypto.py         # 高德 Key 的 Fernet 加解密
│   ├── coords.py         # 坐标转换与距离计算
│   ├── validate.py       # 字段归一化与导入校验（导入/读取共用）
│   └── pathconf.py       # 路径常量与端口探测
├── static/               # 前端
│   ├── index.html        # 页面骨架与模板
│   ├── css/style.css     # 样式（亮 / 暗主题）
│   ├── js/app.js         # 地图适配层与界面逻辑
│   ├── lib/              # 本地依赖：Vue、Leaflet、markercluster
│   └── favicon.svg/.ico  # 站点图标
├── docs/screenshots/     # 界面截图
├── tests/                # 回归测试（pytest + Node 断言）
├── health_check.py       # 数据体检（只读）：库完整性、照片、脏数据、演示数据
├── seed_1000.py          # 演示数据生成脚本（可选）
├── requirements.txt      # 运行依赖
├── requirements-dev.txt  # 测试依赖
├── pytest.ini            # pytest 配置
├── setup.bat / setup.sh  # 一键创建 venv 并安装依赖
├── start.bat / start.sh  # 启动脚本（探测依赖，失效自动回退）
└── README.md
```

## 运行方式

1. 准备环境（推荐一键脚本，会自动创建 venv 并装齐运行 + 测试依赖）：

   ```bat
   setup.bat
   ```

   ```bash
   ./setup.sh
   ```

   手动方式：

   ```bash
   python -m venv venv
   venv\Scripts\activate        # Windows
   pip install -r requirements.txt -r requirements-dev.txt
   ```

2. 启动：

   ```bash
   python -m app.main
   ```

   也可直接运行 `start.bat`（Windows）或 `start.sh`（Linux / macOS）。启动脚本会先验证解释器能 `import fastapi, uvicorn, PIL`，venv 失效（换机器、升级/卸载过 Python）时自动回退到 `py -3` / `python`，都不可用则打印修复指引而不是直接崩掉。

3. 访问：应用会在 `20000–65535` 中探测一个空闲端口，写入 `data/.last_port` 并打印在启动日志里，用浏览器打开该地址即可。

> 后端使用包内相对导入，必须从项目根目录以 `python -m app.main` 启动，不能直接执行 `python app/main.py`。

需要一些数据来体验时，可运行 `python seed_1000.py --count 200 --yes` 生成演示记录。

该脚本**会写入正在运行的应用**，因此加了护栏：数据目录跟随 `FOODMAP_DATA_DIR`（不再写死项目 `data/`）、
启动前先探测服务（连不上就一条都不写）、连续失败 5 条自动中止。只想看看目标而不写，用 `--dry-run`；
想指定地址用 `--base http://127.0.0.1:端口`。

**写库脚本的闸门**：只要数据目录是项目下的真实 `data/`（没有用 `FOODMAP_DATA_DIR` 指到别处），
`seed_1000.py` 与 `seed_demo.py` 都会拒绝执行并提示加 `--yes`——避免"以为在试跑、其实在写真实库"。

## 测试

```bash
python -m pytest tests -q      # 后端 133 个用例
node tests/front-check.js      # 前端 38 项断言（需 Node 18+）
```

覆盖范围：常规 CRUD、照片上传/读取/删除、备份导出→清库→导入往返（含照片字节）、导入字段校验与畸形数据处理，以及草稿范围、密钥语义等回归点。测试使用临时数据目录（`FOODMAP_DATA_DIR`），不会读写 `data/`。

Windows 下可运行 `tests\run-tests.bat` 一次跑完：退出码 0 全部通过、1 有失败、2 缺少 Node 导致前端部分跳过。

## 配置高德地图（可选）

不配置 Key 时使用内置 Leaflet 兜底，地图、打点、筛选全部可用，仅地址搜索与路径规划不可用。若需要高德底图和地址服务，在应用右上角「设置」中填写两类 Key：

| Key | 用途 |
|---|---|
| Web 端（JS API）Key + 安全密钥 securityJsCode | 浏览器加载高德底图 |
| Web 服务 Key | 地址联想、地址解析、驾车路线（后端代理） |

两类 Key 用途不同，只填前者时底图正常但地址搜索不可用。Key 经 Fernet 加密后仅存本地数据库；已保存的值以掩码回显，输入框留空表示保持原值。

## 数据体检（只读）

随时可以确认「库没坏、照片没丢、没混进脏数据」：

```bash
python health_check.py          # 基础检查
python health_check.py --deep   # 额外逐张解码验证照片
```

检查项：SQLite 完整性、表结构、记录/照片计数、字段越界（星级、经纬度、人均、时间戳、tags JSON）、
照片行对应文件是否缺失/为 0 字节、磁盘上的孤儿照片、`.fernet.key` 是否可用、WAL 大小、
以及是否混入演示数据。**只读，不修改任何东西**；退出码 0 = 无致命问题，1 = 发现问题。

## 数据隐私

- 所有数据位于 `data/`：`foodmap.db`、`photos/`、加密主密钥 `.fernet.key`，均不进入版本库。
- 服务只监听 `127.0.0.1` 并校验请求来源，外部站点无法跨站读写记录、照片或 Key。
- 迁移到另一台机器时，复制整个 `data/` 目录即可；只拷 `foodmap.db` 而不拷 `.fernet.key` 会导致已保存的 Key 无法解密。
- `.fernet.key` 万一损坏（被清空、拷贝中断、杀软改写），启动时会自动把它改名留档并生成新钥匙继续运行——记录与照片不受影响，只是此前保存的高德 Key 需要重填。

## 提交前守卫（避免把数据带进仓库）

`data/` 已在 `.gitignore` 里，但历史上出现过"临时目录没被忽略、差点被 `git add -A` 带上去"的情况。
仓库里有两道保险：

1. **`repo_guard.py`**（只按路径判断，默认放行一切源码与资源）：

   ```bash
   python repo_guard.py            # 检查全部已跟踪文件（应为 0 命中）
   python repo_guard.py --staged   # 检查暂存区
   ```

   拦：`data/`、`dev-context/`、`.workbuddy/`、`docs/ux/`、`*.db`、`*.key`/`*.pem`、`.env*`、
   根目录 `*.json`（多为导出备份）、`.tmp-*`/`tmp/`、`venv/`、`__pycache__`、`dist/*.exe`。
   **不拦**：`app/`、`static/`（含截图与 Leaflet 资源）、`tests/`（含 `test_backup_roundtrip.py`）、
   文档、脚本、`hooks/`。

2. **pre-commit 钩子**（每个 clone 各装一次，只影响本机）：

   ```bash
   cat hooks/pre-commit > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
   ```

   提交时若暂存区里有上述文件会直接拒绝并列出文件名；确需跳过用 `git commit --no-verify`。

`tests/test_repo_guard.py` 会拿 `git ls-files` 的真实清单断言"没有任何已跟踪文件被误拦"，
所以以后新增核心文件也不会被守卫挡住。

## 许可证

本项目供个人学习与使用。
