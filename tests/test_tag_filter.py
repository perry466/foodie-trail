# -*- coding: utf-8 -*-
"""标签筛选回归：特殊字符标签不能漏，且必须是精确匹配。

背景（2026-10-23 复审）：旧实现用原文 LIKE 匹配库里 JSON 串，标签含 " 或 \\
时存成 \\" 和 \\\\，永远对不上（漏报）；后加的 Python 复核只能剔误报、救不回
SQL 阶段已漏掉的行。现改用 SQLite json_each 精确等值匹配，本文件守这条线。

运行：venv/Scripts/python.exe -m pytest tests/test_tag_filter.py -q
"""

import urllib.parse


def _create(client, name, tags):
    r = client.post("/api/records", json={
        "name": name, "lng": 116.4, "lat": 39.9, "rating": 4, "tags": tags})
    assert r.status_code == 201, r.text
    return r.json()


def _list(client, tag, tags_any=False):
    params = {"tags": tag, "tagsAny": "true" if tags_any else "false"}
    r = client.get("/api/records", params=params)
    assert r.status_code == 200, r.text
    return [row["name"] for row in r.json()]


def _list_multi(client, tags, tags_any=False):
    # 重复查询参数（?tags=a&tags=b）：标签本身可以含逗号，不能再用逗号拼接
    from urllib.parse import quote
    qs = "&".join(f"tags={quote(t)}" for t in tags)
    r = client.get(f"/api/records?{qs}&tagsAny={'true' if tags_any else 'false'}")
    assert r.status_code == 200, r.text
    return [row["name"] for row in r.json()]


def test_tag_with_double_quote_is_found(client):
    """含双引号的标签：旧 LIKE 存取形态对不上必漏，json_each 必须命中。"""
    _create(client, "quote店", ['招牌"鸡"'])
    _create(client, "普通店", ["川菜"])
    assert _list(client, '招牌"鸡"') == ["quote店"]


def test_tag_with_backslash_is_found(client):
    _create(client, "backslash店", ["a\\b"])
    assert _list(client, "a\\b") == ["backslash店"]


def test_tag_with_like_wildcards_is_found(client):
    """% 和 _ 是 LIKE 通配符，精确匹配下只能按原文命中。"""
    _create(client, "percent店", ["100%回头"])
    _create(client, "underscore店", ["老字号_店"])
    assert _list(client, "100%回头") == ["percent店"]
    assert _list(client, "老字号_店") == ["underscore店"]


def test_tag_match_is_exact_not_substring(client):
    """精确匹配：搜「火」不能命中标签「火锅」的店（旧 LIKE 子串会误命中）。"""
    _create(client, "火锅店", ["火锅"])
    assert _list(client, "火") == []
    assert _list(client, "火锅") == ["火锅店"]


def test_tag_all_mode_requires_every_tag(client):
    _create(client, "全有店", ["川菜", "老店"])
    _create(client, "只有川菜", ["川菜"])
    assert _list_multi(client, ["川菜", "老店"]) == ["全有店"]


def test_tag_any_mode_finds_special_chars(client):
    _create(client, "quote店", ['招牌"鸡"'])
    _create(client, "川菜店", ["川菜"])
    names = _list_multi(client, ['招牌"鸡"', "川菜"], tags_any=True)
    assert sorted(names) == sorted(["quote店", "川菜店"])


def test_normal_tags_still_work(client):
    """普通标签路径不被改坏：创建、筛选、无命中三段都验。"""
    _create(client, "阿婆面馆", ["面馆", "小吃"])
    _create(client, "咖啡馆", ["咖啡"])
    assert _list(client, "面馆") == ["阿婆面馆"]
    assert _list(client, "不存在") == []


def test_tag_filter_url_encoding(client):
    """前端按 URL 编码传参，双引号经 %22 到达后端后行为一致。"""
    _create(client, "quote店", ['招牌"鸡"'])
    tag = urllib.parse.quote('招牌"鸡"')
    r = client.get(f"/api/records?tags={tag}")
    assert r.status_code == 200, r.text
    assert [row["name"] for row in r.json()] == ["quote店"]


def test_tag_with_comma_is_found(client):
    """含逗号的标签：tags 参数不再按逗号拆分，?tags=川菜,辣 作为一个整体匹配。"""
    _create(client, "逗号店", ["川菜,辣"])
    _create(client, "普通川菜", ["川菜"])
    r = client.get("/api/records", params={"tags": "川菜,辣"})
    assert r.status_code == 200, r.text
    assert [row["name"] for row in r.json()] == ["逗号店"]


def test_repeated_tags_params(client):
    """?tags=a&tags=b 与逗号拼接的时代语义一致：默认全部命中。"""
    _create(client, "全有店", ["川菜", "老店"])
    _create(client, "只有川菜", ["川菜"])
    r = client.get("/api/records?tags=%E5%B7%9D%E8%8F%9C&tags=%E8%80%81%E5%BA%97")
    assert r.status_code == 200, r.text
    assert [row["name"] for row in r.json()] == ["全有店"]


def test_dirty_tags_rows_do_not_break_filter(client):
    """tags 列有脏数据（空串/非法 JSON）时标签筛选不 500，正常行照常命中。

    裸 json_each 遇到 malformed JSON 会抛 OperationalError 把整个接口打挂——
    一条坏数据不能拖垮全部（2026-10-23 复审）。json_valid 守卫把脏行当无标签。
    """
    from app.db import get_conn
    _create(client, "正常店", ["川菜"])
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id, name, lng, lat, rating, draft, tags, "
            "created_at, updated_at) VALUES "
            "('dirty-empty', '空标签店', 116.4, 39.9, 4, 0, '', 1, 1)")
        conn.execute(
            "INSERT INTO records (id, name, lng, lat, rating, draft, tags, "
            "created_at, updated_at) VALUES "
            "('dirty-bad', '坏JSON店', 116.4, 39.9, 4, 0, '{不是json', 1, 1)")
        conn.execute(
            "INSERT INTO records (id, name, lng, lat, rating, draft, tags, "
            "created_at, updated_at) VALUES "
            "('dirty-obj', '对象店', 116.4, 39.9, 4, 0, '{\"a\":1}', 1, 1)")

    r = client.get("/api/records", params={"tags": "川菜"})
    assert r.status_code == 200, r.text
    assert [row["name"] for row in r.json()] == ["正常店"]

    # 不带标签筛选也照常返回（脏行不炸列表）
    r = client.get("/api/records")
    assert r.status_code == 200, r.text
