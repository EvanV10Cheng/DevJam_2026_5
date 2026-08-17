"""Google Routes 串接層。

★ 擁有者：P1。其他人請勿修改本檔（README §5）。
★ 目前狀態：已串接 Google Routes API，並將原始回傳正規化為凍結契約。

契約（已凍結，見 README §4）：
    get_routes(origin, destination) -> list[plan]
    每個 plan 含且僅含：totalSeconds / transferCount / steps / polyline
    等待相關欄位（waitSeconds / waitSource / realSeconds / isLive）由 main.py 補上。
    失敗時回傳 []，不要拋例外。
"""

import copy
import os
import time
from pathlib import Path

import httpx


def _load_dotenv() -> None:
    """手動讀 .env（同層目錄），不引入 python-dotenv。

    只在環境變數尚未設定時才填入，執行時手動 export 的值優先。
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# 沒有 FieldMask 會回 400，Routes API 強制要求（README §5）
FIELD_MASK = ",".join(
    [
        "routes.duration",
        "routes.distanceMeters",
        "routes.polyline.encodedPolyline",
        "routes.legs.steps.travelMode",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.distanceMeters",
        "routes.legs.steps.transitDetails",
        # 整條路線的票價。Routes API 只在 TRANSIT 模式且該地區有票價資料時才回傳。
        # https://developers.google.com/maps/documentation/routes/reference/rest/v2/RouteTravelAdvisory
        "routes.travelAdvisory.transitFare",
    ]
)

FARE_CURRENCY = "TWD"

# transitLine.vehicle.type -> 我們的 mode。實際值必須實測，缺的補進來（步驟 1.5 / 1.6）
VEHICLE_TYPE_MAP = {
    "BUS": "BUS",
    "SUBWAY": "METRO",
    "METRO_RAIL": "METRO",
    "HEAVY_RAIL": "TRAIN",
    "RAIL": "TRAIN",
    "COMMUTER_TRAIN": "TRAIN",
    "HIGH_SPEED_TRAIN": "HSR",
    # Google 的 LONG_DISTANCE_TRAIN 是長途列車，不等於台灣高鐵；
    # 自強號等台鐵對號列車也可能使用這個類型。
    "LONG_DISTANCE_TRAIN": "TRAIN",
}
DEFAULT_MODE = "BUS"

METRO_LINE_NAME_MAP = {
    "wenhu line": "文湖線",
    "wenhu": "文湖線",
    "tamsui-xinyi line": "淡水信義線",
    "tamsui-xinyi": "淡水信義線",
    "songshan-xindian line": "松山新店線",
    "songshan-xindian": "松山新店線",
    "zhonghe-xinlu line": "中和新蘆線",
    "zhonghe-xinlu": "中和新蘆線",
    "bannan line": "板南線",
    "bannan": "板南線",
    "circular line": "環狀線",
    "circular": "環狀線",
}

# Google 的台灣鐵路 vehicle.type 偶爾過於籠統，以中英文名稱協助校正。
HSR_NAME_HINTS = ("高鐵", "thsr", "taiwan high speed rail")
TRA_NAME_HINTS = (
    "台鐵",
    "臺鐵",
    "區間",
    "自強",
    "莒光",
    "復興",
    "普悠瑪",
    "太魯閣",
    "taiwan railways",
    "taiwan railway",
    "tze-chiang",
    "local train",
)

# ★ 這個數字直接決定 Google 配額燒多快，前端是 30 秒輪詢一次。
#
#   快取 20 秒  → 每次輪詢都 miss → 單一可見分頁每小時 120 次 → 1000 次配額撐 8 小時
#   快取 300 秒 → 每 5 分鐘才問一次 → 每小時 12 次           → 撐 83 小時
#
# 路線「形狀」（搭哪幾班車、經過哪些站）不會每 30 秒變，會變的是即時資料，
# 而那一層由 TDX 負責（ETA_CACHE_TTL 維持 20 秒）。所以拉長這裡不影響新鮮度。
ROUTE_CACHE_TTL = 300
_route_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def _secs(value) -> int:
    """把 Google 的 "900s" / "900.5s" / None 轉成 int 秒數。

    無法解析或小於零的值視為 0，避免外部資料異常破壞 API 契約。
    """
    if value is None:
        return 0

    try:
        raw = str(value).strip()
        if raw.endswith("s"):
            raw = raw[:-1]
        return max(int(float(raw)), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalize_line_name(value) -> str:
    """統一路線名稱的大小寫、空白與連字號，供比對使用。"""
    normalized = " ".join(str(value or "").strip().split()).casefold()
    normalized = normalized.replace("–", "-").replace("—", "-")
    return normalized.replace(" - ", "-").replace("- ", "-").replace(" -", "-")


def _resolve_mode(vehicle_type, line_names: str) -> str:
    """辨識交通種類；明確的台鐵／高鐵名稱優先於 Google 的籠統分類。

    ★ 但 vehicle.type 為 BUS 時不套用名稱判斷。Google 說是公車就是公車，
      而台北有一堆叫「區間車」的公車（919區間車、236區間車…），
      TRA_NAME_HINTS 含「區間」會把它們全部誤判成台鐵，
      連帶讓 main.py 跳過公車的 TDX 查詢。
    """
    if vehicle_type == "BUS":
        return "BUS"

    normalized_names = _normalize_line_name(line_names)
    if any(hint in normalized_names for hint in HSR_NAME_HINTS):
        return "HSR"
    if any(hint in normalized_names for hint in TRA_NAME_HINTS):
        return "TRAIN"
    return VEHICLE_TYPE_MAP.get(vehicle_type, DEFAULT_MODE)


def _has_cjk(value: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in value)


def _localize_route_name(route_name: str, mode: str, full_name: str = "") -> str:
    """把英文路線名換成中文。

    Google 的 nameShort 對公車是編號（307、藍22，直接可用），
    但對軌道運輸常常是英文（Tamsui-Xinyi Line、Local Train、
    Tze-Chiang Limited Express），而 name 才是中文（淡水信義線、
    區間車、自強號）。捷運走對照表，台鐵／高鐵直接改用 name。
    """
    if mode == "METRO":
        return METRO_LINE_NAME_MAP.get(_normalize_line_name(route_name), route_name)
    if mode in ("TRAIN", "HSR") and not _has_cjk(route_name) and _has_cjk(full_name):
        return full_name
    return route_name


def _parse_money(money) -> int | float | None:
    """解析 Google Money（currencyCode / units / nanos）成台幣金額。

    https://developers.google.com/maps/documentation/routes/transit-route

    units 是「整數部分」的字串，nanos 是十億分之一的小數部分。
    只接受 TWD；幣別不符、缺欄位、非數字、負值一律回 None——
    ★ 回 None 而不是 0，因為「查不到票價」和「免費」是完全不同的兩件事，
      混在一起會讓前端把未知票價當成最便宜的方案。
    """
    if not isinstance(money, dict):
        return None
    if str(money.get("currencyCode") or "").upper() != FARE_CURRENCY:
        return None

    units, nanos = money.get("units"), money.get("nanos")
    if units is None and nanos is None:
        return None

    try:
        whole = int(units) if units is not None else 0
        frac = int(nanos) if nanos is not None else 0
    except (TypeError, ValueError):
        return None

    if whole < 0 or frac < 0:
        return None  # 負票價不合理，當成無效資料

    return whole if frac == 0 else whole + frac / 1_000_000_000


def _latlng(stop: dict) -> dict | None:
    """從 Google 的 stopDetails.*.location.latLng 取座標。

    這是站點比對的關鍵：TDX 的站名是「臺北」、Google 是「台北」，
    字串永遠對不上；改用座標找最近站就完全繞開異體字問題。
    """
    ll = ((stop or {}).get("location") or {}).get("latLng") or {}
    lat, lng = ll.get("latitude"), ll.get("longitude")
    if lat is None or lng is None:
        return None
    return {"lat": float(lat), "lng": float(lng)}


def _merge_walks(steps: list[dict]) -> list[dict]:
    """把連續的 WALK 步驟合併成一段，時間與距離相加（需求 8）。

    Google 會把一次步行拆成很多小段——實測「台北車站→淡水」單一方案就有
    8 個 WALK 步驟（含 466m/18s 這種它自己的怪值）。對使用者來說那就是
    「走一段路」，拆開顯示只是雜訊。

    RIDE 之間的步行仍會各自獨立成一段，因為中間隔著搭乘段，不會被合併——
    那才是真正的轉乘步行。
    """
    merged: list[dict] = []
    for step in steps:
        if step.get("type") == "WALK" and merged and merged[-1].get("type") == "WALK":
            prev = merged[-1]
            prev["seconds"] += step.get("seconds", 0)
            prev["meters"] += step.get("meters", 0)
            continue
        merged.append(dict(step))
    return merged


def parse_route(route: dict) -> dict:
    """把單一 route 攤平成一個 plan。

    重點：步驟藏在 routes[].legs[].steps[]，是兩層巢狀，要用雙層迴圈攤平。
    取值路徑：
        路線名稱 transitDetails.transitLine.nameShort 優先，沒有才用 .name
        上車站   transitDetails.stopDetails.departureStop.name
        下車站   transitDetails.stopDetails.arrivalStop.name
        站數     transitDetails.stopCount
        transferCount = RIDE 步驟數 - 1（最小值 0）

    缺少的外部欄位使用 0 或空字串，確保凍結契約中的欄位一律存在。
    """
    steps: list[dict] = []
    ride_count = 0

    for leg in route.get("legs") or []:
        for step in leg.get("steps") or []:
            transit = step.get("transitDetails") or {}
            if step.get("travelMode") == "TRANSIT" or transit:
                line = transit.get("transitLine") or {}
                vehicle = line.get("vehicle") or {}
                stop_details = transit.get("stopDetails") or {}
                departure_stop = stop_details.get("departureStop") or {}
                arrival_stop = stop_details.get("arrivalStop") or {}
                name_short = str(line.get("nameShort") or "")
                name = str(line.get("name") or "")
                route_name = name_short or name
                mode = _resolve_mode(vehicle.get("type"), f"{name_short} {name}")
                route_name = _localize_route_name(route_name, mode, name)

                try:
                    stop_count = max(int(transit.get("stopCount") or 0), 0)
                except (TypeError, ValueError, OverflowError):
                    stop_count = 0

                try:
                    ride_meters = max(int(step.get("distanceMeters") or 0), 0)
                except (TypeError, ValueError, OverflowError):
                    ride_meters = 0

                steps.append(
                    {
                        "type": "RIDE",
                        "mode": mode,
                        "routeName": route_name,
                        "fromStop": str(departure_stop.get("name") or ""),
                        "toStop": str(arrival_stop.get("name") or ""),
                        "seconds": _secs(step.get("staticDuration")),
                        "stopCount": stop_count,
                        # 前端已會讀 meters / departAt / arriveAt，順手填滿
                        "meters": ride_meters,
                        "departAt": str(stop_details.get("departureTime") or ""),
                        "arriveAt": str(stop_details.get("arrivalTime") or ""),
                        # 以下給 main.py 查 TDX 用：座標比對比站名字串比對可靠得多
                        # （TDX 的「臺北」對 Google 的「台北」字串永遠對不上）
                        "headsign": str(transit.get("headsign") or ""),
                        "fromStopPos": _latlng(departure_stop),
                        "toStopPos": _latlng(arrival_stop),
                    }
                )
                ride_count += 1
                continue

            try:
                meters = max(int(step.get("distanceMeters") or 0), 0)
            except (TypeError, ValueError, OverflowError):
                meters = 0

            steps.append(
                {
                    "type": "WALK",
                    "seconds": _secs(step.get("staticDuration")),
                    "meters": meters,
                }
            )

    polyline = route.get("polyline") or {}
    fare = _parse_money(((route.get("travelAdvisory") or {}).get("transitFare")))
    return {
        "totalSeconds": _secs(route.get("duration")),
        "transferCount": max(ride_count - 1, 0),
        # ★ 兩個欄位一律存在（README §3）。Google 只給單一票價，沒有悠遊卡價，
        #   所以 icFare 恆為 None —— 不自行猜價，猜錯比沒有更糟。
        "fare": fare,
        "icFare": None,
        "steps": _merge_walks(steps),
        "polyline": str(polyline.get("encodedPolyline") or ""),
    }


async def get_routes(origin: str, destination: str) -> list[dict]:
    """呼叫 Google Routes API 並正規化。

    回傳 list[plan]，每個 plan 含且僅含：
        totalSeconds, transferCount, steps, polyline
    等待相關欄位由 main.py 負責補上，這裡不要碰。

    失敗時回傳空 list []，不要拋例外。

    同一組起訖點快取 20 秒；快取值以深拷貝回傳，避免組裝層補欄位後
    污染下一次 get_routes() 的四欄輸出。
    """
    if not API_KEY:
        return []

    cache_key = (origin, destination)
    now = time.monotonic()
    cached = _route_cache.get(cache_key)
    if cached is not None and now - cached[0] < ROUTE_CACHE_TTL:
        return copy.deepcopy(cached[1])

    headers = {
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }
    body = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "TRANSIT",
        "computeAlternativeRoutes": True,
        "languageCode": "zh-TW",
        "regionCode": "TW",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(ENDPOINT, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

        routes = data.get("routes", [])
        if not isinstance(routes, list):
            return []

        plans = [parse_route(route) for route in routes if isinstance(route, dict)]
        _route_cache[cache_key] = (time.monotonic(), copy.deepcopy(plans))
        return plans
    except Exception:
        return []
