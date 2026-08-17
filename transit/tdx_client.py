"""TDX 公車即時到站層。

★ 擁有者：P2。其他人請勿修改本檔（README §6）。

契約（已凍結，見 README §4）：
    get_eta(route_name, stop_name) -> (int | None, str)
        查到即時資料      -> (整數秒數, "即時")
        末班已過或未營運  -> (None, "末班已過")
        其他任何情況      -> (None, "班表推估")

★★ 這個函式絕對不能拋例外。網路、認證、解析的任何錯誤都要 catch 起來，
   回傳 (None, "班表推估")。這是刻意設計：P4 的組裝層因此完全不用寫
   try/except，兩人零溝通。
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import unicodedata
from pathlib import Path

import httpx


def _load_dotenv() -> None:
    """手動讀 .env（同層目錄），不引入 python-dotenv（README §0 禁止額外套件）。

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
    """取得並快取 access token（過期前 TOKEN_TTL_MARGIN 秒重取）。"""
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data["expires_in"] - TOKEN_TTL_MARGIN
    return _token_cache["access_token"]


async def _fetch_eta(route_name: str) -> list[dict]:
    """查 CITIES 兩個城市的即時到站並合併。20 秒快取，key 用 route_name。"""
    now = time.time()
    cached = _eta_cache.get(route_name)
    if cached and now - cached[0] < ETA_CACHE_TTL:
        return cached[1]

    token = await _get_token()
    headers = {"authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=10) as client:
        responses = await asyncio.gather(
            *(
                client.get(
                    ETA_URL.format(city=city, route=route_name),
                    headers=headers,
                    params={"$format": "JSON"},
                )
                for city in CITIES
            ),
            return_exceptions=True,
        )

    rows: list[dict] = []
    for resp in responses:
        if isinstance(resp, Exception) or resp.status_code != 200:
            continue
        rows.extend(resp.json())

    _eta_cache[route_name] = (now, rows)
    return rows


def _clean(name: str) -> str:
    name = name[:-1] if name.endswith("站") else name
    return name


def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)  # 全形轉半形
    name = re.sub(r"[（(].*?[）)]", "", name)  # 去除括號內容
    return name


def _match_stop(google_name: str, tdx_name: str) -> bool:
    """站名比對——依序嘗試，成功即停（README §6）。

    Google 說「台北車站」，TDX 可能是「臺北車站」（異體字）、
    「台北車站(忠孝)」（帶括號）、或「北車」。
    """
    if google_name == tdx_name:
        return True

    clean_g, clean_t = _clean(google_name), _clean(tdx_name)
    if clean_g == clean_t:
        return True

    if clean_g in tdx_name or tdx_name in google_name:
        return True

    if _normalize(google_name) == _normalize(tdx_name):
        return True

    return False


async def get_eta(route_name: str, stop_name: str) -> tuple[int | None, str]:
    """查某條公車在某站牌的即時到站。

    回傳 (等待秒數, 來源說明)：
        查到即時資料      -> (整數秒數, "即時")
        末班已過或未營運  -> (None, "末班已過")
        其他任何情況      -> (None, "班表推估")

    ★ 這個函式絕對不能拋例外。
    """
    try:
        rows = await _fetch_eta(route_name)

        for row in rows:
            tdx_stop_name = row.get("StopName", {}).get("Zh_tw", "")
            if not _match_stop(stop_name, tdx_stop_name):
                continue

            status = row.get("StopStatus")
            if status in (STATUS_LAST_TRIP_PASSED, STATUS_NOT_IN_SERVICE):
                return None, "末班已過"
            if status == STATUS_NORMAL and row.get("EstimateTime") is not None:
                return row["EstimateTime"], "即時"
            return None, "班表推估"

        return None, "班表推估"
    except Exception:
        return None, "班表推估"


if __name__ == "__main__":
    async def _main() -> None:
        token = await _get_token()
        print("token 前 20 字元:", token[:20])
        result = await get_eta("307", "台北車站")
        print("get_eta('307', '台北車站') =", result)

    asyncio.run(_main())
