# -*- coding: utf-8 -*-
"""exe 版本资源：`app/version.py` → `build/version_info.txt` → 文件属性。

这组用例守三件事：
1. 四段版本号换算正确（Windows 只认 `2.0.1.0`，少一段就写不进去）；
2. 资源文件里的版本**跟着 `app/version.py` 走**，不是另抄一份；
3. `FoodieTrail.spec` 真的把它传给了 `EXE(...)`——否则文件生成了也没用，
   打出来的 exe 属性里仍然是空的（这次就是补这个洞）。
"""
import importlib

import pytest

from app.version import VERSION

mvi = importlib.import_module("scripts.make_version_info")


@pytest.mark.parametrize("raw,expect", [
    ("2.0.1", (2, 0, 1, 0)),
    ("v2.0.1", (2, 0, 1, 0)),
    ("1.0.10", (1, 0, 10, 0)),      # 两位补丁号不能被截断
    ("2.1", (2, 1, 0, 0)),
    ("3.0.0.7", (3, 0, 0, 7)),      # 已经是四段就原样
])
def test_parse_version_pads_to_four(raw, expect):
    assert mvi.parse_version(raw) == expect


@pytest.mark.parametrize("bad", ["", "abc", "2.0.x", "2.0.1.0.1", "2..1"])
def test_parse_version_rejects_junk(bad):
    with pytest.raises(ValueError):
        mvi.parse_version(bad)


def test_render_contains_four_part_and_string_table():
    text = mvi.render("2.0.1")
    assert "filevers=(2, 0, 1, 0)" in text
    assert "prodvers=(2, 0, 1, 0)" in text
    assert 'StringStruct("FileVersion", "2.0.1")' in text
    assert 'StringStruct("ProductVersion", "2.0.1")' in text
    assert 'StringStruct("OriginalFilename", "FoodieTrail.exe")' in text
    # 必须保持 ASCII：没有 BOM 的解析路径上中文会翻车
    assert text.isascii()


def test_version_follows_single_source(tmp_path):
    """不传参时版本来自 app/version.py，不能是硬编码。"""
    out = tmp_path / "version_info.txt"
    mvi.write_version_file(None, out)
    text = out.read_text(encoding="utf-8")
    assert f'StringStruct("FileVersion", "{VERSION}")' in text


def test_write_is_utf8_lf_and_idempotent(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    assert mvi.write_version_file("2.0.1", a) == str(a)
    mvi.write_version_file("2.0.1", b)
    assert a.read_bytes() == b.read_bytes()
    assert b"\r\n" not in a.read_bytes()


def test_pyinstaller_can_load_it(tmp_path):
    """真正交给 PyInstaller 的解析器读一遍，确认不是「看着像」而已。"""
    versioninfo = pytest.importorskip("PyInstaller.utils.win32.versioninfo")
    out = tmp_path / "version_info.txt"
    mvi.write_version_file("2.0.1", out)
    info = versioninfo.load_version_info_from_text_file(str(out))
    ver = info.ffi
    got = (ver.fileVersionMS >> 16, ver.fileVersionMS & 0xFFFF,
           ver.fileVersionLS >> 16, ver.fileVersionLS & 0xFFFF)
    assert got == (2, 0, 1, 0)
    table = info.kids[0].kids[0]
    strings = {k.name: k.val for k in table.kids}
    assert strings["FileVersion"] == "2.0.1"
    assert strings["ProductVersion"] == "2.0.1"
    assert strings["ProductName"] == mvi.PRODUCT


def test_spec_actually_passes_version_to_exe():
    """spec 里必须有 version=，否则资源文件白生成。"""
    spec = (mvi.ROOT / "FoodieTrail.spec").read_text(encoding="utf-8")
    assert "write_version_file()" in spec
    assert '"version": VERSION_INFO' in spec
    assert "**_exe_extra" in spec
