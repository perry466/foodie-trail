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

需要一些数据来体验时，可运行 `python seed_1000.py` 生成演示记录（会写入当前数据目录）。

## 测试

```bash
python -m pytest tests -q      # 后端 115 个用例
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

## 数据隐私

- 所有数据位于 `data/`：`foodmap.db`、`photos/`、加密主密钥 `.fernet.key`，均不进入版本库。
- 服务只监听 `127.0.0.1` 并校验请求来源，外部站点无法跨站读写记录、照片或 Key。
- 迁移到另一台机器时，复制整个 `data/` 目录即可；只拷 `foodmap.db` 而不拷 `.fernet.key` 会导致已保存的 Key 无法解密。
- `.fernet.key` 万一损坏（被清空、拷贝中断、杀软改写），启动时会自动把它改名留档并生成新钥匙继续运行——记录与照片不受影响，只是此前保存的高德 Key 需要重填。

## 许可证

本项目供个人学习与使用。
