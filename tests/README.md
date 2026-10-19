# 回归测试

两条命令，覆盖四个容易复发的回归点。测试全部在临时目录里跑，
**不会创建、修改或删除 `data/foodmap.db`**。

## 一、跑测试

### 1. 后端（pytest，9 个用例）

```bat
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m pytest tests -q
```

预期输出：`9 passed`。

### 2. 前端（Node 断言，15 项）

```bat
node tests\front-check.js
```

预期输出：`通过 15 项` 且退出码为 0。缺 Node 时先装 Node 18+；Windows 上一般已有 `node`。

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
| `front-check.js` | 草稿三态的地图请求参数与渲染结果、重复点击不重复请求、导出 URL 含 `includeDrafts=1`、照片删除失败保留待删项且表单不关闭 |

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
