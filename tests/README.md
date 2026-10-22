# 回归测试

两条命令，覆盖最容易复发的那些回归点（含「备份照片损坏不能删掉原照片」）。测试全部在临时目录里跑，
**不会创建、修改或删除 `data/foodmap.db`**。

## 一、跑测试

### 1. 后端（pytest，183 个用例）

```bat
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m pytest tests -q
```

预期输出：`183 passed`。

### 2. 前端（Node 断言，48 项）

```bat
node tests\front-check.js
```

预期输出：`通过 48 项` 且退出码为 0。缺 Node 时先装 Node 18+；Windows 上一般已有 `node`。

### 3. 一条命令全跑

```bat
tests\run-tests.bat
```

退出码：

| 退出码 | 含义 |
|---|---|
| 0 | 两条线都通过（`ALL TESTS PASSED`） |
| 1 | 有用例失败（`TESTS FAILED`） |
| 2 | 部分跳过：环境里找不到 `node`，前端断言未执行（`PARTIAL`） |

缺少 Node 时**不会**报告全部通过，而是以退出码 2 结束并明确写出“前端检查被跳过”。

## 二、测试怎么隔离数据

`app/pathconf.py` 支持环境变量 `FOODMAP_DATA_DIR`：

- 不设置：`D:\project\foodie-trail\data`（正常使用）。
- 设置后：数据库、照片、`.fernet.key`、`.last_port` 全部落到该目录。

`tests/conftest.py` 在导入 `app` **之前**把它指向 `%TEMP%\foodmap-test-xxxx`，会话结束自动删除。
想自己验证隔离是否生效：

```bat
set FOODMAP_DATA_DIR=D:\tmp\fm-test
venv\Scripts\python.exe -m app.main
```

此时界面是空的（新库），关掉后真实数据仍在原处。

## 三、测试覆盖了什么

| 文件 | 覆盖点 |
|---|---|
| `test_regressions.py::test_export_includes_drafts_by_default` | `/api/export` 默认包含草稿 |
| `...::test_export_still_honours_include_drafts_false` | 显式 `includeDrafts=0` 仍可排除（参数没被写死） |
| `...::test_export_keeps_other_filters` | 导出仍受关键词 / 标签等筛选影响 |
| `...::test_records_default_excludes_drafts` | 列表接口默认不含草稿 |
| `...::test_records_drafts_only` | `draftsOnly=1` 只返回草稿 |
| `...::test_drafts_only_has_priority_over_include_drafts` | 只传 `draftsOnly=1` 也是草稿优先 |
| `...::test_security_kept_when_omitted_or_empty` | 不传 / 传空串 / 传空白都不清除安全密钥；传新值正常写入 |
| `...::test_web_key_only_update_keeps_js_and_security` | 只改 Web 服务 Key 时 JS Key 与安全密钥不变 |
| `...::test_clear_security_only` | 单独清除安全密钥，JS Key 与 Web Key 保留 |
| `test_backup_roundtrip.py::test_corrupt_photos_in_backup_keep_existing_photos` | **备份照片损坏时，原有照片必须保留**（导入不能先删后写） |
| `...::test_partial_photo_set_is_not_applied` | 一张坏照片 → 整批不采用，不留半套照片 |
| `...::test_explicit_empty_photo_set_clears_old_photos` | 备份声明含照片且为空 → 才允许清空 |
| `...::test_meta_backup_does_not_touch_photos` | `mode=meta` 备份不动已有照片 |
| `...::test_legacy_backup_with_empty_photos_keeps_existing` | 老格式备份（无 `photosIncluded`）保守保留 |
| `...::test_valid_photos_still_replace_old_ones` | 健康备份仍正常覆盖并清理旧文件 |
| `test_import_validation.py::test_export_does_not_read_outside_photos_dir` | 被篡改的 `photos.path` 不能借导出读走目录外文件 |
| `test_api_crud.py::test_sort_field_and_direction_are_whitelisted` | 排序字段/方向白名单，注入串被丢弃 |
| `test_api_crud.py::test_price_max_is_exclusive` | 人均价位 `[下限, 上限)`：30–60 不含 60 |
| `...::test_price_buckets_match_api_filters` | 看板分桶数 == 同条件列表查询条数 |
| `...::test_single_delete_keeps_file_when_db_fails` | 删记录时数据库失败 → 照片文件仍在 |
| `...::test_batch_delete_keeps_files_when_db_fails` | 批量删除同样「先删库再删文件」 |
| `...::test_photo_delete_keeps_file_when_db_fails` | 单张照片删除同样顺序 |
| `...::test_photo_path_uses_forward_slash` | 新照片路径存正斜杠，可跨系统搬 data/ |
| `...::test_legacy_backslash_photo_path_is_normalized` | 老库反斜杠路径可读 + `init_db` 迁移 |
| `...::test_dashboard_photo_total_excludes_drafts` | 看板照片数不含草稿照片 |
| `test_write_validation.py` | 写接口校验 30 例：越界人均 422、非法状态 422、超长文本 422、重复 id 409、不安全 id 422、坐标转换 400、七天排班往返、不安全 id 重复导入不重复、0 元有效、超大时间戳不炸看板、导入 `failed` 统计 |
| `...::test_non_progress_import_reports_failed_count` | 非进度导入遇到写入异常必须计入 `failed`（以前是 written=0/invalid=0） |
| `...::test_huge_timestamp_does_not_break_dashboard` | `createdAt=10^17` 导入后 `/api/dashboard` 仍 200 |
| `test_write_validation.py::test_full_week_schedule_can_be_saved` | **七天排班（239/421 字）必须能保存**，不能被 120 字上限误杀 |
| `...::test_full_week_schedule_export_import_roundtrip` | 完整排班 导出 → 清库 → 导入 字节一致 |
| `...::test_hours_structure_is_sanitized` | 越界时间/坏时段/未知星期被清掉而不是整条拒收 |
| `...::test_unsafe_id_is_stable_across_repeated_imports` | 不安全 id 重复导入只产生一条记录（uuid5 确定性） |
| `...::test_zero_price_is_a_real_price` | 0 元在 API / 看板都算有效价格 |
| `...::test_coords_convert_bad_bodies_are_4xx` | null/数组/坏 JSON 一律 4xx，不 500 |
| `test_packaging.py` | **打包 8 例**：frozen 时静态资源取 `_MEIPASS`、数据落 exe 同级、源码模式路径不变、spec 关键项（static/assets/console=False/collect_all）存在、发布 zip 不夹带 `data/` 与日志 |
| `test_repo_guard.py` | **提交前守卫 6 例**：所有已跟踪文件不得被误拦（拿 `git ls-files` 实测）、数据/密钥/备份/临时目录必须拦、路径分隔符归一 |
| `front-check.js` | 草稿三态的地图请求参数与渲染结果、重复点击不重复请求、导出 URL 含 `includeDrafts=1`、照片删除失败保留待删项且表单不关闭、价位区间预览边界、Object URL 复用与释放、经纬度 0 可保存、导入「0 写入但已是最新」文案、进入批量选择同步 URL、**版本号按数字元组比较**（`2.0.0 > 1.0.9`、`1.0.10 > 1.0.9`）、**安装三步状态机**（进行中/全完成/超时标失败）、**「刚更新完」只在新版本真正起来后才消费标记** |
| `test_startup_robustness.py` | **启动健壮性、性能与写库闸门 28 例**：`.fernet.key` 损坏仍能启动且坏文件留档、好钥匙不被换、`PORT=abc/99999` 不崩、16 位灰度 PNG 与 LA/CMYK/P 模式可上传且灰度不被压成纯白、非图片仍 400、重复导入计入 `unchanged`、旧备份不覆盖新记录、300 条导入 < 6s（连接复用）、`%`/`_` 按字面量搜索、`rating: 4.0`/`"5"` 不再整条被拒 |
| `test_update.py` | **应用内更新 42 例**：`1.0.10 > 1.0.9`（数字比较而非字符串）、`v` 前缀/`-beta` 后缀容错、资产按后缀匹配、无 sha256 时禁止自动安装、30 分钟内缓存不发请求、`force=1` 绕过缓存、缓存过期重查、**GitHub 不通时返回 `ok=false` 而不是 500**、刷新失败用旧缓存兜底并标 `stale`、非安装版拒绝下载/安装（409）、安装包路径穿越（`../`、`a\b.exe`、非 exe）一律拒绝、版本接口与进度接口形状、**取消下载**（下载中取消落到 `cancelled` 且删 `.part`、取消不再尝试其它网络路径、取消后能重新开始、已完成时取消不改状态、下载中拒绝安装、取消接口形状）、安装接口回传目标版本（前端遮罩与「已更新」判断都靠它） |

## 四、手工验证（不用测试脚本时）

前置：`start.bat` 启动应用；如需草稿数据，点「添加」→ 填店名 → 地图上点一个位置 → 勾选「存为草稿」→ 保存。

### 1. 备份包含草稿

1. 顶部「更多」→「导出备份（含草稿）」。
2. 得到 `foodmap-backup-YYYYMMDD-N.json`。
3. 用记事本打开，搜索草稿店名，应能搜到；`N` 应等于“当前筛选命中数（含草稿）”。

预期：草稿在备份里。注意关键词、标签等筛选仍会生效——想导出全部，先清空搜索框与筛选。

### 2. 切换草稿范围，地图立即同步

1. 「筛选」→ 草稿 → 点「仅草稿」。
2. **不要拖动地图**，直接看地图。

预期：列表只剩草稿；地图图钉也只剩草稿。再点「不含草稿」草稿图钉消失；点「含草稿」恢复。

若地图一直无图钉，先确认「设置」里「在地图上显示美食描点」是开启状态。

### 3. 保存设置不会清掉安全密钥

1. 记下「安全密钥」输入框里掩码的后四位。
2. 只改「Web 服务 Key」，点保存 → 页面自动刷新。
3. 再打开「设置」。

预期：安全密钥仍显示同一掩码，JS Key 未变；地图正常加载。
把安全密钥输入框清空再保存，结果相同（空值 = 保持原值）。

清除必须走明确操作：

- 点安全密钥下面的「清除已存的安全密钥」→ 确认 → 只有安全密钥消失，JS Key 与 Web Key 保留。
- 点「全部清除」→ 确认 → 三个 Key 全部消失。

### 4. 照片删除失败会提示并可重试

制造一次失败（用浏览器 DevTools，不需要改代码）：

1. 打开记录详情 →「编辑」→ 删掉一张已存在的照片（点缩略图右上角 ✕）→ 点保存。
2. 在保存前先打断删除请求：DevTools → Network → 找到 `DELETE /api/photos/...` →
   右键 → **Block request URL**（Chrome/Edge）。
3. 再点一次保存。

预期：提示「记录已保存，但有 1 张照片删除失败，可再点保存重试」，表单不关闭。
4. 回到 Network 面板取消 Block，再点保存。

预期：照片真正删除，表单关闭，重新打开详情不再出现该照片。

如果第 2 步来不及拦截，也可以直接关掉服务再点保存——但那样记录本身也保存失败，
提示会变成「保存失败」，无法验证删除分支。推荐用 Block request URL。
