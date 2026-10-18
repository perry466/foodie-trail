# 美食地图 Foodie Trail

## 项目简介

美食地图（Foodie Trail）是一款本地运行的个人美食记录 Web 应用。用户在地图上按位置添加美食记录，支持评分、标签、营业时间、人均、打卡状态、照片与备注，并提供搜索、精确筛选、看板统计与数据导入导出。所有数据均保存在本机，不依赖任何外部服务器。

## 功能特性

- 全屏地图概览：优先使用高德 JS API 底图；未配置 Key 时回退本地 Leaflet + 高德瓦片，无需 Key 亦可显示底图、打点与查看记录。
- 按位置添加与编辑记录：地图点选、定位我，或在地址框输入即出联想结果（↑↓ 选择、Enter 确认，无需按回车）。
- 记录字段：名称、经纬度、评分（精确星级 1–5）、标签、营业时间、人均消费、打卡状态、备注、照片。
- 检索与筛选：关键词搜索、精确星级筛选、标签多选筛选、打卡状态筛选、人均价位筛选、视野内筛选。
- 批量删除：列表内多选，支持全选 / 反选 / 清空，一次确认删除。
- 可视化交互：详情卡片锚定图钉、悬停预览、缩略图网格。
- 数据看板：概览指标（总记录 / 打卡率 / 待拔草 / 人均中位数）、状态构成、评分与价位分布、高频标签、近 12 个月录入趋势、高分待拔草与积压清单、数据健康度；图表可点击直接筛到列表。
- 照片管理：上传后自动进行方向校正与压缩。
- 高德 Key 配置：支持 JS API Key、安全密钥、Web 服务 Key，均经 Fernet 加密后仅存入本地数据库。
- 高德代理：POI 搜索、地理编码、路径规划。
- 坐标处理：WGS84 与 GCJ02 互转、附近距离计算。
- 智能推荐：附近推荐、同类相似推荐。
- 数据互通：支持导入与导出。
- 界面主题：深色 / 浅色切换。
- 草稿：未完成记录可暂存为草稿。

## 技术栈

- 后端：FastAPI、SQLite、cryptography（Fernet 加密）、Pillow、aiofiles、httpx。
- 前端：原生 JavaScript（Vue 3 经 CDN 引入）、本地 Leaflet 与 Leaflet.markercluster 库（库文件本地化；底图与 Vue 仍需联网）。
- 架构特点：无外部数据库服务，前后端同进程运行，纯本地部署。

## 目录结构

```
foodie-trail/
├── app/                  # FastAPI 后端
│   ├── main.py           # API 入口（路由、请求模型、图片压缩、高德代理）
│   ├── repository.py     # 数据访问层（SQLite 实现，预留 Postgres 接口）
│   ├── db.py             # 建库与连接管理（WAL 模式、外键约束）
│   ├── crypto.py         # 高德 Key 的 Fernet 加解密
│   ├── coords.py         # 坐标转换与距离计算
│   └── pathconf.py       # 路径常量与端口探测
├── static/               # 前端资源
│   ├── index.html        # 应用主页面
│   ├── css/style.css     # 样式表
│   ├── js/app.js         # 核心逻辑（地图适配层 + Vue 应用）
│   └── lib/              # 本地 Leaflet 与 markercluster 库（库文件本地化）
├── requirements.txt      # Python 依赖清单
├── start.bat / start.sh  # 启动脚本（等价于 python -m app.main）
├── seed_1000.py          # 演示数据生成脚本（可选，固定随机种子可复现）
├── UPLOAD_RULES.md       # 仓库上传规范（隐私与忽略规则）
└── README.md             # 本文档
```

## 运行方式

1. 准备虚拟环境与依赖：

   ```bash
   python -m venv venv
   venv\Scripts\activate        # Windows
   pip install -r requirements.txt
   ```

2. 启动应用：

   ```bash
   python -m app.main
   ```

   亦可直接运行 `start.bat`（Windows）或 `start.sh`（Linux / macOS）。

3. 访问应用：

   应用启动后会在 `20000–65535` 区间内探测一个空闲端口，端口号写入 `data/.last_port` 并打印于启动日志。浏览器打开该地址即可使用。

   说明：因后端使用包内相对导入，必须以 `python -m app.main` 方式从项目根目录启动，不可直接执行 `python app/main.py`。

## 配置高德地图（可选）

默认无地图 Key 时使用本地 Leaflet + 高德瓦片，添加与浏览记录功能不受影响。若需启用高德底图及 POI 搜索、路径规划等功能：

1. 在高德开放平台申请 JS API Key、安全密钥与 Web 服务 Key。
2. 在应用「设置」面板录入。Key 经 Fernet 加密后仅保存于本地数据库 `data/foodmap.db`，不会出现在源码中，也不会随仓库上传。

## 数据隐私

- 所有用户数据（数据库 `data/foodmap.db`、加密主密钥 `data/.fernet.key`、照片目录 `data/photos/`）均位于 `data/` 目录，已被 `.gitignore` 完全忽略，不会进入本仓库。
- 克隆本仓库后，需自行通过 `seed_1000.py` 生成演示数据，或在应用界面中手动添加记录。

## 上传规范

本仓库遵循"非必要不上传"原则，详见 `UPLOAD_RULES.md`：运行时数据、密钥、虚拟环境、缓存、打包产物与本地开发上下文一律不入库，仅提交运行所需源码与必要文档。

## 许可证

本项目供个人学习与使用。
