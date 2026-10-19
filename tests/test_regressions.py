"""回归测试：针对四个容易复发的回归点。

每个用例对应一条“用户可感知”的故障，断言的是行为而不是实现细节：
1. 备份不能静默漏掉草稿；
2. 草稿范围必须由服务端精确过滤（仅草稿 / 不含草稿 / 含草稿）；
3. 设置里只改 Web 服务 Key 或留空安全密钥时，已存的 securityJsCode 不能被清掉；
4. 清除安全密钥必须能单独执行，且不牵连 JS Key。

运行：venv/Scripts/python.exe -m pytest tests -q
"""


def _create(client, name, draft=False, **extra):
    payload = {"name": name, "lng": 116.4, "lat": 39.9, "rating": 4, "draft": draft}
    payload.update(extra)
    r = client.post("/api/records", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _names(resp, key=None):
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = body[key] if key else body
    return [row["name"] for row in rows]


# ---------- 1. 导出备份 ----------

def test_export_includes_drafts_by_default(client):
    _create(client, "正式店")
    _create(client, "草稿店", draft=True)

    names = _names(client.get("/api/export", params={"mode": "full"}), "records")
    assert "草稿店" in names
    assert "正式店" in names
    assert len(names) == 2


def test_export_still_honours_include_drafts_false(client):
    """默认包含草稿，但显式传 includeDrafts=0 时仍按参数排除（参数没有被写死）。"""
    _create(client, "正式店")
    _create(client, "草稿店", draft=True)

    names = _names(client.get("/api/export", params={"mode": "full", "includeDrafts": 0}), "records")
    assert names == ["正式店"]


def test_export_keeps_other_filters(client):
    """导出仍受关键词/标签等筛选影响，草稿只是“不再被额外排除”。"""
    _create(client, "火锅一号", tags=["火锅"])
    _create(client, "咖啡二号", tags=["咖啡"])
    _create(client, "火锅草稿", draft=True, tags=["火锅"])

    names = _names(client.get("/api/export", params={"mode": "full", "tags": "火锅"}), "records")
    assert sorted(names) == sorted(["火锅一号", "火锅草稿"])


# ---------- 2. 草稿范围 ----------

def test_records_default_excludes_drafts(client):
    _create(client, "正式店")
    _create(client, "草稿店", draft=True)

    assert _names(client.get("/api/records")) == ["正式店"]


def test_records_drafts_only(client):
    _create(client, "正式店")
    _create(client, "草稿店", draft=True)

    names = _names(client.get("/api/records", params={"includeDrafts": 1, "draftsOnly": 1}))
    assert names == ["草稿店"]


def test_drafts_only_has_priority_over_include_drafts(client):
    """draftsOnly=1 单独出现也必须只返回草稿（前端“仅草稿”依赖这一点）。"""
    _create(client, "正式店")
    _create(client, "草稿店", draft=True)

    assert _names(client.get("/api/records", params={"draftsOnly": 1})) == ["草稿店"]
    assert sorted(_names(client.get("/api/records", params={"includeDrafts": 1}))) == sorted(
        ["正式店", "草稿店"]
    )


# ---------- 3/4. 设置中的密钥语义 ----------

def _config(client):
    r = client.get("/api/config/amap")
    assert r.status_code == 200, r.text
    return r.json()


def test_security_kept_when_omitted_or_empty(client):
    r = client.put("/api/settings/amap", json={"key": "JS-KEY-1", "security": "SEC-1"})
    assert r.status_code == 200, r.text
    assert _config(client)["security"] == "SEC-1"

    # 只改 JS Key，不传 security
    client.put("/api/settings/amap", json={"key": "JS-KEY-2"})
    assert _config(client)["security"] == "SEC-1"

    # 传空串（设置面板未改动时的旧行为）也不能删
    client.put("/api/settings/amap", json={"key": "JS-KEY-2", "security": ""})
    assert _config(client)["security"] == "SEC-1"

    # 全空白同样视为“保持原值”
    client.put("/api/settings/amap", json={"key": "JS-KEY-2", "security": "   "})
    assert _config(client)["security"] == "SEC-1"

    # 真换新值时正常写入
    client.put("/api/settings/amap", json={"key": "JS-KEY-2", "security": "SEC-2"})
    assert _config(client)["security"] == "SEC-2"


def test_web_key_only_update_keeps_js_and_security(client):
    client.put("/api/settings/amap", json={"key": "JS-KEY-1", "security": "SEC-1"})
    client.put("/api/settings/amap", json={"key": "JS-KEY-1", "web_key": "WEB-1"})
    cfg = _config(client)
    assert cfg["key"] == "JS-KEY-1"
    assert cfg["security"] == "SEC-1"
    assert cfg["webConfigured"] is True

    # 再保存一次、不传 web_key：Web Key 保持不变
    client.put("/api/settings/amap", json={"key": "JS-KEY-1"})
    assert _config(client)["webConfigured"] is True


def test_clear_security_only(client):
    client.put("/api/settings/amap", json={"key": "JS-KEY-1", "security": "SEC-1", "web_key": "WEB-1"})

    r = client.delete("/api/settings/amap/security")
    assert r.status_code == 200, r.text
    cfg = _config(client)
    assert cfg["security"] is None
    assert cfg["key"] == "JS-KEY-1"
    assert cfg["webConfigured"] is True
