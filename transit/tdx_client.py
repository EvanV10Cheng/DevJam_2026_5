"""TDX 公車即時到站層。

★ 擁有者：P2。其他人請勿修改本檔（README §6）。
★ 目前狀態：骨架 + 假回傳，讓 main.py 從第 1 小時就能跑起來。
   P2 完成後把 return _FAKE_ETA 換成真實實作。

契約（已凍結，見 README §4）：
    get_eta(route_name, stop_name) -> (int | None, str)
        查到即時資料      -> (整數秒數, "即時")
        末班已過或未營運  -> (None, "末班已過")
        其他任何情況      -> (None, "班表推估")

★★ 這個函式絕對不能拋例外。網路、認證、解析的任何錯誤都要 catch 起來，
   回傳 (None, "班表推估")。這是刻意設計：P4 的組裝層因此完全不用寫
   try/except，兩人零溝通。
"""

import os

AUTH_URL = (
    "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
)
ETA_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/{city}/{route}"

CLIENT_ID = os.getenv("TDX_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET", "")

# 大台北要查兩個 city 再合併結果
CITIES = ["Taipei", "NewTaipei"]

# StopStatus 語意（README §6）
STATUS_NORMAL = 0
STATUS_NOT_DEPARTED = 1
STATUS_SKIPPED = 2
STATUS_LAST_TRIP_PASSED = 3
STATUS_NOT_IN_SERVICE = 4

TOKEN_TTL_MARGIN = 60  # 過期前 60 秒就重新申請
ETA_CACHE_TTL = 20  # 即時到站快取 20 秒

_token_cache: dict = {"access_token": None, "expires_at": 0.0}
_eta_cache: dict = {}  # route_name -> (存入時間, 原始回傳 list)


async def _get_token() -> str:
    """取得並快取 access token。

    POST AUTH_URL，form data:
        grant_type=client_credentials, client_id=..., client_secret=...
    回傳 {"access_token": "...", "expires_in": 86400}

    Token 有效期約 24 小時，必須快取；每次呼叫都重取會被限流。
    驗收：連續呼叫兩次，第二次不產生 HTTP 請求。
    401 時先檢查 secret 有沒有多餘空白。

    TODO(P2, 步驟 2.1)
    """
    raise NotImplementedError


async def _fetch_eta(route_name: str) -> list[dict]:
    """查 CITIES 兩個城市的即時到站並合併。加 20 秒快取，key 用 route_name。

    GET ETA_URL，header: authorization: Bearer {token}，query: $format=JSON
    要用的欄位：StopName.Zh_tw / EstimateTime（可能為 null）/ StopStatus

    TODO(P2, 步驟 2.2 / 2.6 / 2.8)
    """
    raise NotImplementedError


def _match_stop(google_name: str, tdx_name: str) -> bool:
    """站名比對——本條線的核心難題。

    Google 說「台北車站」，TDX 可能是「臺北車站」（異體字）、
    「台北車站(忠孝)」（帶括號）、或「北車」。

    依序嘗試，成功即停：
        1. 完全相同
        2. 去掉「站」字後完全相同
        3. 雙向包含：clean in tdx_name 或 tdx_name in google_name
        4. 全形轉半形、去除所有括號內容後再比一次

    ★ 硬性上限 30 分鐘。超過就停手，接受回傳「班表推估」。
      走降級不算失敗——Demo 只需要找到一條對得上的路線。

    TODO(P2, 步驟 2.5)
    """
    raise NotImplementedError


# 假回傳：P2 實作完成後刪除
_FAKE_ETA: tuple[int | None, str] = (180, "即時")


async def get_eta(route_name: str, stop_name: str) -> tuple[int | None, str]:
    """查某條公車在某站牌的即時到站。

    回傳 (等待秒數, 來源說明)：
        查到即時資料      -> (整數秒數, "即時")
        末班已過或未營運  -> (None, "末班已過")
        其他任何情況      -> (None, "班表推估")

    ★ 這個函式絕對不能拋例外。

    TODO(P2, 步驟 2.4 / 2.7)：
        rows = await _fetch_eta(route_name)
        找出 _match_stop(stop_name, row["StopName"]["Zh_tw"]) 的那筆
        StopStatus 3 或 4                        -> (None, "末班已過")
        StopStatus 0 且 EstimateTime 不為 null   -> (EstimateTime, "即時")
        其他所有情況                              -> (None, "班表推估")
        最外層包 try/except Exception -> (None, "班表推估")
    """
    return _FAKE_ETA
