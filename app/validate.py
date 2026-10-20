"""字段归一化与导入校验。

背景：备份文件来自用户自己（也可能来自别人转发的旧备份），字段类型不可信。
这里把「能救的字段救回来、救不了的字段拒绝」的规则集中在一处，
导入接口与读取路径（repository._row_to_record）共用同一套归一化，
避免畸形 tags 之类的东西一路流到前端把列表打挂。
"""
import json
import math
import re
import uuid
from datetime import datetime

# 标签：单条最多 32 个、每个最多 24 字（前端只展示前 3 个，存储不必无限长）
MAX_TAGS = 32
MAX_TAG_LEN = 24
# 店名/备注/字段长度上限，防止超长字符串拖垮列表与搜索
MAX_NAME_LEN = 120
MAX_TEXT_LEN = 2000
# 营业时间有两副面孔：
# - 新格式是完整七天排班 JSON（7 天 × 1 段 = 239 字，× 2 段 = 421 字），按结构校验、不按字数截断；
# - 旧格式是纯文本（"10:00-21:00"），才用这个 120 字上限。
MAX_HOURS_LEN = 120
MAX_SLOTS_PER_DAY = 6
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# 人均价格合理区间（元）
MIN_PRICE, MAX_PRICE = 0, 100000

CHECKIN_VALUES = ("want", "visited", "favorite")

# 记录 id：只有这些字符能安全出现在 URL 路径里
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 时间戳合理区间（毫秒）：2000-01-01 ~ 2100-01-01。
# 超范围的值（如被篡改成 10^17）会让 datetime.fromtimestamp 抛 ValueError/OverflowError，
# 从而把看板的整月统计打成 500，所以入口处就回落成 default。
MIN_TS_MS = 946_684_800_000
MAX_TS_MS = 4_102_444_800_000


def _clamp_ts(ms: int, default: int) -> int:
    return ms if MIN_TS_MS <= ms <= MAX_TS_MS else default


def stable_record_id(raw):
    """把备份里的 id 收敛成可安全放进 URL 的 id。

    安全 id 原样返回；不安全 id（`a/b`、含空格等）用 **uuid5** 派生确定性的新 id——
    同一份备份重复导入必须落到同一条记录上，否则每导一次就多一条同名记录。
    """
    sid = normalize_id(raw)
    if sid:
        return sid
    if isinstance(raw, str) and raw.strip():
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "foodmap:" + raw.strip()))
    return str(uuid.uuid4())


def normalize_id(value):
    """记录 id 必须能安全放进 URL 路径：只允许 `[A-Za-z0-9_-]`，最长 64。

    返回规范化后的 id；不合法返回 None（调用方生成新 uuid）。
    起因：备份里 id 写成 `a/b` 时，记录能建成功，但前端 `/api/records/a/b`
    会被路由拆成两段而 404，详情页直接打不开。
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if ID_RE.match(value) else None


def normalize_tags(value) -> list:
    """把任意输入收敛成 list[str]：字符串视为单个标签，其它类型丢弃。

    - 去空白、去空串、去重（保序）、截断超长标签、限制数量
    - dict / int / None 等一律返回 []
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out, seen = [], set()
    for tag in value:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if not tag or len(tag) > MAX_TAG_LEN or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= MAX_TAGS:
            break
    return out


def normalize_text(value, limit: int = MAX_TEXT_LEN):
    """可空文本：非字符串一律当 None，超长截断（而不是整条拒收）。"""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:limit]


def normalize_hours(value):
    """营业时间归一化：七天排班 JSON 按结构收敛，旧纯文本原样返回。

    返回 None 表示空值或「看起来是 JSON 但解析不了」；调用方据此决定拒绝还是丢弃。
    不能对 JSON 做长度截断——那会把 `{"mon":[{"s":"10:0` 这种半截数据写进库，
    前端 parseHours 解析失败后整周排班就没了。
    """
    if not isinstance(value, str):
        return None
    txt = value.strip()
    if not txt:
        return None
    if not txt.startswith("{"):
        return txt                      # 旧纯文本，长度由调用方决定

    try:
        obj = json.loads(txt)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    out, total = {}, 0
    for key in WEEKDAY_KEYS:
        slots = []
        raw_slots = obj.get(key)
        if isinstance(raw_slots, list):
            for slot in raw_slots[:MAX_SLOTS_PER_DAY]:
                if not isinstance(slot, dict):
                    continue
                start, end = slot.get("s"), slot.get("e")
                if (isinstance(start, str) and isinstance(end, str)
                        and TIME_RE.match(start.strip()) and TIME_RE.match(end.strip())):
                    slots.append({"s": start.strip(), "e": end.strip()})
        out[key] = slots
        total += len(slots)
    if not total:
        return None                     # 一周全空 = 没有营业时间
    # 与前端 serializeHours 的 JSON.stringify 输出保持一致（紧凑、无空格、周一到周日顺序）
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def clamp_hours(value):
    """导入用：结构化的排班 JSON 整体保留，只有旧纯文本才按 120 字截断。"""
    hours = normalize_hours(value)
    if hours is None:
        return None
    return hours if hours.startswith("{") else hours[:MAX_HOURS_LEN]


def normalize_price(value):
    """人均价格：接受数字字符串，其余返回 None；越界按边界截断。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        value = int(round(value))
    if value < MIN_PRICE or value > MAX_PRICE:
        return None
    return int(value)


def normalize_checkin(value):
    """打卡状态：只认三个枚举值，大小写/空白容错，其余当未设置。"""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in CHECKIN_VALUES else None


def normalize_rating(value, default: int = None):
    """星级：1-5 整数；bool 不算 int（True 会被当成 1）。非法返回 default。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if 1 <= value <= 5 else default


def normalize_ts(value, default: int) -> int:
    """时间戳统一为毫秒：兼容 秒/毫秒数字与 ISO 字符串；无法识别或超出合理区间用 default。"""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0:
            return default
        # 小于 10^11 视为秒级
        ms = int(value * 1000) if value < 100_000_000_000 else int(value)
        return _clamp_ts(ms, default)
    if isinstance(value, str):
        txt = value.strip().replace("Z", "+00:00")
        if not txt:
            return default
        if txt.isdigit():
            return normalize_ts(int(txt), default)
        try:
            return _clamp_ts(int(datetime.fromisoformat(txt).timestamp() * 1000), default)
        except (ValueError, OverflowError, OSError):
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return _clamp_ts(int(datetime.strptime(txt[:19], fmt).timestamp() * 1000), default)
            except (ValueError, OverflowError, OSError):
                continue
    return default


def validate_record(obj) -> list:
    """校验一条备份记录的核心字段；返回 [(字段, 说明)]，空列表表示可导入。

    只对「决定了记录是否可用」的字段做硬校验：店名、坐标、星级。
    其余字段由 normalize_* 尽量救回，避免因为一个脏字段丢掉整条记录。
    """
    if not isinstance(obj, dict):
        return [("record", "记录必须是对象")]

    errs = []
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        errs.append(("name", "店名必填"))
    elif len(name.strip()) > MAX_NAME_LEN:
        errs.append(("name", f"店名超过 {MAX_NAME_LEN} 字"))

    try:
        lng = float(obj.get("lng"))
        lat = float(obj.get("lat"))
    except (TypeError, ValueError):
        errs.append(("lng/lat", "坐标非法"))
    else:
        # NaN / inf 能通过 float()，但会让 SQLite 与前端排序出问题
        if not (math.isfinite(lng) and math.isfinite(lat)):
            errs.append(("lng/lat", "坐标非法"))
        elif not (-180 <= lng <= 180 and -90 <= lat <= 90):
            errs.append(("lng/lat", "坐标越界"))

    if normalize_rating(obj.get("rating", 3)) is None:
        errs.append(("rating", "星级须为1-5整数"))

    return errs


def build_record_payload(obj: dict, now: int) -> dict:
    """把一条已通过 validate_record 的备份记录收敛成可入库的 payload。"""
    rating = normalize_rating(obj.get("rating", 3), 3)
    draft = obj.get("draft", False)
    return {
        "id": stable_record_id(obj.get("id")),
        "name": obj["name"].strip()[:MAX_NAME_LEN],
        "lng": float(obj["lng"]),
        "lat": float(obj["lat"]),
        "rating": rating if rating is not None else 3,
        "tags": normalize_tags(obj.get("tags")),
        "businessHours": clamp_hours(obj.get("businessHours")),
        "avgPrice": normalize_price(obj.get("avgPrice")),
        "checkinStatus": normalize_checkin(obj.get("checkinStatus")),
        "note": normalize_text(obj.get("note")),
        "draft": bool(draft) if isinstance(draft, bool) else str(draft).lower() in ("1", "true", "yes"),
        "createdAt": normalize_ts(obj.get("createdAt"), now),
        "updatedAt": normalize_ts(obj.get("updatedAt"), now),
    }
