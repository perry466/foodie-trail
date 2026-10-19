"""FoodMap FastAPI 主程序：API + 静态托管"""
import base64
import io
import json
import os
import re
import time
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from . import crypto
from .coords import wgs84_to_gcj02, haversine
from .db import init_db
from .pathconf import (
    AMAP_REST, DATA_DIR, DEFAULT_PORT, PHOTOS_DIR, PHOTO_MAX_BYTES,
    PHOTO_MAX_COUNT, PHOTO_MAX_EDGE, PHOTO_QUALITY, STATIC_DIR,
)
from .repository import SQLiteRepository

app = FastAPI(title="FoodMap", version="1.0.0")
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
    img = Image.open(io.BytesIO(data))
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
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > PHOTO_MAX_EDGE:
        scale = PHOTO_MAX_EDGE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    quality = PHOTO_QUALITY
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    while buf.tell() > PHOTO_MAX_BYTES and quality > 30:
        quality -= 8
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
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
    checkinStatus: str = "", tags: str = "", includeDrafts: bool = False,
    draftsOnly: bool = False,
    swLng: float = None, swLat: float = None, neLng: float = None, neLat: float = None,
    sort: str = "updatedAt:desc", limit: int = 0, offset: int = 0,
):
    filters = {
        "keyword": keyword, "ratingMin": ratingMin, "ratingMax": ratingMax,
        "avgPriceMin": avgPriceMin, "avgPriceMax": avgPriceMax,
        "checkinStatus": checkinStatus, "includeDrafts": includeDrafts,
        "draftsOnly": draftsOnly,
    }
    if tags:
        filters["tags"] = [t for t in tags.split(",") if t]
    if None not in (swLng, swLat, neLng, neLat):
        filters["bounds"] = {"swLng": swLng, "swLat": swLat, "neLng": neLng, "neLat": neLat}
    sort_list = []
    for part in sort.split(","):
        f, _, d = part.partition(":")
        sort_list.append((f, d or "desc"))
    return repo.list(filters, sort_list, limit, offset)


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
    return repo.create(payload)


@app.put("/api/records/{rid}")
def update_record(rid: str, body: RecordIn):
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
    """批量删除：先删照片文件，再一次性删记录（photos 表随外键级联清理）。"""
    ids, seen = [], set()
    for rid in (body.ids or []):
        if isinstance(rid, str) and rid and rid not in seen:
            seen.add(rid)
            ids.append(rid)
    if not ids:
        return {"ok": True, "deleted": 0}
    for path in repo.photo_paths(ids):
        _remove_photo_file(path)
    return {"ok": True, "deleted": repo.delete_many(ids)}


@app.delete("/api/records/{rid}")
def delete_record(rid: str):
    # 删除记录及其照片文件
    rec = repo.get(rid)
    if rec:
        for p in rec["photos"]:
            _remove_photo_file(p["path"])
    repo.delete(rid)
    return {"ok": True}


def _remove_photo_file(rel_path: str):
    full = os.path.join(DATA_DIR, rel_path) if not os.path.isabs(rel_path) else rel_path
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
    data = await file.read()
    compressed = _compress_image(data)
    pid = str(uuid.uuid4())
    fname = f"{pid}.jpg"
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    full = os.path.join(PHOTOS_DIR, fname)
    with open(full, "wb") as f:
        f.write(compressed)
    photo = {
        "id": pid, "recordId": rid,
        "path": os.path.join("photos", fname), "thumb": None, "createdAt": _now(),
    }
    repo.add_photo(photo)
    return photo


@app.get("/api/photos/{pid}")
def get_photo(pid: str):
    p = repo.get_photo(pid)
    if not p:
        raise HTTPException(404, "照片不存在")
    full = os.path.join(DATA_DIR, p["path"]) if not os.path.isabs(p["path"]) else p["path"]
    if not os.path.exists(full):
        raise HTTPException(404, "照片文件丢失")
    return FileResponse(full)


@app.delete("/api/photos/{pid}")
def delete_photo(pid: str):
    p = repo.get_photo(pid)
    if p:
        _remove_photo_file(p["path"])
        repo.delete_photo(pid)
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
        raise HTTPException(400, "未配置高德 Web 服务 Key：POI 搜索需要「Web 服务」类型的 Key，请在「设置 → ③ 后端 Web 服务 Key」里填写")
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
        raise HTTPException(400, "未配置高德 Web 服务 Key：地址解析需要「Web 服务」类型的 Key，请在「设置 → ③ 后端 Web 服务 Key」里填写")
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
    lng = body.get("lng"); lat = body.get("lat")
    if lng is None or lat is None:
        raise HTTPException(400, "需要 lng,lat")
    glng, glat = wgs84_to_gcj02(float(lng), float(lat))
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
def _build_export(mode: str, filters: dict, sort_list: list) -> dict:
    records = repo.list(filters, sort_list)
    out_records = []
    for r in records:
        full = repo.get(r["id"])  # 含 photos（含路径）
        rec = {
            "id": r["id"], "name": r["name"], "lng": r["lng"], "lat": r["lat"],
            "rating": r["rating"], "tags": r["tags"], "businessHours": r["businessHours"],
            "avgPrice": r["avgPrice"], "checkinStatus": r["checkinStatus"],
            "note": r["note"], "draft": r["draft"],
            "createdAt": r["createdAt"], "updatedAt": r["updatedAt"],
            "photos": [],
        }
        if mode == "full":
            for p in full["photos"]:
                full_path = os.path.join(DATA_DIR, p["path"]) if not os.path.isabs(p["path"]) else p["path"]
                if os.path.exists(full_path):
                    with open(full_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    rec["photos"].append({
                        "id": p["id"], "data": b64, "name": os.path.basename(p["path"]),
                    })
        out_records.append(rec)
    return {
        "app": "foodmap", "version": 2,
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "records": out_records,
    }


@app.get("/api/export")
def export_records(
    mode: str = "full",
    keyword: str = "", ratingMin: int = None, ratingMax: int = None,
    avgPriceMin: int = None, avgPriceMax: int = None,
    checkinStatus: str = "", tags: str = "", includeDrafts: bool = True,
    sort: str = "updatedAt:desc",
):
    """导出备份。includeDrafts 默认为 True：草稿也是用户数据，备份不应静默遗漏。"""
    filters = {
        "keyword": keyword, "ratingMin": ratingMin, "ratingMax": ratingMax,
        "avgPriceMin": avgPriceMin, "avgPriceMax": avgPriceMax,
        "checkinStatus": checkinStatus, "includeDrafts": includeDrafts,
    }
    if tags:
        filters["tags"] = [t for t in tags.split(",") if t]
    sort_list = [(s.partition(":")[0], s.partition(":")[2] or "desc") for s in sort.split(",")]
    data = _build_export(mode, filters, sort_list)
    n = len(data["records"])
    fname = f"foodmap-backup-{time.strftime('%Y%m%d')}-{n}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _validate_record(obj: dict, index: int):
    errs = []
    if not isinstance(obj.get("name"), str) or not obj.get("name").strip():
        errs.append(("name", "店名必填"))
    try:
        lng = float(obj.get("lng")); lat = float(obj.get("lat"))
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            errs.append(("lng/lat", "坐标越界"))
    except (TypeError, ValueError):
        errs.append(("lng/lat", "坐标非法"))
    rating = obj.get("rating", 3)
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        errs.append(("rating", "星级须为1-5整数"))
    return errs


@app.post("/api/import")
async def import_records(file: UploadFile = File(...), confirm: bool = False):
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "文件不是合法 JSON")
    if not isinstance(data, dict) or data.get("app") != "foodmap" or "records" not in data:
        raise HTTPException(400, "文件格式不符（缺少 app/records）")
    records = data["records"]
    if not isinstance(records, list):
        raise HTTPException(400, "records 须为数组")

    append = update = invalid = 0
    invalid_details = []
    cleaned = []
    for i, r in enumerate(records):
        errs = _validate_record(r, i)
        if errs:
            invalid += 1
            invalid_details.append({"index": i, "fields": [e[0] for e in errs], "msgs": [e[1] for e in errs]})
            continue
        payload = {
            "id": r.get("id") or str(uuid.uuid4()),
            "name": r["name"], "lng": float(r["lng"]), "lat": float(r["lat"]),
            "rating": int(r.get("rating", 3)), "tags": r.get("tags", []),
            "businessHours": r.get("businessHours"), "avgPrice": r.get("avgPrice"),
            "checkinStatus": r.get("checkinStatus"), "note": r.get("note"),
            "draft": bool(r.get("draft", False)),
            "createdAt": int(r.get("createdAt", _now())),
            "updatedAt": int(r.get("updatedAt", _now())),
        }
        existing = repo.get(payload["id"])
        if existing:
            update += 1
        else:
            append += 1
        cleaned.append((payload, r.get("photos", [])))

    if not confirm:
        return {
            "preview": True, "append": append, "update": update,
            "invalid": invalid, "invalidDetails": invalid_details,
            "total": len(records),
        }

    # 确认写入：按 updatedAt 较新覆盖，新 id 追加
    written = 0
    for payload, photos in cleaned:
        res = repo.upsert(payload)
        if res == "skip":
            continue
        written += 1
        # 重置该记录照片
        rec = repo.get(payload["id"])
        for p in rec["photos"]:
            _remove_photo_file(p["path"])
            repo.delete_photo(p["id"])
        for ph in photos:
            b64 = ph.get("data")
            if not b64:
                continue
            try:
                img_data = base64.b64decode(b64)
            except Exception:
                continue
            pid = str(uuid.uuid4())
            fname = f"{pid}.jpg"
            os.makedirs(PHOTOS_DIR, exist_ok=True)
            with open(os.path.join(PHOTOS_DIR, fname), "wb") as f:
                f.write(img_data)
            repo.add_photo({
                "id": pid, "recordId": payload["id"],
                "path": os.path.join("photos", fname), "thumb": None, "createdAt": _now(),
            })
    return {"preview": False, "written": written, "invalid": invalid,
            "invalidDetails": invalid_details}


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

    from .pathconf import (
        find_free_port,
        load_last_port,
        save_last_port,
    )

    env_port = os.environ.get("PORT")
    preferred = int(env_port) if env_port else load_last_port()
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
