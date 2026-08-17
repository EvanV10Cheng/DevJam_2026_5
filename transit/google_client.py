"""Google Routes 串接層。

★ 擁有者：P1。其他人請勿修改本檔（README §5）。
★ 目前狀態：骨架 + 假回傳，讓 main.py 從第 1 小時就能跑起來。
   P1 完成後把 _FAKE_PLANS 那段刪掉，換成真實實作。

契約（已凍結，見 README §4）：
    get_routes(origin, destination) -> list[plan]
    每個 plan 含且僅含：totalSeconds / transferCount / steps / polyline
    等待相關欄位（waitSeconds / waitSource / realSeconds / isLive）由 main.py 補上。
    失敗時回傳 []，不要拋例外。
"""

import os

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
    ]
)

# transitLine.vehicle.type -> 我們的 mode。實際值必須實測，缺的補進來（步驟 1.5 / 1.6）
VEHICLE_TYPE_MAP = {
    "BUS": "BUS",
    "SUBWAY": "METRO",
    "METRO_RAIL": "METRO",
    "HEAVY_RAIL": "TRAIN",
    "RAIL": "TRAIN",
    "COMMUTER_TRAIN": "TRAIN",
    "HIGH_SPEED_TRAIN": "HSR",
    "LONG_DISTANCE_TRAIN": "HSR",
}
DEFAULT_MODE = "BUS"


def _secs(value) -> int:
    """把 Google 的 "900s" / "900.5s" / None 轉成 int 秒數。

    TODO(P1, 步驟 1.2)：驗收條件 _secs("900s") == 900、_secs(None) == 0
    """
    raise NotImplementedError


def parse_route(route: dict) -> dict:
    """把單一 route 攤平成一個 plan。

    重點：步驟藏在 routes[].legs[].steps[]，是兩層巢狀，要用雙層迴圈攤平。
    取值路徑：
        路線名稱 transitDetails.transitLine.nameShort 優先，沒有才用 .name
        上車站   transitDetails.stopDetails.departureStop.name
        下車站   transitDetails.stopDetails.arrivalStop.name
        站數     transitDetails.stopCount
        transferCount = RIDE 步驟數 - 1（最小值 0）

    TODO(P1, 步驟 1.3)
    """
    raise NotImplementedError


# --------------------------------------------------------------------------
# 假回傳：P1 實作完成後整段刪除
# --------------------------------------------------------------------------
_FAKE_PLANS: list[dict] = [
    {
        "totalSeconds": 1980,
        "transferCount": 1,
        "polyline": "yzxwCstn`Vg@_AcBqCsAyBoAoB",
        "steps": [
            {"type": "WALK", "seconds": 180, "meters": 210},
            {
                "type": "RIDE",
                "mode": "BUS",
                "routeName": "307",
                "fromStop": "台北車站",
                "toStop": "西門",
                "seconds": 600,
                "stopCount": 5,
            },
            {"type": "WALK", "seconds": 120, "meters": 140},
            {
                "type": "RIDE",
                "mode": "METRO",
                "routeName": "淡水信義線",
                "fromStop": "西門",
                "toStop": "淡水",
                "seconds": 960,
                "stopCount": 14,
            },
            {"type": "WALK", "seconds": 120, "meters": 150},
        ],
    },
    {
        "totalSeconds": 1800,
        "transferCount": 0,
        "polyline": "uzxwCqtn`VsBiDwAyBkAiB",
        "steps": [
            {"type": "WALK", "seconds": 300, "meters": 380},
            {
                "type": "RIDE",
                "mode": "BUS",
                "routeName": "紅 15",
                "fromStop": "捷運劍潭站",
                "toStop": "淡水捷運站",
                "seconds": 1320,
                "stopCount": 18,
            },
            {"type": "WALK", "seconds": 180, "meters": 200},
        ],
    },
]


async def get_routes(origin: str, destination: str) -> list[dict]:
    """呼叫 Google Routes API 並正規化。

    回傳 list[plan]，每個 plan 含且僅含：
        totalSeconds, transferCount, steps, polyline
    等待相關欄位由 main.py 負責補上，這裡不要碰。

    失敗時回傳空 list []，不要拋例外。

    TODO(P1, 步驟 1.4 / 1.7 / 1.8)：
        POST ENDPOINT
        headers = {"X-Goog-Api-Key": API_KEY,
                   "X-Goog-FieldMask": FIELD_MASK,
                   "Content-Type": "application/json"}
        body    = {"origin": {"address": origin},
                   "destination": {"address": destination},
                   "travelMode": "TRANSIT",
                   "computeAlternativeRoutes": True,
                   "languageCode": "zh-TW",
                   "regionCode": "TW"}
        回傳 [parse_route(r) for r in data.get("routes", [])]
        整段包 try/except，任何失敗 return []
        再加 20 秒行程內快取（key = origin + destination）
    """
    return _FAKE_PLANS
