# -*- coding: utf-8 -*-
"""发布说明：CHANGELOG 的抽取规则，以及「当前版本必须有说明」这条约束。

发版说明最容易出的错不是写错字，而是**忘了写**——所以这里把
「app/version.py 的 VERSION 必须在 CHANGELOG.md 里有同号章节」
变成一条会红的用例，而不是靠人记。
"""
import importlib
import textwrap

import pytest

from app.version import VERSION

rn = importlib.import_module("scripts.release_notes")

SAMPLE = """
# 更新日志

## [2.0.0] - 2026-10-22

段落一。

### 新增

- 甲

## [1.0.0] - 2026-10-21

- 乙
"""


def test_extract_returns_only_that_version():
    body = rn.extract_section(SAMPLE, "2.0.0")
    assert body.startswith("段落一。")
    assert "### 新增" in body and "甲" in body
    assert "乙" not in body                      # 不能吃到下一个版本


def test_extract_last_version_reaches_eof():
    body = rn.extract_section(SAMPLE, "1.0.0")
    assert body.strip() == "- 乙"


def test_extract_missing_version_returns_none():
    assert rn.extract_section(SAMPLE, "3.1.4") is None


def test_unreleased_heading_never_matches():
    """`## [Unreleased]` 不能被当成某个版本；也不该截断后面的正式章节。"""
    text = "## [Unreleased]\n\n- 待发\n\n" + SAMPLE.split("\n", 2)[2]
    body = rn.extract_section(text, "1.0.0")
    assert body and "乙" in body


@pytest.mark.parametrize("raw,expect", [
    ("2.0.0", "2.0.0"),
    ("v2.0.0", "2.0.0"),
    ("  V2.0.0 ", "2.0.0"),
])
def test_normalize_version(raw, expect):
    assert rn.normalize_version(raw) == expect


def test_current_version_has_changelog_entry():
    """当前 VERSION 必须在 CHANGELOG 里有章节——否则 CI 会拒绝发布。"""
    text = rn.CHANGELOG.read_text(encoding="utf-8")
    body = rn.extract_section(text, VERSION)
    assert body, f"CHANGELOG.md 缺少 [{VERSION}] 章节"
    assert len(body) > 80, "章节内容太短，像是占位符"


def test_script_writes_file_and_reports_missing(monkeypatch, capsys, tmp_path):
    out = tmp_path / "notes.md"
    monkeypatch.setattr("sys.argv", ["release_notes.py", "v" + VERSION, "--out", str(out)])
    assert rn.main() == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("## 本版本变更")
    assert "### 下载哪个文件" in text and f"v{VERSION}" in text

    monkeypatch.setattr("sys.argv", ["release_notes.py", "0.0.1", "--out", str(out)])
    assert rn.main() == 1                       # 缺章节必须失败，不能发出去


def test_extract_user_notes_pulls_only_that_section():
    """「给用户的说明」是应用内更新面板的内容源：只吃本小节，遇到下一个 ### 就停。"""
    md = textwrap.dedent("""
    ## [9.9.9] - 2026-01-01

    ### 给用户的说明

    - 修复了一些问题，提升了稳定性。

    ### 新增

    - 内部模块 X 改为 Y（这条不该出现在用户面板里）。

    ### 修复

    - z

    ## [9.9.8] - 2025-12-01
    """)
    notes = rn.extract_user_notes(md, "9.9.9")
    assert notes is not None
    assert "稳定性" in notes
    assert "内部模块" not in notes          # 技术细节不进用户面板
    assert "9.9.8" not in notes             # 不越界到下一版


def test_extract_user_notes_missing_section_returns_none():
    """没写用户说明时不报错，返回 None（调用方视为「这一版不需要说明」，不再兜底废话）。"""
    md = textwrap.dedent("""
    ## [9.9.9] - 2026-01-01

    ### 修复

    - 某个内部修复

    ## [9.9.8] - 2025-12-01
    """)
    assert rn.extract_user_notes(md, "9.9.9") is None
    assert rn.extract_user_notes("没有章节", "9.9.9") is None
