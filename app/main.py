"""FoodMap FastAPI 主程序：API + 静态托管"""
import base64
import io
import json
import math
import os
import re
import sqlite3
import time
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from . import crypto, update
from .coords import haversine, wgs84_to_gcj02
from .db import get_conn, init_db
from .pathconf import (
    AMAP_REST,
    DATA_DIR,
    PHOTO_MAX_BYTES,
    PHOTO_MAX_COUNT,
    PHOTO_MAX_EDGE,
    PHOTO_QUALITY,
    PHOTOS_DIR,
    STATIC_DIR,
)
from .repository import SQLiteRepository
from .validate import (
    MAX_HOURS_LEN,
    MAX_NAME_LEN,
    MAX_PRICE,
    MAX_TEXT_LEN,
    MIN_PRICE,
    build_record_payload,
    normalize_checkin,
    normalize_hours,
    normalize_price,
    normalize_tags,
    normalize_text,
    validate_record,
)
from .version import VERSION

# ---- 输入体量上限 ----
# 单张上传图片原始大小（手机直出一般 2-8MB，20MB 足够，且避免整块读进内存撑爆）
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# 备份文件上限：内含 base64 照片，按 1000 条 × 9 张 × 500KB 估算仍留有余量
MAX_IMPORT_BYTES = 256 * 1024 * 1024
# 单张备份照片解码后上限（备份里是压缩前原图，放宽到 4 倍）
MAX_IMPORT_PHOTO_BYTES = PHOTO_MAX_BYTES * 4
# 解码像素上限：挡住「几 KB 的 PNG 解压成几十亿像素」的解压炸弹
MAX_IMAGE_PIXELS = 64_000_000
# 备份记录条数上限，防止一份文件塞进上百万条把导入拖死
MAX_IMPORT_RECORDS = 200_000

app = FastAPI(title="FoodMap", version=VERSION)
repo = SQLiteRepository()

# 本服务只服务自身页面，任何外部站点都不得跨站读写数据。
# 原先 allow_origins=["*"] 意味着用户浏览任意网页时，该页面的脚本都能改记录、
# 删数据、导出照片、读取地图 Key。这里收紧到本机来源。
LOCAL_ORIGIN_RE = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=LOCAL_ORIGIN_RE.pattern,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _guard_origin(request, call_next):
    """拦截跨站请求：浏览器跨站时会带上 Origin，非本机来源一律拒绝。

    仅靠 CORS 响应头不够——请求本身仍可能到达服务端并被执行（删除类请求尤其致命），
    所以这里直接在入口处拒绝。无 Origin 的请求（命令行、curl、同源导航）放行。
    """
    origin = request.headers.get("origin")
    if origin and not LOCAL_ORIGIN_RE.match(origin):
        return JSONResponse({"detail": "拒绝跨站访问"}, status_code=403)
    return await call_next(request)

init_db()


# ---------- Pydantic ----------
# 记录 id 必须能安全放进 URL 路径：前端多处 `/api/records/${id}`，含 `/` `?` `#` 的 id
# 会让详情接口 404（`a/b` 被当成两段路径）。导入路径另有兜底（见 _sanitize_record_id）。
RECORD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RecordIn(BaseModel):
    id: Optional[str] = None
    name: str
    lng: float
    lat: float
    rating: int = Field(3, ge=1, le=5)
    tags: list = []
    businessHours: Optional[str] = None
    avgPrice: Optional[int] = None
    checkinStatus: Optional[str] = None
    note: Optional[str] = None
    draft: bool = False

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not RECORD_ID_RE.match(v):
            raise ValueError("记录 id 只能包含字母、数字、- 和 _（1–64 位）")
        return v

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        # 空白店名会让列表出现无法识别的一行，入口处就拒绝
        v = v.strip()
        if not v:
            raise ValueError("店名必填")
        if len(v) > MAX_NAME_LEN:
            raise ValueError(f"店名不能超过 {MAX_NAME_LEN} 字")
        return v

    @field_validator("lng")
    @classmethod
    def _lng_ok(cls, v: float) -> float:
        # NaN/inf 能通过 float 校验，但会让 SQLite 排序与前端地图出问题
        if not (-180 <= v <= 180):
            raise ValueError("经度须在 -180~180")
        return v

    @field_validator("lat")
    @classmethod
    def _lat_ok(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("纬度须在 -90~90")
        return v

    @field_validator("tags")
    @classmethod
    def _tags_ok(cls, v: list) -> list:
        # 只接受字符串标签：脏数据在写库前就收敛，不留给列表接口去炸
        if not isinstance(v, list):
            raise ValueError("tags 须为数组")
        for t in v:
            if not isinstance(t, str):
                raise ValueError("标签必须是字符串")
        return normalize_tags(v)

    # 下面三个字段与导入共用 validate.py 的规则与上限。
    # 区别只在「越界怎么处理」：导入是灾备，尽量救活（截断/置空）；
    # 直接写是用户的明确输入，直接 422 告知，避免"存进去又变 null"的静默丢失。
    @field_validator("avgPrice")
    @classmethod
    def _price_ok(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        price = normalize_price(v)
        if price is None:
            raise ValueError(f"人均须为 {MIN_PRICE}–{MAX_PRICE} 之间的整数（元）")
        return price

    @field_validator("checkinStatus")
    @classmethod
    def _checkin_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        status = normalize_checkin(v)
        if status is None:
            raise ValueError("状态只能是 want / visited / favorite")
        return status

    @field_validator("note")
    @classmethod
    def _note_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("备注必须是文本")
        if len(v.strip()) > MAX_TEXT_LEN:
            raise ValueError(f"备注不能超过 {MAX_TEXT_LEN} 字")
        return normalize_text(v, MAX_TEXT_LEN)

    @field_validator("businessHours")
    @classmethod
    def _hours_ok(cls, v: Optional[str]) -> Optional[str]:
        # 七天排班 JSON 有 239（每天 1 段）～421（每天 2 段）字，按字数限制会误杀正常数据，
        # 所以这里按结构校验：JSON 只保留 mon..sun + HH:MM 时段，旧纯文本才用 120 字上限。
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("营业时间必须是文本")
        txt = v.strip()
        if not txt:
            return None
        hours = normalize_hours(txt)
        if hours is None:
            raise ValueError("营业时间格式不正确：应为 {mon:[{s,e}],…} 的七天排班 JSON")
        if not hours.startswith("{") and len(hours) > MAX_HOURS_LEN:
            raise ValueError(f"营业时间纯文本不能超过 {MAX_HOURS_LEN} 字，请用排班编辑器")
        return hours


class AmapKeyIn(BaseModel):
    key: str                        # 前端 JS API Key（用于浏览器加载地图）
    security: Optional[str] = None  # 安全密钥 securityJsCode（JS API 2.0 需要）
    web_key: Optional[str] = None   # 后端 Web 服务 Key（POI/地理编码/路线代理，不下发前端）


class BatchDeleteIn(BaseModel):
    ids: list[str] = []             # 待批量删除的记录 id 列表


# ---------- 工具 ----------
def _now() -> int:
    return int(time.time() * 1000)


def _compress_image(data: bytes) -> bytes:
    """把任意图片重编码为受控 JPEG。非图片/超大像素会抛 ValueError，由调用方转 4xx。"""
    try:
        img = Image.open(io.BytesIO(data))
    except Exception as e:                    # 非图片、损坏文件：统一交给调用方转 400
        raise ValueError(f"无法识别的图片：{e}")
    w, h = img.size
    # 解压炸弹：尺寸信息来自文件头，此时还没真正解码整张图，先拦掉
    if w <= 0 or h <= 0 or w * h > MAX_IMAGE_PIXELS:
        raise ValueError("图片尺寸过大")
    # EXIF 方向校正（手机照片竖拍横线问题）
    try:
        from PIL import ExifTags
        exif = getattr(img, "_getexif", lambda: None)()
        if exif:
            orientation = exif.get(ExifTags.TAGS.get("Orientation"))
            trans = {3: Image.ROTATE_180, 6: Image.ROTATE_270,
                     8: Image.ROTATE_90, 2: Image.FLIP_LEFT_RIGHT,
                     4: Image.FLIP_TOP_BOTTOM, 5: Image.TRANSPOSE, 7: Image.TRANSVERSE}
            if orientation in trans:
                img = img.transpose(trans[orientation])
    except Exception:
        pass
    # 只转 RGBA/P 不够：16 位灰度（I;16 / I / F）、LA、CMYK 等模式直接 img.save(JPEG)
    # 会抛 OSError，用户拿一张合法 PNG 也被报「无法识别的图片」。统一先落成 RGB。
    if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        # 16 位/32 位灰度按 8 位缩比，直接 convert("RGB") 会把整张图压成纯白
        img = img.point(lambda v: v * (1 / 256.0)).convert("L")
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > PHOTO_MAX_EDGE:
        scale = PHOTO_MAX_EDGE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    quality = PHOTO_QUALITY
    try:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        while buf.tell() > PHOTO_MAX_BYTES and quality > 30:
            quality -= 8
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
    except OSError as e:                       # 极端色彩模式等：仍然给 4xx，不冒 500
        raise ValueError(f"图片无法转换为 JPEG：{e}")
    return buf.getvalue()


def _amap_key() -> Optional[str]:
    enc = repo.get_setting("amap_key")
    return crypto.decrypt(enc) if enc else None


def _amap_security() -> Optional[str]:
    enc = repo.get_setting("amap_security")
    return crypto.decrypt(enc) if enc else None


def _amap_web_key() -> Optional[str]:
    """后端 Web 服务 Key（数据代理用），绝不返回前端。"""
    enc = repo.get_setting("amap_web_key")
    return crypto.decrypt(enc) if enc else None


# ---------- 记录 CRUD ----------
@app.get("/api/records")
def list_records(
    keyword: str = "", ratingMin: int = None, ratingMax: int = None,
    avgPriceMin: int = None, avgPriceMax: int = None,
    checkinStatus: str = "", tags: list[str] = Query(default=[]),
    tagsAny: bool = False, includeDrafts: bool = False,
    draftsOnly: bool = False,
    swLng: float = None, swLat: float = None, neLng: float = None, neLat: float = None,
    sort: str = "updatedAt:desc", limit: int = 0, offset: int = 0,
):
    filters = {
        "keyword": keyword, "ratingMin": ratingMin, "ratingMax": ratingMax,
        "avgPriceMin": avgPriceMin, "avgPriceMax": avgPriceMax,
        "checkinStatus": checkinStatus, "includeDrafts": includeDrafts,
        "draftsOnly": draftsOnly, "tagsAny": tagsAny,
    }
    # tags 收重复查询参数（?tags=a&tags=b），**不按逗号拆**：
    # 标签本身可以含逗号（如「川菜,辣」），拆了就永远筛不到（2026-10-23 复审）。
    if tags:
        filters["tags"] = [t for t in tags if t]
    if None not in (swLng, swLat, neLng, neLat):
        filters["bounds"] = {"swLng": swLng, "swLat": swLat, "neLng": neLng, "neLat": neLat}
    return repo.list(filters, sort, limit, offset)


@app.get("/api/records/{rid}")
def get_record(rid: str):
    rec = repo.get(rid)
    if not rec:
        raise HTTPException(404, "记录不存在")
    return rec


@app.post("/api/records", status_code=201)
def create_record(body: RecordIn):
    rid = body.id or str(uuid.uuid4())
    payload = body.model_dump()
    payload["id"] = rid
    payload["createdAt"] = payload["updatedAt"] = _now()
    if body.id and repo.get(rid):
        # 显式指定了已存在的 id：这是冲突，不是服务器错误
        raise HTTPException(409, "记录 id 已存在，请换一个或不指定 id")
    try:
        return repo.create(payload)
    except sqlite3.IntegrityError:
        # 并发下两个请求同时通过上面的检查，兜底仍返回 409 而不是 500
        raise HTTPException(409, "记录 id 已存在")


@app.put("/api/records/{rid}")
def update_record(rid: str, body: RecordIn):
    """**全量替换**语义：没传的可选字段会被重置（tags→[]、note→null、
    avgPrice→null、checkinStatus→null、draft→false），不是局部更新。

    前端 `_recordBody()` 因此每次都带齐所有字段。用脚本/curl 改状态时也必须
    先 GET 再整体 PUT，否则会把备注、标签、草稿标记一起清掉。照片不在此接口内。
    """
    existing = repo.get(rid)
    if not existing:
        raise HTTPException(404, "记录不存在")
    payload = body.model_dump()
    payload["id"] = rid
    payload["createdAt"] = existing["createdAt"]
    payload["updatedAt"] = _now()
    rec = repo.update(rid, payload)
    return rec


# 注意：批量路由必须注册在 /api/records/{rid} 之前，否则 "batch" 会被当成 rid 捕获
@app.delete("/api/records/batch")
def delete_records_batch(body: BatchDeleteIn):
    """批量删除：先在一个事务里删记录行（photos 随外键级联），成功后再清文件。

    顺序不能反过来。先删文件的话，数据库一失败就留下「记录还在、照片已丢」的
    坏状态；反过来最多留下几个孤儿文件，对用户不可见也可再清理。
    """
    ids, seen = [], set()
    for rid in (body.ids or []):
        if isinstance(rid, str) and rid and rid not in seen:
            seen.add(rid)
            ids.append(rid)
    if not ids:
        return {"ok": True, "deleted": 0}
    paths = repo.photo_paths(ids)        # 只读路径，不动文件
    deleted = repo.delete_many(ids)      # 事务删行；抛错则文件一张没少
    for path in paths:
        _remove_photo_file(path)
    return {"ok": True, "deleted": deleted}


@app.delete("/api/records/{rid}")
def delete_record(rid: str):
    rec = repo.get(rid)
    paths = [p["path"] for p in rec["photos"]] if rec else []
    repo.delete(rid)                     # 先删行，删失败就不碰文件
    for path in paths:
        _remove_photo_file(path)
    return {"ok": True}


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """分块读取上传内容，超过上限立即 413，防止无上限的请求把内存读爆。

    注意：这只防「无限读」，不防「整文件驻留」——上限内的文件仍会完整
    存进内存，且 json.loads 解析时原始字节与 Python 对象会同时存在，
    峰值可达文件的数倍。256MB 上限是按「mode=full 备份内嵌 base64 照片」
    的合法体积定的（单机单人使用，峰值内存高一点可接受）；
    若将来要支持更大的库，应改流式解析而不是继续抬高这个数。
    """
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"文件过大（上限 {limit // (1024 * 1024)}MB）")
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_photo_path(rel_path) -> Optional[str]:
    """把库里记的 photos/xxx.jpg 解析成绝对路径，并确认它没有跑出 PHOTOS_DIR。

    返回 None 表示路径非法（绝对路径、../ 逃逸、空值），调用方应跳过。
    这层防护针对的是被篡改过的数据库/旧备份，正常写入永远只会是 photos/<uuid>.jpg。

    同时把反斜杠统一成 `/`：2026-10 之前的 Windows 版本用 os.path.join 存成了
    `photos\\xxx.jpg`，原样搬到 Linux/macOS 就找不到文件。读的时候容错，写的时候不用反斜杠。
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    rel = rel_path.strip().replace("\\", "/")
    if os.path.isabs(rel):
        candidate = rel
    else:
        candidate = os.path.join(DATA_DIR, rel)
    full = os.path.realpath(candidate)
    root = os.path.realpath(PHOTOS_DIR)
    try:
        if os.path.commonpath([full, root]) != root:
            return None
    except ValueError:          # 不同盘符
        return None
    return full


def _remove_photo_file(rel_path: str):
    full = _safe_photo_path(rel_path)
    if not full:
        return
    try:
        os.remove(full)
    except OSError:
        pass


# ---------- 照片 ----------
@app.post("/api/records/{rid}/photos")
async def upload_photo(rid: str, file: UploadFile = File(...)):
    rec = repo.get(rid)
    if not rec:
        raise HTTPException(404, "记录不存在")
    if len(rec["photos"]) >= PHOTO_MAX_COUNT:
        raise HTTPException(400, f"最多 {PHOTO_MAX_COUNT} 张照片")
    data = await _read_limited(file, MAX_UPLOAD_BYTES)
    if not data:
        raise HTTPException(400, "空文件")
    try:
        compressed = _compress_image(data)
    except Exception:
        # 非图片、损坏文件、像素超限都走这里：给 4xx，而不是 500 堆栈
        raise HTTPException(400, "无法识别的图片（支持 JPG/PNG/WebP）")
    pid = str(uuid.uuid4())
    fname = f"{pid}.jpg"
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    full = os.path.join(PHOTOS_DIR, fname)
    with open(full, "wb") as f:
        f.write(compressed)
    photo = {
        "id": pid, "recordId": rid,
        # 统一存正斜杠：data/ 跨系统搬动后 Linux/macOS 也能解析（反斜杠只在 Windows 有效）
        "path": f"photos/{fname}", "thumb": None, "createdAt": _now(),
    }
    repo.add_photo(photo)
    return photo


@app.get("/api/photos/{pid}")
def get_photo(pid: str):
    p = repo.get_photo(pid)
    if not p:
        raise HTTPException(404, "照片不存在")
    full = _safe_photo_path(p["path"])
    if not full or not os.path.exists(full):
        raise HTTPException(404, "照片文件丢失")
    return FileResponse(full)


@app.delete("/api/photos/{pid}")
def delete_photo(pid: str):
    p = repo.get_photo(pid)
    if p:
        repo.delete_photo(pid)          # 先删行：行还在就绝不先删文件
        _remove_photo_file(p["path"])
    return {"ok": True}


# ---------- 设置 / Key ----------
@app.get("/api/config/amap")
def config_amap():
    """返回前端初始化地图所需 Key（仅 JS Key + 安全密钥；Web 服务 Key 不下发前端）。"""
    key = _amap_key()
    sec = _amap_security()
    web = _amap_web_key()
    return {
        "key": key,
        "security": sec,
        "configured": bool(key),
        "webConfigured": bool(web),
    }


@app.put("/api/settings/amap")
def set_amap(body: AmapKeyIn):
    repo.set_setting("amap_key", crypto.encrypt(body.key))
    # 安全密钥：None 或空串表示"保持原值"。
    # 前端只改 Web 服务 Key 时不会再传 security，这里若按空值删除，
    # 会导致高德地图随后报 INVALID_USER_SCODE；清除必须走 DELETE /api/settings/amap/security。
    if body.security and body.security.strip():
        repo.set_setting("amap_security", crypto.encrypt(body.security.strip()))
    # Web 服务 Key：非空则存；不传（None）或空串则保持不变
    if body.web_key:
        repo.set_setting("amap_web_key", crypto.encrypt(body.web_key))
    return {"ok": True}


@app.delete("/api/settings/amap/security")
def clear_amap_security():
    """只清除安全密钥，保留 JS Key 与 Web 服务 Key。"""
    repo.delete_setting("amap_security")
    return {"ok": True}


@app.delete("/api/settings/amap")
def clear_amap():
    repo.delete_setting("amap_key")
    repo.delete_setting("amap_security")
    repo.delete_setting("amap_web_key")
    return {"ok": True}


@app.post("/api/settings/test-connection")
def test_connection():
    """测试后端 Web 服务 Key（代理搜索/地理编码/路线依赖它）。"""
    web = _amap_web_key()
    if not web:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "msg": "未配置 Web 服务 Key（代理搜索/地理编码/路线需要它）"},
        )
    try:
        r = httpx.get(
            f"{AMAP_REST}/v3/assistant/inputtips",
            params={"key": web, "keywords": "测试", "city": ""}, timeout=8,
        )
        data = r.json()
    except Exception as e:
        return {"ok": False, "msg": f"网络错误: {e}"}
    if data.get("status") == "1":
        return {"ok": True, "msg": "Web 服务 Key 连接成功"}
    info = data.get("info", "未知错误")
    return {"ok": False, "msg": f"高德返回: {info}"}


# ---------- 版本 / 更新 ----------
# 说明：检查更新永远不抛 500。GitHub 在国内时通时不通，网络问题必须由前端
# 静默处理（见 app/update.py 顶部三条约束），不能变成"打开就报错"。
@app.get("/api/app/version")
def app_version():
    """本地版本与运行形态，纯读内存，不发任何网络请求。"""
    return {"version": VERSION, "mode": update.detect_mode()}


@app.get("/api/update/check")
def update_check(force: int = 0):
    """查最新 Release。force=1 跳过 6 小时缓存。"""
    return update.check(force=bool(force))


@app.post("/api/update/download")
def update_download():
    """开始后台下载安装包；进度用 GET 同一路径查。"""
    try:
        return update.start_download()
    except update.UpdateError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "msg": e.message})


@app.get("/api/update/download")
def update_download_progress():
    return update.progress()


@app.post("/api/update/cancel")
def update_cancel():
    """取消正在进行的下载。幂等：没在下载也返回 200 + 当前进度。

    为什么需要一个独立路由而不是 DELETE：前端用的是同一个 sendForm 助手，
    而且这个操作不是「删除服务端资源」，只是停一个后台任务。
    """
    return update.cancel_download()


@app.post("/api/update/install")
def update_install():
    """启动安装器并退出本进程。只对安装版开放。"""
    try:
        return update.install()
    except update.UpdateError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "msg": e.message})


@app.post("/api/update/reveal")
def update_reveal():
    """打开下载目录，给自动安装失败时留一个手动双击安装包的出口。"""
    try:
        return update.reveal_download()
    except update.UpdateError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "msg": e.message})



# ---------- 高德代理（数据请求走后端，前端不持 Key） ----------
# 高德返回 status=0 时，把 info 翻译成可操作的中文提示，避免前端只看到英文错误码
_AMAP_INFO_HINTS = {
    "INVALID_USER_KEY": "高德 Key 无效或已失效，请在「设置」里重新填写",
    "USER_KEY_REQUIRED": "缺少高德 Key，请先在「设置」里填写",
    "USERKEY_PLAT_NOMATCH": "Key 类型不对：POI 搜索/地址解析必须用「Web 服务」类型的 Key，不能用「Web 端(JS API)」Key",
    "INVALID_USER_SCODE": "Key 与安全密钥不匹配，请重新核对 JS API Key 和 securityJsCode",
    "DAILY_QUERY_OVER_LIMIT": "今日调用配额已用完（个人 Key 有每日限额），请明天再试或更换 Key",
    "INSUFFICIENT_PRIVILEGES": "该 Key 没有 Web 服务接口权限，请在高德控制台开通",
    "SERVICE_NOT_AVAILABLE": "高德服务暂不可用，请稍后再试",
    "INVALID_PARAMS": "搜索参数不合法，请换个关键词试试",
    "ENGINE_RESPONSE_DATA_ERROR": "高德返回数据异常，请稍后再试",
}


def _amap_call(url: str, params: dict) -> dict:
    """调用高德 Web 服务并统一处理错误：返回 status=1 的数据，否则抛出带中文说明的 400。"""
    try:
        r = httpx.get(url, params=params, timeout=8)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"连接高德服务失败：{e.__class__.__name__}")
    try:
        data = r.json()
    except Exception:
        raise HTTPException(502, "高德返回内容无法解析")
    if str(data.get("status")) == "1":
        return data
    info = data.get("info") or "未知错误"
    code = data.get("infocode") or ""
    hint = _AMAP_INFO_HINTS.get(info) or f"高德返回错误：{info}"
    raise HTTPException(400, f"{hint}（{code}）" if code else hint)


def _norm_lnglat(loc):
    """把高德返回的 location 归一成 (lng, lat) 浮点数。

    高德不同接口/不同版本返回的 location 有三种形态，前端如果直接 .split(',')
    就会在某些接口上抛 "split is not a function"：
      1. 字符串 "116.397,39.909"
      2. 对象 {"lng":116.397,"lat":39.909}
      3. 数组 [116.397, 39.909]
    这里统一吃下三种，取不到就返回 (None, None)。
    """
    lng = lat = None
    if isinstance(loc, str):
        parts = [p for p in loc.split(",") if p.strip() != ""]
        if len(parts) >= 2:
            try:
                lng, lat = float(parts[0]), float(parts[1])
            except ValueError:
                lng = lat = None
    elif isinstance(loc, (list, tuple)) and len(loc) >= 2:
        try:
            lng, lat = float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            lng = lat = None
    elif isinstance(loc, dict):
        try:
            lng, lat = float(loc.get("lng")), float(loc.get("lat"))
        except (TypeError, ValueError):
            lng = lat = None
    if lng is None or lat is None:
        return None, None
    # 明显越界的脏数据直接丢弃，避免污染前端
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None, None
    return lng, lat


@app.get("/api/amap/poi")
def amap_poi(keywords: str, city: str = "", location: str = ""):
    """输入提示（联想搜索）。返回已归一化的 {name, district, address, lng, lat}。"""
    key = _amap_web_key()
    if not key:
        raise HTTPException(
            400,
            "未配置高德 Web 服务 Key：POI 搜索需要「Web 服务」类型的 Key，"
            "请在「设置 → ③ 后端 Web 服务 Key」里填写",
        )
    params = {"key": key, "keywords": keywords, "city": city}
    if location:
        params["location"] = location      # 传入当前坐标时，高德会按距离排序
    data = _amap_call(f"{AMAP_REST}/v3/assistant/inputtips", params)

    tips = []
    for t in data.get("tips") or []:
        if not isinstance(t, dict):
            continue
        lng, lat = _norm_lnglat(t.get("location"))
        if lng is None:
            continue                        # 无坐标的提示项（如纯行政区名）对选点无用
        name = (t.get("name") or "").strip()
        if not name:
            continue
        tips.append({
            "name": name,
            "district": (t.get("district") or "").strip("[] "),
            "address": (t.get("address") or "").strip("[] "),
            "lng": lng,
            "lat": lat,
            "type": t.get("typecode") or "",
        })
    return {"ok": True, "keywords": keywords, "tips": tips}


@app.get("/api/amap/geocode")
def amap_geocode(address: str):
    key = _amap_web_key()
    if not key:
        raise HTTPException(
            400,
            "未配置高德 Web 服务 Key：地址解析需要「Web 服务」类型的 Key，"
            "请在「设置 → ③ 后端 Web 服务 Key」里填写",
        )
    data = _amap_call(f"{AMAP_REST}/v3/geocode/geo", {"key": key, "address": address})

    geos = []
    for g in data.get("geocodes") or []:
        if not isinstance(g, dict):
            continue
        lng, lat = _norm_lnglat(g.get("location"))
        if lng is None:
            continue
        geos.append({
            "formatted_address": g.get("formatted_address") or address,
            "lng": lng,
            "lat": lat,
            "level": g.get("level") or "",
            "city": g.get("city") or "",
            "district": g.get("district") or "",
        })
    return {"ok": True, "geocodes": geos}


@app.get("/api/amap/route")
def amap_route(origin: str, destination: str):
    """origin/destination: 'lng,lat'。返回驾车距离(米)。"""
    key = _amap_web_key()
    if not key:
        raise HTTPException(400, "未配置高德 Web 服务 Key：路线需要「Web 服务」类型的 Key")
    return _amap_call(
        f"{AMAP_REST}/v3/direction/driving",
        {"key": key, "origin": origin, "destination": destination, "extensions": "base"},
    )


# ---------- 坐标转换 ----------
@app.post("/api/coords/convert")
def coord_convert(body: dict):
    lng = body.get("lng")
    lat = body.get("lat")
    if lng is None or lat is None:
        raise HTTPException(400, "需要 lng,lat")
    try:
        lng = float(lng)
        lat = float(lat)
    except (TypeError, ValueError):
        raise HTTPException(400, "lng/lat 必须是数字")
    if not (math.isfinite(lng) and math.isfinite(lat)):
        raise HTTPException(400, "lng/lat 必须是有限数字")
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        raise HTTPException(400, "坐标越界")
    glng, glat = wgs84_to_gcj02(lng, lat)
    return {"lng": glng, "lat": glat}


# ---------- 推荐 ----------
@app.get("/api/recommend/nearby")
def recommend_nearby(lat: float, lng: float, limit: int = 20):
    records = repo.list({"includeDrafts": False}, [("rating", "desc")])
    for r in records:
        r["distanceKm"] = round(haversine(lat, lng, r["lat"], r["lng"]), 2)
    records.sort(key=lambda x: x["distanceKm"])
    return records[:limit]


@app.get("/api/recommend/similar/{rid}")
def recommend_similar(rid: str, limit: int = 5):
    base = repo.get(rid)
    if not base:
        raise HTTPException(404, "记录不存在")
    base_tags = set(base["tags"])
    if len(base_tags) == 0:
        return []
    others = repo.list({"includeDrafts": False}, [("updatedAt", "desc")])
    scored = []
    for r in others:
        if r["id"] == rid:
            continue
        t = set(r["tags"])
        union = base_tags | t
        jac = len(base_tags & t) / len(union) if union else 0
        if jac > 0:
            scored.append((jac, r))
    scored.sort(key=lambda x: (-x[0], -x[1]["rating"]))
    return [r for _, r in scored[:limit]]


# ---------- 看板 ----------
@app.get("/api/dashboard")
def dashboard():
    return repo.dashboard()


# ---------- 导出 / 导入 ----------
def _export_record(full: dict, mode: str) -> dict:
    """把一条记录转成备份里的结构；照片按需内联 base64。

    photosIncluded 是给导入方的显式契约：
    - true  →「这条记录的照片就是下面这些，空数组也表示确实没有照片」；
    - false →「本次备份没带照片（mode=meta），导入时不要动已有照片」。
    有这面旗子，导入才敢在「照片数组为空」时清空旧照片而不误删。
    """
    rec = {
        "id": full["id"], "name": full["name"], "lng": full["lng"], "lat": full["lat"],
        "rating": full["rating"], "tags": full["tags"], "businessHours": full["businessHours"],
        "avgPrice": full["avgPrice"], "checkinStatus": full["checkinStatus"],
        "note": full["note"], "draft": full["draft"],
        "createdAt": full["createdAt"], "updatedAt": full["updatedAt"],
        "photosIncluded": mode == "full",
        "photos": [],
    }
    if mode == "full":
        for p in full.get("photos", []):
            # 走 _safe_photo_path：库里若有被篡改的 path（../ 或绝对路径），
            # 导出不能因此读到 photos/ 之外的文件
            full_path = _safe_photo_path(p["path"])
            if not full_path or not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
            except OSError:
                # isfile 与 open 之间有时间窗口：另一个标签页刚删了这张照片、
                # 杀毒软件锁住文件、外部清理工具动了 photos/ 都会走到这里。
                # 导出是流式的，此时响应头已经发出，异常会让用户拿到**截断的 JSON**
                # —— 宁可这一张照片缺失（记录本身还在），也不能让整份备份失效。
                continue
            rec["photos"].append({
                "id": p["id"], "data": b64, "name": os.path.basename(full_path),
            })
    return rec


def _iter_export(records: list, photos_map: dict, mode: str):
    """逐条产出 JSON 文本：内存只与「单条记录 + 它的照片」有关，不随总数据量增长。"""
    yield '{"app":"foodmap","version":2,"photosIncluded":'
    yield "true" if mode == "full" else "false"
    yield ',"exportedAt":'
    yield json.dumps(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    yield ',"records":['
    first = True
    for row in records:
        full = dict(row)
        full["photos"] = photos_map.get(row["id"], [])
        if not first:
            yield ","
        yield json.dumps(_export_record(full, mode), ensure_ascii=False)
        first = False
    yield "]}"


@app.get("/api/export")
def export_records(
    mode: str = "full",
    keyword: str = "", ratingMin: int = None, ratingMax: int = None,
    avgPriceMin: int = None, avgPriceMax: int = None,
    checkinStatus: str = "", tags: list[str] = Query(default=[]),
    tagsAny: bool = False,
    includeDrafts: bool = True,
    sort: str = "updatedAt:desc",
):
    """导出备份。includeDrafts 默认为 True：草稿也是用户数据，备份不应静默遗漏。

    `tagsAny` 必须和 `/api/records` 一样收下来：漏了它，导出会退化成「同时含全部标签」，
    用户在「任一标签」下点导出会拿到一个更小的子集，而且没有任何提示——
    对以本地备份为卖点的应用，这等于备份不可信。
    """
    filters = {
        "keyword": keyword, "ratingMin": ratingMin, "ratingMax": ratingMax,
        "avgPriceMin": avgPriceMin, "avgPriceMax": avgPriceMax,
        "checkinStatus": checkinStatus, "includeDrafts": includeDrafts,
        "tagsAny": tagsAny,
    }
    # 与 /api/records 同口径：tags 收重复参数，不按逗号拆
    if tags:
        filters["tags"] = [t for t in tags if t]
    # 只取元数据列表（不读照片），条数用于文件名；正文交给流式生成器
    # sort 由数据层 normalize_sort 白名单化，用户原文不会进 SQL
    records = repo.list(filters, sort)
    photos_map = repo.photos_map()      # 一次查完，避免逐条 get 再开连接
    fname = f"foodmap-backup-{time.strftime('%Y%m%d')}-{len(records)}.json"
    return StreamingResponse(
        _iter_export(records, photos_map, mode),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Total-Records": str(len(records)),
            "Cache-Control": "no-store",
        },
    )


def _decode_backup_photo(ph) -> tuple:
    """把备份里的一条照片还原成「受控 JPEG」字节。

    防线（按代价从低到高，先便宜的检查）：
    1. 类型/空值 → 丢弃；
    2. base64 字符串长度上限（不解码就能挡住超大块）；
    3. 严格 base64 校验；
    4. 解码后字节上限；
    5. 真实图片 + 像素上限（挡解压炸弹）；
    6. 重编码为 JPEG（顺手抹掉 EXIF/GPS，也避免把 HTML/脚本伪装成 .jpg 存下来）。
    返回 (data, None) 或 (None, 原因)。
    """
    if not isinstance(ph, dict):
        return None, "bad_entry"
    data = ph.get("data")
    if not isinstance(data, str) or not data.strip():
        return None, "empty"
    # 兼容手工/第三方工具产生的换行折行 base64；去掉空白后再按长度与内容校验
    data = "".join(data.split())
    # base64 膨胀约 4/3，留一点余量
    if len(data) > (MAX_IMPORT_PHOTO_BYTES * 4) // 3 + 1024:
        return None, "too_large"
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        return None, "bad_base64"
    if not raw:
        return None, "empty"
    if len(raw) > MAX_IMPORT_PHOTO_BYTES:
        return None, "too_large"
    try:
        encoded = _compress_image(raw)
    except Exception:
        return None, "bad_image"
    return encoded, None


_IMPORT_TMP_SUFFIX = ".part"


def _cleanup_stale_import_temps(max_age: float = 24 * 3600) -> None:
    """清掉上次导入中断留下的 .part 临时文件（超过 1 天才动，避免误删并发导入）。"""
    try:
        names = os.listdir(PHOTOS_DIR)
    except OSError:
        return
    now = time.time()
    for name in names:
        if not name.endswith(_IMPORT_TMP_SUFFIX):
            continue
        full = os.path.join(PHOTOS_DIR, name)
        try:
            if now - os.path.getmtime(full) > max_age:
                os.remove(full)
        except OSError:
            pass


def _stage_import_photos(photos: list) -> tuple:
    """校验并把备份照片全部暂存为 .part 临时文件，此时不碰正式文件名、不碰数据库。

    返回 (staged, skipped)。staged 每项含 {tmp, final, photo(数据库行)}。
    skipped > 0 表示这份照片集不完整，调用方必须整体放弃替换。
    """
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    staged, skipped = [], 0
    for ph in photos:
        encoded, _reason = _decode_backup_photo(ph)
        if encoded is None:
            skipped += 1
            continue
        pid = str(uuid.uuid4())
        final_name = f"{pid}.jpg"
        tmp = os.path.join(PHOTOS_DIR, f".{pid}{_IMPORT_TMP_SUFFIX}")
        try:
            with open(tmp, "wb") as f:
                f.write(encoded)
        except OSError as e:
            print(f"[import] 暂存照片失败 {pid}: {e}")
            skipped += 1
            continue
        staged.append({
            "tmp": tmp,
            "final": os.path.join(PHOTOS_DIR, final_name),
            "photo": {
                "id": pid, "path": f"photos/{final_name}",
                "thumb": None, "createdAt": _now(),
            },
        })
    return staged, skipped


def _discard_staged(staged: list) -> None:
    for item in staged:
        for key in ("tmp", "final"):
            try:
                os.remove(item[key])
            except OSError:
                pass


def _photos_included_flag(backup: dict, record: dict, photos: list) -> bool:
    """判断这条记录的照片数组是否可信地代表「它的全部照片」。

    1. 记录自带 photosIncluded 布尔 → 用它（新格式，最明确）；
    2. 整个备份带 photosIncluded → 用它（mode=meta 导出的备份整体不带照片）；
    3. 都没有（更早的备份）→ 数组非空才算带照片；空数组按「没带」处理，
       不清空已有照片。宁可多留几张图，也不能因为一份旧备份误删用户照片。
    """
    for source in (record, backup):
        flag = source.get("photosIncluded") if isinstance(source, dict) else None
        if isinstance(flag, bool):
            return flag
    return bool(photos)


def _write_import_record(payload: dict, photos: list, photos_included: bool = False,
                         conn=None) -> dict:
    """写入一条记录（含照片）。

    返回 {"written": bool, "unchanged": bool, "photos": 成功张数,
          "skipped": 被拒张数, "kept": 旧照片是否保留, "removed": 旧照片元数据}。
    written=False + unchanged=True 表示按 updatedAt 判定库里的版本更新，本条原样跳过
    （此时不动照片）；调用方要把这个数单独报给用户，否则界面显示「写入 0 条」像是失败。

    conn 由调用方传入时整批复用同一条连接：本函数不提交、不关连接，
    旧照片文件也不在这里删（等调用方 commit 成功后再删，避免提交失败却已经删了图）。

    照片替换严格两阶段，顺序不能改：
    1. 所有新照片先解码/校验/重编码，落到 photos/.*.part 临时文件；
    2. 全部通过后才改名为正式文件，并在一个事务里换掉 photos 行，最后才删旧文件；
    3. 任一张失败 → 丢弃全部新文件，原有照片原样保留。
    绝不「先删旧照片再逐张写新照片」：备份里照片损坏/为空时，那等于直接销毁原图。
    """
    if repo.upsert(payload, conn=conn) == "skip":
        return {"written": False, "unchanged": True, "photos": 0,
                "skipped": 0, "kept": False, "removed": []}

    existing = repo.get(payload["id"], conn=conn) or {"photos": []}
    old_photos = existing.get("photos") or []
    if not photos_included:
        # 备份没带照片（mode=meta 或旧格式无法判断）：只恢复记录字段，照片一律不动
        return {"written": True, "unchanged": False, "photos": 0,
                "skipped": 0, "kept": bool(old_photos), "removed": []}

    staged, skipped = _stage_import_photos(photos)
    if skipped:
        _discard_staged(staged)
        return {"written": True, "unchanged": False, "photos": 0,
                "skipped": skipped, "kept": bool(old_photos), "removed": []}

    # 全部校验通过（0 张也走这里：photosIncluded=true 的空数组表示「确实没有照片」）
    moved = []
    try:
        for item in staged:
            os.replace(item["tmp"], item["final"])
            moved.append(item["final"])
        removed = repo.replace_photos(payload["id"], [i["photo"] for i in staged], conn=conn)
    except Exception:
        for path in moved:                 # 只回滚新文件；旧文件从头到尾没动过
            try:
                os.remove(path)
            except OSError:
                pass
        _discard_staged(staged)
        raise
    if conn is not None:
        # 复用连接：数据库还没提交，旧文件必须等调用方提交成功后再删
        return {"written": True, "unchanged": False, "photos": len(staged),
                "skipped": 0, "kept": False, "removed": removed or []}
    for p in (removed or []):
        _remove_photo_file(p.get("path"))  # 数据库已指向新集合，旧文件这时才删
    return {"written": True, "unchanged": False, "photos": len(staged),
            "skipped": 0, "kept": False, "removed": []}


def _import_one(conn, payload: dict, photos: list, photos_included: bool) -> dict:
    """写一条记录 + 提交 + 清理被替换的旧照片文件（整批导入共用一个连接）。"""
    res = _write_import_record(payload, photos, photos_included, conn=conn)
    conn.commit()
    for p in (res.get("removed") or []):
        _remove_photo_file(p.get("path"))      # 提交成功后才删旧文件
    res["removed"] = []
    return res


def _iter_import(cleaned: list, invalid: int, invalid_details: list, ids_renamed: int = 0):
    """逐条写库并产出进度事件（NDJSON）。整批复用一条连接，单条事务。"""
    yield json.dumps({"type": "start", "total": len(cleaned), "invalid": invalid,
                      "idsRenamed": ids_renamed}) + "\n"
    written = failed = unchanged = photos_skipped = photos_kept = 0
    with get_conn() as conn:
        for i, (payload, photos, photos_included) in enumerate(cleaned):
            try:
                res = _import_one(conn, payload, photos, photos_included)
                if res["written"]:
                    written += 1
                elif res.get("unchanged"):
                    unchanged += 1
                photos_skipped += res["skipped"]
                if res.get("kept"):
                    photos_kept += 1
            except Exception as e:                     # 单条失败不中断整批
                conn.rollback()
                failed += 1
                print(f"[import] 写入失败 {payload.get('id')}: {e}")
            if (i + 1) % 5 == 0 or i + 1 == len(cleaned):
                yield json.dumps({"type": "progress", "done": i + 1, "total": len(cleaned)}) + "\n"
    yield json.dumps({
        "type": "done", "written": written, "unchanged": unchanged, "invalid": invalid,
        "failed": failed, "invalidDetails": invalid_details,
        "photosSkipped": photos_skipped, "photosKept": photos_kept,
        "idsRenamed": ids_renamed,
    }) + "\n"


@app.post("/api/import")
async def import_records(file: UploadFile = File(...), confirm: bool = False, progress: bool = False):
    _cleanup_stale_import_temps()
    raw = await _read_limited(file, MAX_IMPORT_BYTES)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "文件不是合法 JSON")
    if not isinstance(data, dict) or data.get("app") != "foodmap" or "records" not in data:
        raise HTTPException(400, "文件格式不符（缺少 app/records）")
    records = data["records"]
    if not isinstance(records, list):
        raise HTTPException(400, "records 须为数组")
    if len(records) > MAX_IMPORT_RECORDS:
        raise HTTPException(413, f"记录条数过多（上限 {MAX_IMPORT_RECORDS} 条）")

    now = _now()
    append = update = invalid = ids_renamed = 0
    invalid_details = []
    cleaned = []
    # 一次取全部 id：预览只为区分「新增 / 覆盖」，逐条 repo.get 会开 N 条连接
    known_ids = repo.existing_ids()
    for i, r in enumerate(records):
        errs = validate_record(r)
        if errs:
            invalid += 1
            invalid_details.append({"index": i, "fields": [e[0] for e in errs], "msgs": [e[1] for e in errs]})
            continue
        try:
            payload = build_record_payload(r, now)
        except Exception as e:
            # 兜底：任何没预料到的字段组合都只让这一条失效，不 500 整批
            invalid += 1
            invalid_details.append({"index": i, "fields": ["record"], "msgs": [f"字段无法解析：{e}"]})
            continue
        # 备份里的 id 含 `/`、空格等字符时，记录能建成功但详情接口会 404；
        # build_record_payload 会换成新 uuid，这里只做统计，让用户知道 id 变了。
        raw_id = r.get("id")
        if isinstance(raw_id, str) and raw_id.strip() and raw_id.strip() != payload["id"]:
            ids_renamed += 1
        photos = r.get("photos") if isinstance(r, dict) else None
        if not isinstance(photos, list):
            photos, photos_included = [], False     # 形状不对就只恢复记录本身，不连带丢记录
        else:
            photos_included = _photos_included_flag(data, r, photos)
        existing = payload["id"] in known_ids
        if existing:
            update += 1
        else:
            append += 1
        cleaned.append((payload, photos, photos_included))

    if not confirm:
        return {
            "preview": True, "append": append, "update": update,
            "invalid": invalid, "invalidDetails": invalid_details,
            "total": len(records), "idsRenamed": ids_renamed,
        }

    # 确认写入：按 updatedAt 较新覆盖，新 id 追加
    if progress:
        # 边写边报进度：NDJSON，一行一个事件；前端用 fetch 流式读取
        return StreamingResponse(
            _iter_import(cleaned, invalid, invalid_details, ids_renamed),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    written = failed = unchanged = photos_skipped = photos_kept = 0
    # 整批复用一条连接：每条 4 次建连是导入慢（1000 条 ≈ 55s）的根因
    with get_conn() as conn:
        for payload, photos, photos_included in cleaned:
            try:
                res = _import_one(conn, payload, photos, photos_included)
                if res["written"]:
                    written += 1
                elif res.get("unchanged"):
                    unchanged += 1
                photos_skipped += res["skipped"]
                if res.get("kept"):
                    photos_kept += 1
            except Exception as e:
                # 单条失败不能让整批看起来"成功但少了几条"：计入 failed 并返回
                conn.rollback()
                failed += 1
                print(f"[import] 写入失败 {payload.get('id')}: {e}")
    return {"preview": False, "written": written, "unchanged": unchanged, "failed": failed,
            "invalid": invalid, "invalidDetails": invalid_details,
            "photosSkipped": photos_skipped, "photosKept": photos_kept,
            "idsRenamed": ids_renamed}


# ---------- 静态托管（前端） ----------
class NoCacheStaticFiles(StaticFiles):
    """本地应用：静态资源禁用强缓存，避免改动 CSS/JS 后浏览器仍用旧文件。"""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


if os.path.isdir(STATIC_DIR):
    app.mount("/", NoCacheStaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import threading
    import webbrowser

    from .pathconf import find_free_port, load_last_port, parse_port, save_last_port

    # PORT 环境变量写错（"abc"、99999）不能让进程崩在启动阶段：
    # 非法值只提示一句，然后退回「上次端口 / 随机可用端口」。
    env_port = os.environ.get("PORT")
    preferred = parse_port(env_port)
    if env_port and preferred is None:
        print(f"[FoodMap] PORT={env_port!r} 不是 1024–65535 的端口号，已忽略并自动选择端口。")
    if preferred is None:
        preferred = load_last_port()
    hint = crypto.status_hint()
    if hint:
        print(f"[FoodMap] 注意：{hint}")
    port = find_free_port(preferred)
    save_last_port(port)
    url = f"http://127.0.0.1:{port}"
    print(f"[FoodMap] 本地服务已启动: {url}")

    def _open_browser():
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # 等服务起来后再打开浏览器，避免连不上
    threading.Timer(1.5, _open_browser).start()
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port)
