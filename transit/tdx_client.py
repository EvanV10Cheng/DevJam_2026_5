"""TDX 即時資料層。

契約（見 README §4）：
    get_eta(route_name, stop_name) -> (int | None, str)

★★ get_eta 絕不拋例外。網路、認證、解析的任何錯誤都要 catch 起來。
   這是刻意設計：main.py 的組裝層因此完全不用寫 try/except。

本檔的三個地基機制（所有後續端點都共用）：
  1. 三組金鑰輪替  —— .env 的 TDX_CLIENT_ID_{1,2,3}，round-robin 分攤請求
  2. 429 冷卻      —— 某組被限流就暫時跳過，換下一組重試
  3. 快取 + 併發合流 —— 同一個 key 的併發查詢共用一次 HTTP，不重複打
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlencode

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
BASE = "https://tdx.transportdata.tw/api/basic"
ETA_URL = BASE + "/v2/Bus/EstimatedTimeOfArrival/City/{city}/{route}"

# 大台北要查兩個 city 再合併結果
CITIES = ["Taipei", "NewTaipei"]

# StopStatus 語意（README §6）
STATUS_NORMAL = 0
STATUS_NOT_DEPARTED = 1
STATUS_SKIPPED = 2
STATUS_LAST_TRIP_PASSED = 3
STATUS_NOT_IN_SERVICE = 4

# waitSource 的取值。★ 這是契約值，改動要同步 check_contract.py 與 README §3
SRC_LIVE = "即時"
SRC_NO_SERVICE = "無班次"  # 查得到這站，但目前沒有班次資訊
SRC_LAST_PASSED = "末班已過"
SRC_RATE_LIMITED = "查詢受限"  # 被 TDX 限流，不是真的沒車
SRC_SCHEDULE = "班表推估"  # 查無路線／其他錯誤的預設降級

TOKEN_TTL_MARGIN = 60  # 過期前 60 秒就重新申請
RATE_LIMIT_COOLDOWN = 30  # 某組金鑰被 429 後冷卻幾秒
ETA_CACHE_TTL = 20  # 即時到站快取 20 秒

# 車輛位置的快取比到站時間長。它的用途是佐證「路上真的有這個方向的車」，
# 不像 ETA 那樣需要秒級新鮮度。★ 這是 30 秒輪詢能不被限流的關鍵：
# 實測它佔單次輪詢 18 個請求裡的 10 個，拉長快取後降到 3 個左右，
# 整體從 0.6 req/s 降到 0.37 req/s，退到 TDX 的限流門檻底下。
NEAR_STOP_CACHE_TTL = 90
STATIC_CACHE_TTL = 86400  # 站點清單等靜態資料快取一天


# --------------------------------------------------------------------------
# 金鑰池：三組金鑰輪流分攤請求
# --------------------------------------------------------------------------


def _load_credentials() -> list[dict]:
    """讀取 .env 裡的金鑰組。支援 TDX_CLIENT_ID_1/2/3，也相容舊的單組命名。"""
    creds: list[dict] = []
    seen: set[tuple[str, str]] = set()

    candidates = [
        (os.getenv(f"TDX_CLIENT_ID_{i}", ""), os.getenv(f"TDX_CLIENT_SECRET_{i}", ""))
        for i in (1, 2, 3)
    ]
    candidates.append((os.getenv("TDX_CLIENT_ID", ""), os.getenv("TDX_CLIENT_SECRET", "")))

    for cid, secret in candidates:
        # strip 很重要：貼金鑰時常帶到前後空白，症狀是 401（README §6）
        cid, secret = cid.strip(), secret.strip()
        if not cid or not secret or (cid, secret) in seen:
            continue
        seen.add((cid, secret))
        creds.append(
            {
                "client_id": cid,
                "client_secret": secret,
                "token": None,
                "expires_at": 0.0,
                "cooldown_until": 0.0,
            }
        )
    return creds


_slots = _load_credentials()
_rr = 0

# 對外揭露，讓診斷腳本能檢查金鑰有沒有讀到
CREDENTIAL_COUNT = len(_slots)


def _pick_slot() -> dict | None:
    """Round-robin 挑一組金鑰，跳過冷卻中的。全部冷卻時回傳最早解凍的那組。"""
    global _rr
    if not _slots:
        return None
    now = time.time()
    for _ in range(len(_slots)):
        slot = _slots[_rr % len(_slots)]
        _rr += 1
        if slot["cooldown_until"] <= now:
            return slot
    # ★ 全部都在冷卻中就直接放棄，不要硬送。
    #   舊版會回傳「最早解凍」的那把繼續打，結果是越被限流打得越兇：
    #   實測 30 秒輪詢下，7 個搭乘段被放大成 36 個到站請求（每條路線 6 次
    #   ＝ 2 個城市 × 3 把金鑰），把限流狀態一直維持住。
    return None


async def _get_token(slot: dict) -> str:
    """取得並快取單一金鑰組的 access token（有效期約 24 小時，必須快取）。"""
    now = time.time()
    if slot["token"] and now < slot["expires_at"]:
        return slot["token"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": slot["client_id"],
                "client_secret": slot["client_secret"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    slot["token"] = data["access_token"]
    slot["expires_at"] = now + data["expires_in"] - TOKEN_TTL_MARGIN
    return slot["token"]


# --------------------------------------------------------------------------
# 統一的 GET：所有 TDX 端點都走這裡，才有一致的輪替、冷卻與錯誤語意
# --------------------------------------------------------------------------


# 同時最多幾個 TDX 請求在飛。★ 這是不被限流的關鍵：
# 一次查詢會展開成數十個請求（每條公車要站序表＋到站，各兩個城市），
# 全部用 asyncio.gather 一次射出去必定觸發 429。實測不節流時單次查詢
# 打了 78 個請求並全部被擋。
_MAX_CONCURRENCY = 2
_sem: asyncio.Semaphore | None = None

# 請求之間的最小間隔。★ 光有並發上限不夠：TDX 看的是「瞬間突發率」而不是
# 平均值。實測單次輪詢的 13 個請求會在 2 秒內打完 = 6.5 req/s，即使 30 秒
# 平均只有 0.43 req/s 一樣被擋。把請求攤平在時間軸上才是有效的。
_MIN_REQUEST_GAP = 0.35
_last_request_at = 0.0
_pace_lock: asyncio.Lock | None = None


async def _pace() -> None:
    """確保兩個請求之間至少隔 _MIN_REQUEST_GAP 秒。"""
    global _last_request_at, _pace_lock
    if _pace_lock is None:
        _pace_lock = asyncio.Lock()
    async with _pace_lock:
        wait = _last_request_at + _MIN_REQUEST_GAP - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


def _semaphore() -> asyncio.Semaphore:
    # 延遲建立：Semaphore 要綁在實際執行的 event loop 上
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    return _sem


async def _get(url: str, params: dict | None = None) -> tuple[list | dict | None, str]:
    """回傳 (資料, 狀態)。狀態為 "ok" / "rate_limited" / "error"。

    ★ 429 一定要能被上層看見。舊版把非 200 一律 continue 吃掉，
      導致「被限流」與「這站真的沒車」在畫面上完全一樣，Demo 時無法除錯。
    """
    if not _slots:
        return None, "error"

    # ★ 不能用 httpx 的 params= 傳查詢字串：url 本身已經帶 query 時
    #   （例如 OData 的 $filter），httpx 會整個取代掉而不是合併。
    #   實測症狀是 $filter 被丟掉、回傳整份 14,641 筆資料，
    #   然後取第一筆得到完全不相干的票價，而且沒有任何錯誤訊息。
    merged = dict(params or {})
    merged.setdefault("$format", "JSON")
    sep = "&" if "?" in url else "?"
    url = url + sep + urlencode(merged)
    params = None
    saw_rate_limit = False

    # 每組金鑰各試一次；被 429 就換下一組
    for attempt in range(len(_slots)):
        slot = _pick_slot()
        if slot is None:
            # 所有金鑰都在冷卻 —— 這是限流造成的，要如實回報，
            # 不能報成一般錯誤，否則畫面會顯示「班表推估」而不是「查詢受限」
            saw_rate_limit = True
            break
        try:
            token = await _get_token(slot)
            async with _semaphore():
                await _pace()
                if attempt:
                    # 已經被擋過一次，稍微退避再換金鑰重試
                    await asyncio.sleep(0.4 * attempt)
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        url, headers={"authorization": f"Bearer {token}"}
                    )
        except Exception:
            continue

        if resp.status_code == 200:
            try:
                return resp.json(), "ok"
            except Exception:
                return None, "error"

        if resp.status_code == 429:
            saw_rate_limit = True
            slot["cooldown_until"] = time.time() + RATE_LIMIT_COOLDOWN
            continue

        if resp.status_code == 401:
            # token 可能過期，清掉重來一次
            slot["token"] = None
            continue

    return None, ("rate_limited" if saw_rate_limit else "error")


# --------------------------------------------------------------------------
# 快取 + 併發合流
# --------------------------------------------------------------------------

_cache: dict[str, tuple[float, object, str]] = {}  # key -> (存入時間, 資料, 狀態)
_inflight: dict[str, asyncio.Task] = {}

# 失敗也要短暫快取，否則被限流的請求會在下一次查詢立刻全部重試，
# 形成雪崩：實測「熱快取」那輪反而比冷啟動多打 15 個請求就是這個原因。
NEGATIVE_TTL = 25

# 靜態資料（站序表、站點清單）落地到磁碟。這是降低請求量最有效的一招——
# TDX 的限流很緊（實測單金鑰每 0.5 秒一次仍有一半被擋），而這些資料
# 幾個月才變一次，沒有理由每次重啟都重抓。
_DISK_DIR = Path(__file__).parent / "fixtures" / "cache"


def _disk_read(name: str, ttl: float):
    try:
        p = _DISK_DIR / f"{name}.json"
        if not p.exists() or time.time() - p.stat().st_mtime > ttl:
            return None
        import json

        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _disk_write(name: str, data) -> None:
    try:
        import json

        _DISK_DIR.mkdir(parents=True, exist_ok=True)
        (_DISK_DIR / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


async def _cached(key: str, ttl: float, coro_factory):
    """同一個 key 的併發查詢共用一次 HTTP。

    舊版沒有這層，六個方案併發查同一條路線時，因為誰都還沒寫進快取，
    會重複打同樣的請求（實測 919 被查了兩次），是踩到限流的主因之一。
    """
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], hit[2]

    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(coro_factory())
        _inflight[key] = task
        try:
            data, status = await task
        finally:
            _inflight.pop(key, None)
        # 成功用正常 TTL；失敗用短 TTL —— 失敗完全不快取會造成重試雪崩
        _cache[key] = (time.time(), data, status) if status == "ok" else (
            time.time() - ttl + NEGATIVE_TTL,
            data,
            status,
        )
        return data, status

    return await task


# --------------------------------------------------------------------------
# 公車即時到站
# --------------------------------------------------------------------------


async def _fetch_eta(route_name: str) -> tuple[list[dict], str]:
    """查 CITIES 兩個城市的即時到站並合併。回傳 (rows, 狀態)。"""

    async def fetch():
        rows: list[dict] = []
        statuses: list[str] = []
        # 循序而非併發，而且拿到資料就停：大部分路線只屬於其中一個城市，
        # 每次都查兩個等於白白多打一倍請求。
        for city in CITIES:
            data, status = await _get(ETA_URL.format(city=city, route=route_name))
            statuses.append(status)
            if status == "ok" and isinstance(data, list) and data:
                rows.extend(data)
                break
        if rows:
            return rows, "ok"
        if "rate_limited" in statuses:
            return [], "rate_limited"
        return [], "ok" if "ok" in statuses else "error"

    return await _cached(f"eta:{route_name}", ETA_CACHE_TTL, fetch)


# --------------------------------------------------------------------------
# 站名比對（仍保留給沒有座標可用的情境）
# --------------------------------------------------------------------------


def _clean(name: str) -> str:
    return name[:-1] if name.endswith("站") else name


def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)  # 全形轉半形
    name = re.sub(r"[（(].*?[）)]", "", name)  # 去除括號內容
    return name


def _match_stop(google_name: str, tdx_name: str) -> bool:
    """站名比對——依序嘗試，成功即停（README §6）。

    注意：NFKC 不處理異體字，「臺」不會被正規化成「台」，所以
    「台北車站」對「臺北車站(忠孝)」仍然會失敗。主要的比對路徑已改成
    用座標找最近站（見 geo.py），這裡只是沒有座標時的備援。
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
        查到即時資料        -> (秒數, "即時")
        這站目前沒有班次     -> (None, "無班次")
        末班已過或未營運     -> (None, "末班已過")
        被 TDX 限流         -> (None, "查詢受限")
        查無路線或其他錯誤   -> (None, "班表推估")

    ★ 這個函式絕對不能拋例外。
    """
    try:
        rows, status = await _fetch_eta(route_name)

        if status == "rate_limited":
            return None, SRC_RATE_LIMITED
        if not rows:
            return None, SRC_SCHEDULE

        for row in rows:
            # TDX 的 RouteName 路徑參數是前綴模糊比對，查「624」會連「624綠野香坡」
            # 都回傳，這裡一定要精確比對路線名，否則會抓到別條路線的到站時間。
            if row.get("RouteName", {}).get("Zh_tw", "") != route_name:
                continue

            if not _match_stop(stop_name, row.get("StopName", {}).get("Zh_tw", "")):
                continue

            st = row.get("StopStatus")
            if st in (STATUS_LAST_TRIP_PASSED, STATUS_NOT_IN_SERVICE):
                return None, SRC_LAST_PASSED
            if st == STATUS_NORMAL and row.get("EstimateTime") is not None:
                return row["EstimateTime"], SRC_LIVE
            # 查得到這一站，但沒有可用的到站時間 —— 這就是「這站真的沒車」
            return None, SRC_NO_SERVICE

        return None, SRC_SCHEDULE
    except Exception:
        return None, SRC_SCHEDULE


# --------------------------------------------------------------------------
# 座標比對：用 Google 給的站點座標找最近的 TDX 站點
#
# 為什麼不用站名：TDX 是「臺北」、Google 是「台北」，異體字讓字串比對永遠失敗，
# 而 NFKC 正規化不處理異體字。座標沒有這個問題。
# --------------------------------------------------------------------------

import math  # noqa: E402

NEAREST_LIMIT_M = 400.0  # 一般用途：超過這個距離就視為找不到，不要硬配

# 方向判定專用的放寬上限。實測 756 的返程不停 Google 說的「捷運北門站」，
# 起站是 663m 外的「臺北車站(承德)」——總站附近的上車點常常隔一條街。
# 放寬距離是安全的，因為真正的安全網是站序檢查（上車序必須小於下車序），
# 那個檢查會擋掉反方向，距離只是用來在同一條路線上定位是哪一站。
DIRECTION_LIMIT_M = 900.0


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearest(pos: dict | None, items: list[dict], get_pos, limit_m=NEAREST_LIMIT_M):
    """從 items 找離 pos 最近的一筆。回傳 (項目, 距離) 或 (None, None)。"""
    if not pos or not items:
        return None, None
    best, best_d = None, None
    for it in items:
        p = get_pos(it)
        if not p:
            continue
        d = _haversine_m(pos["lat"], pos["lng"], p[0], p[1])
        if best_d is None or d < best_d:
            best, best_d = it, d
    if best_d is None or best_d > limit_m:
        return None, None
    return best, best_d


def _nearest_all(pos: dict | None, items: list[dict], get_pos, limit_m=NEAREST_LIMIT_M):
    """回傳所有在距離上限內的項目，由近而遠排序。

    捷運需要這個而不是單一最近站：同一個「台北車站」在板南線是 BL12、
    在淡水信義線是 R10，座標幾乎重疊。只取最近的一個會選到錯的線。
    """
    if not pos or not items:
        return []
    out = []
    for it in items:
        p = get_pos(it)
        if not p:
            continue
        d = _haversine_m(pos["lat"], pos["lng"], p[0], p[1])
        if d <= limit_m:
            out.append((d, it))
    out.sort(key=lambda x: x[0])
    return [it for _d, it in out]


def _station_pos(st: dict):
    p = st.get("StationPosition") or {}
    lat, lng = p.get("PositionLat"), p.get("PositionLon")
    return (lat, lng) if lat is not None and lng is not None else None


async def _static(disk_name: str, cache_key: str, fetch) -> list[dict]:
    """靜態資料的三層快取：記憶體 → 磁碟 → TDX。"""
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < STATIC_CACHE_TTL and hit[2] == "ok":
        return hit[1] or []

    on_disk = _disk_read(disk_name, STATIC_CACHE_TTL)
    if on_disk:
        _cache[cache_key] = (time.time(), on_disk, "ok")
        return on_disk

    rows, status = await _cached(cache_key, STATIC_CACHE_TTL, fetch)
    if status == "ok" and rows:
        _disk_write(disk_name, rows)
    return rows or []


async def _station_list(url: str, key: str, cache_key: str) -> list[dict]:
    """站點清單是靜態資料，記憶體＋磁碟快取一天。"""

    async def fetch():
        data, status = await _get(url)
        if status != "ok":
            return [], status
        lst = data if isinstance(data, list) else (data or {}).get(key, [])
        return lst, "ok"

    return await _static(cache_key.replace(":", "_"), cache_key, fetch)


async def tra_stations() -> list[dict]:
    return await _station_list(
        f"{BASE}/v3/Rail/TRA/Station", "Stations", "static:tra_stations"
    )


async def metro_stations() -> list[dict]:
    return await _station_list(
        f"{BASE}/v2/Rail/Metro/Station/TRTC", "Stations", "static:metro_stations"
    )


# --------------------------------------------------------------------------
# 需求 4：公車方向判定
# --------------------------------------------------------------------------


async def _stop_of_route(route_name: str) -> list[dict]:
    """路線的站牌與站序（含方向），靜態資料快取一天。"""

    async def fetch():
        rows: list[dict] = []
        for city in CITIES:
            data, status = await _get(
                f"{BASE}/v2/Bus/StopOfRoute/City/{city}/{route_name}"
            )
            if status == "ok" and isinstance(data, list) and data:
                rows.extend(data)
                break  # 同上：拿到就停，不要兩個城市都打
        return rows, "ok" if rows else "error"

    # 站序表幾個月才變一次，落地到磁碟後重啟也不用重抓
    safe = re.sub(r"[^\w一-鿿-]", "_", route_name)
    return await _static(f"sor_{safe}", f"sor:{route_name}", fetch)


async def resolve_boarding(
    route_name: str, from_pos: dict | None, to_pos: dict | None
) -> tuple[int | None, dict | None]:
    """判定該搭哪個方向、以及在 TDX 眼中的上車站（需求 4）。

    回傳 (Direction, 上車站)。判不出來時回 (None, None)，不要猜。

    做法：對每個 (SubRoute, Direction) 的站序表，用座標找出上車站與下車站
    分別對應到哪一站，只有「上車站序 < 下車站序」的方向才是對的。

    不做這件事的話會抓到反方向的車，預估時間完全錯誤——反向車可能剛過站，
    ETA 顯示 2 分鐘，但那台車是往反方向開的。

    ★ 一併回傳上車站，是因為 Google 的站名未必在該方向的站序表上。實測 756：
      Google 說在「捷運北門站」上車，但返程根本不停那站，實際起站是
      663m 外的「臺北車站(承德)」。用 TDX 自己的站（StopUID 精確比對）
      才查得到正確方向的到站時間。
    """
    if not from_pos or not to_pos:
        return None, None

    def stop_pos(s):
        p = s.get("StopPosition") or {}
        lat, lng = p.get("PositionLat"), p.get("PositionLon")
        return (lat, lng) if lat is not None and lng is not None else None

    best, best_stop, best_score = None, None, None
    for rec in await _stop_of_route(route_name):
        if rec.get("RouteName", {}).get("Zh_tw") != route_name:
            continue
        stops = rec.get("Stops") or []
        a, da = _nearest(from_pos, stops, stop_pos, DIRECTION_LIMIT_M)
        b, db = _nearest(to_pos, stops, stop_pos, DIRECTION_LIMIT_M)
        if a is None or b is None:
            continue
        if a.get("StopSequence", 0) >= b.get("StopSequence", 0):
            continue  # 上車站排在下車站後面 → 這是反方向，直接排除
        score = da + db
        if best_score is None or score < best_score:
            best, best_stop, best_score = rec, a, score

    if best is None:
        return None, None
    return best.get("Direction"), best_stop


async def get_eta_directional(
    route_name: str, stop_name: str, from_pos=None, to_pos=None, resolved=None
) -> tuple[int | None, str]:
    """帶方向判定的公車到站查詢（需求 4 + 7）。

    先用座標判方向，再用座標（而非站名）鎖定上車站，兩者都失敗才退回站名比對。
    """
    try:
        # resolved 讓呼叫端可以只解析一次方向，避免重複計算
        direction, boarding = (
            resolved
            if resolved is not None
            else await resolve_boarding(route_name, from_pos, to_pos)
        )
        rows, status = await _fetch_eta(route_name)

        if status == "rate_limited":
            return None, SRC_RATE_LIMITED
        if not rows:
            return None, SRC_SCHEDULE

        # 精確比對路線名：查「624」TDX 會連「624綠野香坡」一起回傳
        cand = [r for r in rows if r.get("RouteName", {}).get("Zh_tw") == route_name]
        if direction is not None:
            cand = [r for r in cand if r.get("Direction") == direction]
        if not cand:
            return None, SRC_SCHEDULE

        match = []
        if boarding is not None:
            # 首選：用 TDX 自己的 StopUID 精確比對，完全不碰站名字串
            uid = boarding.get("StopUID")
            match = [r for r in cand if r.get("StopUID") == uid]
        if not match:
            # 備援：沒判出方向時才退回站名比對（會受異體字影響）
            match = [
                r
                for r in cand
                if _match_stop(stop_name, r.get("StopName", {}).get("Zh_tw", ""))
            ]

        if not match:
            return None, SRC_SCHEDULE

        row = match[0]
        st = row.get("StopStatus")
        if st in (STATUS_LAST_TRIP_PASSED, STATUS_NOT_IN_SERVICE):
            return None, SRC_LAST_PASSED
        if st == STATUS_NORMAL and row.get("EstimateTime") is not None:
            return row["EstimateTime"], SRC_LIVE
        return None, SRC_NO_SERVICE
    except Exception:
        return None, SRC_SCHEDULE


# --------------------------------------------------------------------------
# 需求 7：實際車輛位置（RealTimeNearStop）
# --------------------------------------------------------------------------


async def _near_stop(route_name: str) -> tuple[list[dict], str]:
    """該路線目前有哪些車、各在第幾站。A2EventType：0 進站、1 離站。"""

    async def fetch():
        for city in CITIES:
            data, status = await _get(
                f"{BASE}/v2/Bus/RealTimeNearStop/City/{city}/{route_name}"
            )
            if status == "ok" and isinstance(data, list) and data:
                return data, "ok"
            if status == "rate_limited":
                return [], "rate_limited"
        return [], "ok"

    return await _cached(f"near:{route_name}", NEAR_STOP_CACHE_TTL, fetch)


async def approaching_bus(
    route_name: str, direction: int | None, boarding_seq: int | None
) -> dict | None:
    """找出「還沒過我這站、且離我最近」的那台車（需求 7）。

    ETA 是 TDX 推估的數字；這裡是真的有一台車在路上的證據。兩者互為佐證：
    ETA 說 5 分鐘但根本找不到車，那個數字就不可信。
    """
    try:
        if direction is None or boarding_seq is None:
            return None
        rows, status = await _near_stop(route_name)
        if status != "ok" or not rows:
            return None

        best = None
        for r in rows:
            if r.get("RouteName", {}).get("Zh_tw") != route_name:
                continue
            if r.get("Direction") != direction:
                continue
            seq = r.get("StopSequence")
            if seq is None or seq > boarding_seq:
                continue  # 已經過站了，這台車搭不到
            if best is None or seq > best.get("StopSequence", -1):
                best = r  # 越接近我的站越好

        if best is None:
            return None
        return {
            "plate": best.get("PlateNumb", ""),
            "stopsAway": boarding_seq - best.get("StopSequence", boarding_seq),
            "gpsTime": best.get("GPSTime", ""),
        }
    except Exception:
        return None


# --------------------------------------------------------------------------
# 需求 5：台鐵誤點
# --------------------------------------------------------------------------


async def tra_delay(from_pos: dict | None) -> tuple[int, str, str]:
    """回傳 (誤點秒數, 來源, 月台)。查不到就回 (0, "班表推估", "")。

    依你的決定：Google 當基準，TDX 只做加減——誤點 6 分就 +360 秒。
    """
    try:
        station, _d = _nearest(from_pos, await tra_stations(), _station_pos)
        if station is None:
            return 0, SRC_SCHEDULE, ""

        sid = station.get("StationID")

        async def fetch():
            data, status = await _get(
                f"{BASE}/v3/Rail/TRA/StationLiveBoard/Station/{sid}"
            )
            if status != "ok":
                return [], status
            return (data or {}).get("StationLiveBoards", []), "ok"

        boards, status = await _cached(f"tra:{sid}", ETA_CACHE_TTL, fetch)
        if status == "rate_limited":
            return 0, SRC_RATE_LIMITED, ""
        if not boards:
            return 0, SRC_NO_SERVICE, ""

        # DelayTime 單位是分鐘。取最近一班（誤點最具代表性的那筆）
        board = boards[0]
        delay_min = board.get("DelayTime") or 0
        return int(delay_min) * 60, SRC_LIVE, str(board.get("Platform") or "")
    except Exception:
        return 0, SRC_SCHEDULE, ""


# --------------------------------------------------------------------------
# 需求 6：捷運即時到站
# --------------------------------------------------------------------------


async def metro_eta(
    from_pos: dict | None, line_name: str = "", headsign: str = ""
) -> tuple[int | None, str]:
    """台北捷運某站的即時到站秒數（需求 6）。

    捷運班距短，價值主要在等車時間而不是行駛時間。
    """
    try:
        # 同一個站名在不同路線有不同 StationID，全部收進來再用線名篩
        stations = _nearest_all(from_pos, await metro_stations(), _station_pos)
        if not stations:
            return None, SRC_SCHEDULE

        async def fetch():
            data, status = await _get(f"{BASE}/v2/Rail/Metro/LiveBoard/TRTC")
            if status != "ok":
                return [], status
            return (data if isinstance(data, list) else []), "ok"

        boards, status = await _cached("metro:trtc", ETA_CACHE_TTL, fetch)
        if status == "rate_limited":
            return None, SRC_RATE_LIMITED
        if not boards:
            return None, SRC_NO_SERVICE

        sids = {s.get("StationID") for s in stations}
        rows = [b for b in boards if b.get("StationID") in sids]
        if line_name:
            same = [b for b in rows if b.get("LineName", {}).get("Zh_tw") == line_name]
            rows = same or rows
        if headsign:
            # headsign 例如「往淡水站」，TripHeadSign 例如「往淡水」
            key = headsign.replace("往", "").replace("站", "").strip()
            same = [b for b in rows if key and key in str(b.get("TripHeadSign", ""))]
            rows = same or rows
        if not rows:
            return None, SRC_NO_SERVICE

        eta = min(int(b.get("EstimateTime") or 0) for b in rows)
        return eta, SRC_LIVE
    except Exception:
        return None, SRC_SCHEDULE


# --------------------------------------------------------------------------
# 給 main.py 的統一入口：一段行程要向 TDX 問什麼，都在這裡決定
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 官方票價（Google 沒有 transitFare 時的備援）
# --------------------------------------------------------------------------

FARE_CACHE_TTL = 3600  # 票價一小時才可能變，快取久一點

# 台鐵票種代碼。TDX 的 TicketType 是中文字串（成自／成莒／成復／成普），
# 不是數字，跟捷運與高鐵的結構不一樣。
TRA_ADULT_TICKET = {
    "自強": "成自", "普悠瑪": "成自", "太魯閣": "成自",
    "tze-chiang": "成自", "emu3000": "成自",
    "莒光": "成莒", "chu-kuang": "成莒",
    "復興": "成復",
    "區間": "成普", "普通": "成普", "local train": "成普",
}


def _normalize_station(name: str) -> str:
    """站名正規化，用來跨資料源比對。

    Google 說「捷運淡水站」，TDX 說「淡水」；Google 說「台北」，TDX 說「臺北」。
    NFKC 不處理異體字，所以臺→台要自己換。
    """
    s = unicodedata.normalize("NFKC", str(name or "")).strip()
    s = s.replace("臺", "台")
    s = re.sub(r"[（(].*?[）)]", "", s)  # 去掉「台北車站(忠孝)」的括號
    s = re.sub(r"^(捷運|台鐵|高鐵)", "", s)
    s = re.sub(r"(車站|站)$", "", s)
    return re.sub(r"\s+", "", s)


async def _station_id_index(kind: str) -> dict:
    """{正規化站名: StationID}。用既有的站點清單建，不額外打 API。"""

    async def build():
        rows = await (tra_stations() if kind == "TRA" else metro_stations())
        idx = {}
        for st in rows:
            sid = st.get("StationID")
            nm = _normalize_station((st.get("StationName") or {}).get("Zh_tw", ""))
            if sid and nm:
                idx.setdefault(nm, sid)
        return idx, ("ok" if idx else "error")

    idx, _ = await _cached(f"stnidx:{kind}", STATIC_CACHE_TTL, build)
    return idx or {}


def _pick_fare(fares: list, mode: str, route_name: str) -> int | float | None:
    """從 Fares 陣列挑出一般成人票。挑不到回 None。"""
    if not fares:
        return None

    if mode == "TRAIN":
        # 車種決定票種。判不出車種就回 None —— 不能假設成區間車，
        # 自強票價比區間貴一倍以上，猜錯比沒有更糟。
        low = str(route_name or "").lower()
        code = next((v for k, v in TRA_ADULT_TICKET.items() if k in low), None)
        if code is None:
            return None
        for f in fares:
            if f.get("TicketType") == code:
                return f.get("Price")
        return None

    for f in fares:
        if f.get("TicketType") != 1 or f.get("FareClass") != 1:
            continue
        if mode == "HSR" and f.get("CabinClass") != 1:
            continue  # 高鐵要標準車廂，不是商務艙
        return f.get("Price")
    return None


async def get_fare(
    mode: str, route_name: str, from_stop: str, to_stop: str
) -> tuple[int | float | None, int | float | None]:
    """查官方票價，回傳 (票價, 悠遊卡價)。

    ★ 任何錯誤都回 (None, None)，絕不拋例外——與 get_eta 相同的契約，
      組裝層才不用寫 try/except，也不會讓整個 /api/plans 失敗。

    公車一律回 (None, None)：TDX 沒有可靠的分段票價資料，
    而台北公車是分段收費，猜不得。
    """
    try:
        if mode not in ("METRO", "TRAIN", "HSR"):
            return None, None

        a, b = _normalize_station(from_stop), _normalize_station(to_stop)
        if not a or not b or a == b:
            return None, None

        if mode == "METRO":
            idx = await _station_id_index("METRO")
            oid, did = idx.get(a), idx.get(b)
            if not oid or not did:
                return None, None
            # 用 StationID 精確過濾，不用 contains——「台北」用 contains
            # 會配到「台北小巨蛋」，而且 TDX 端是「臺北」根本配不到。
            paths = [
                f"{BASE}/v2/Rail/Metro/ODFare/{op}?"
                f"$filter=OriginStationID eq '{oid}' and DestinationStationID eq '{did}'"
                for op in ("TRTC", "NTMC")
            ]
        elif mode == "TRAIN":
            idx = await _station_id_index("TRA")
            oid, did = idx.get(a), idx.get(b)
            if not oid or not did:
                return None, None
            paths = [
                f"{BASE}/v2/Rail/TRA/ODFare?"
                f"$filter=OriginStationID eq '{oid}' and DestinationStationID eq '{did}'"
            ]
        else:  # HSR
            oid = did = None
            paths = [f"{BASE}/v2/Rail/THSR/ODFare"]

        async def fetch():
            for url in paths:
                data, status = await _get(url)
                if status == "rate_limited":
                    return None, "rate_limited"
                if status == "ok" and isinstance(data, list) and data:
                    return data, "ok"
            return None, "ok"

        key = f"fare:{mode}:{oid or a}:{did or b}"
        rows, status = await _cached(key, FARE_CACHE_TTL, fetch)
        if status != "ok" or not rows:
            return None, None

        if mode == "HSR":
            # 高鐵資料小（132 筆），整份抓回來後用正規化站名精確比對
            rows = [
                r
                for r in rows
                if _normalize_station((r.get("OriginStationName") or {}).get("Zh_tw", "")) == a
                and _normalize_station((r.get("DestinationStationName") or {}).get("Zh_tw", "")) == b
            ]
            if not rows:
                return None, None

        price = _pick_fare(rows[0].get("Fares") or [], mode, route_name)
        if price is None:
            return None, None
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None, None
        if price < 0:
            return None, None
        # TDX 只給單一票價，沒有分悠遊卡價，所以 icFare 維持 None
        return (int(price) if price.is_integer() else price), None
    except Exception:
        return None, None


async def enrich_ride(step: dict) -> dict:
    """查一個 RIDE 步驟的即時資訊。

    回傳 {waitSeconds, waitSource, adjustSeconds, platform}
      waitSeconds   等車秒數（None 代表查不到）
      adjustSeconds 對 Google 行駛時間的修正量（台鐵誤點），正數代表更慢
      platform      月台（前端已會讀 step.platform）

    ★ 絕不拋例外，與 get_eta 相同的契約。
    """
    mode = step.get("mode")
    from_pos, to_pos = step.get("fromStopPos"), step.get("toStopPos")
    out = {
        "waitSeconds": None,
        "waitSource": SRC_SCHEDULE,
        "adjustSeconds": 0,
        "platform": "",
        "vehicle": None,  # 需求 7：實際在路上的那台車（車牌、還有幾站）
    }

    try:
        if mode == "BUS":
            route = step.get("routeName", "")
            # 方向只解析一次，到站查詢與車輛查詢共用（需求 4 + 7）
            resolved = await resolve_boarding(route, from_pos, to_pos)
            direction, boarding = resolved

            secs, src = await get_eta_directional(
                route, step.get("fromStop", ""), from_pos, to_pos, resolved=resolved
            )

            # 需求 7：用實際車輛位置佐證 ETA
            bus = await approaching_bus(
                route, direction, (boarding or {}).get("StopSequence")
            )
            out["vehicle"] = bus
            if secs is not None and bus is None:
                # ETA 有數字但路上找不到對應方向的車，可信度不足
                out["waitSeconds"], out["waitSource"] = secs, SRC_NO_SERVICE
            else:
                out["waitSeconds"], out["waitSource"] = secs, src

        elif mode == "TRAIN":
            adjust, src, platform = await tra_delay(from_pos)
            out["adjustSeconds"], out["waitSource"], out["platform"] = adjust, src, platform

        elif mode == "METRO":
            secs, src = await metro_eta(
                from_pos, step.get("routeName", ""), step.get("headsign", "")
            )
            out["waitSeconds"], out["waitSource"] = secs, src
        # HSR 沒有對應的即時端點，維持班表推估
    except Exception:
        pass

    return out


if __name__ == "__main__":

    async def _main() -> None:
        print(f"讀到 {CREDENTIAL_COUNT} 組金鑰")
        if not CREDENTIAL_COUNT:
            print("★ 沒有金鑰，檢查 .env 的 TDX_CLIENT_ID_1/2/3")
            return
        for i, slot in enumerate(_slots, 1):
            token = await _get_token(slot)
            print(f"  金鑰 {i}: token 前 20 字元 {token[:20]}…")
        print("get_eta('624', '福州街') =", await get_eta("624", "福州街"))

    asyncio.run(_main())
