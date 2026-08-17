"""大台北即時轉乘 — 組裝層。

★ 擁有者：P4。P1/P2/P3 請勿修改本檔（README §8）。

核心邏輯只有一句話：Google 找候選 → TDX 補即時等待 → 依實際總時間重新排序。
若 ranked[0] 不是 Google 的第一名，reordered 為 true——那就是本專案成立的證據。

★ 本機啟動一定要帶 --env-file，否則金鑰讀不到：

    uvicorn main:app --port 8080 --env-file .env

  google_client.py 與 tdx_client.py 在 import 時就用 os.getenv() 讀金鑰，
  沒有任何程式會自動載入 .env。少了 --env-file 的話兩邊的金鑰都是空字串，
  症狀是 Google 回 403、TDX 回 401，很容易誤判成金鑰申請錯了。
  （--env-file 是 uvicorn[standard] 內建功能，不需要額外裝套件。）

  Cloud Run 上不需要這個參數：--set-secrets 會直接注入成真的環境變數。
"""

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import google_client
import tdx_client

# 前端自動更新的間隔（秒）。TDX 的即時到站快取是 20 秒，所以 30 秒輪詢
# 每次都拿得到新資料；Google 那層有 300 秒快取擋著，不會被輪詢燒穿配額。
POLL_INTERVAL_SEC = 60

app = FastAPI(title="大台北即時轉乘")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"ok": True}



def _first_ride(plan: dict) -> dict | None:
    """取出第一個 RIDE step。全程步行的方案會是 None。"""
    for step in plan.get("steps", []):
        if step.get("type") == "RIDE":
            return step
    return None


def _ride_key(step: dict) -> tuple:
    """一個搭乘段的去重鍵。

    多條候選路線常共用同一班車，不去重的話同一段會被重複查，
    這是踩到 TDX 限流的主因（實測單次查詢曾打 12 個並發請求）。
    座標放進鍵裡，因為同名站牌在不同位置是不同的上車點。
    """
    pos = step.get("fromStopPos") or {}
    return (
        step.get("mode", ""),
        step.get("routeName", ""),
        round(pos.get("lat", 0.0), 5),
        round(pos.get("lng", 0.0), 5),
    )


def _plan_signature(plan: dict) -> tuple:
    """方案的「實質內容」簽章：搭哪幾班車、從哪站到哪站。

    步行時間與 Google 的時間估計刻意不納入——那正是重複方案之間唯一的差別。
    """
    return tuple(
        (s.get("mode", ""), s.get("routeName", ""), s.get("fromStop", ""), s.get("toStop", ""))
        for s in plan.get("steps", [])
        if s.get("type") == "RIDE"
    )


def _dedupe_plans(candidates: list[dict]) -> list[dict]:
    """把實質相同的方案合併，每種簽章只留最快的一條。

    Google 的 computeAlternativeRoutes 會回好幾條實質一樣的路線——實測
    「台北車站→淡水」回 6 條，其中 4 條連 encoded polyline 都完全相同，
    另外幾條只差 Google 對時間的估計（45/46/46/47/48 分鐘）。
    對使用者來說那就是同一個搭法，排成五張卡片只是雜訊。

    放在查 TDX 之前，順便省掉重複方案的查詢。同簽章代表搭同樣的車，
    TDX 查出來的等車時間也會一樣，所以用 totalSeconds 挑最快的即可。
    """
    best: dict[tuple, dict] = {}
    for plan in candidates:
        sig = _plan_signature(plan)
        cur = best.get(sig)
        if cur is None or plan.get("totalSeconds", 0) < cur.get("totalSeconds", 0):
            best[sig] = plan
    return list(best.values())


def _fare_key(step: dict) -> tuple:
    """票價查詢的去重鍵。同一段車在多個方案裡只查一次。"""
    return (
        step.get("mode", ""),
        step.get("routeName", ""),
        step.get("fromStop", ""),
        step.get("toStop", ""),
    )


async def _fill_fares(candidates: list[dict]) -> None:
    """填入 plan["fare"] 與 plan["icFare"]。

    優先順序：
      1. Google 的 transitFare（整條路線的總價，最可靠）
      2. 逐段查 TDX 官方票價再加總

    ★ 任一段查不到票價，整個方案的 fare 就是 None。
      不能把未知的那段當成免費——那會讓一條「其實更貴」的路線
      在「票價較低」排序裡跑到第一名，比沒有票價還糟。
    """
    need = [p for p in candidates if p.get("fare") is None]
    if not need:
        return

    # 去重後一次查完，沿用與 enrich_ride 相同的併發模式
    by_key: dict[tuple, dict] = {}
    for plan in need:
        for step in plan.get("steps", []):
            if step.get("type") == "RIDE":
                by_key.setdefault(_fare_key(step), step)

    if by_key:
        keys = list(by_key)
        results = await asyncio.gather(
            *(
                tdx_client.get_fare(
                    by_key[k].get("mode", ""),
                    by_key[k].get("routeName", ""),
                    by_key[k].get("fromStop", ""),
                    by_key[k].get("toStop", ""),
                )
                for k in keys
            )
        )
        lookup = dict(zip(keys, results))
    else:
        lookup = {}

    for plan in need:
        total = 0.0
        complete = False
        for step in plan.get("steps", []):
            if step.get("type") != "RIDE":
                continue
            fare, _ic = lookup.get(_fare_key(step), (None, None))
            if fare is None:
                total, complete = 0.0, False
                break  # 有一段不知道價錢，整個方案就無法給總價
            total += fare
            complete = True
        plan["fare"] = (int(total) if float(total).is_integer() else total) if complete else None
        # TDX 與 Google 都沒有悠遊卡價，不自行推算
        plan.setdefault("icFare", None)


@app.get("/api/plans")
async def plans(origin: str = Query(...), destination: str = Query(...)):
    # ① Google 找候選，並合併實質重複的方案
    candidates = _dedupe_plans(await google_client.get_routes(origin, destination))

    # ② 收集所有方案的所有搭乘段，去重後一次查完
    rides = [s for p in candidates for s in p.get("steps", []) if s.get("type") == "RIDE"]
    by_key: dict[tuple, dict] = {}
    for step in rides:
        by_key.setdefault(_ride_key(step), step)

    keys = list(by_key)
    results = await asyncio.gather(*(tdx_client.enrich_ride(by_key[k]) for k in keys))
    lookup = dict(zip(keys, results))

    # ③ 把 TDX 的結果寫回每一段，再彙總成方案層的欄位
    for plan in candidates:
        first_wait, first_src, adjust_total = None, "班表推估", 0
        seen_first = False

        for step in plan.get("steps", []):
            if step.get("type") != "RIDE":
                continue
            info = lookup.get(_ride_key(step), {})
            # 前端已經會讀 step.waitSeconds 與 step.platform，直接填進去
            step["waitSeconds"] = info.get("waitSeconds")
            step["platform"] = info.get("platform", "")
            adjust_total += info.get("adjustSeconds", 0)
            if not seen_first:
                first_wait = info.get("waitSeconds")
                first_src = info.get("waitSource", "班表推估")
                seen_first = True

        # ★ 所有欄位一律存在，就算值是 null（README §3）
        plan["waitSeconds"] = first_wait
        plan["waitSource"] = first_src
        plan["isLive"] = first_src == "即時"

        # Google 當基準，TDX 只做修正：
        #   + 第一段的等車時間（Google 的 duration 不含等第一班車）
        #   + 各段的誤點修正（台鐵 DelayTime）
        # 轉乘段的等車時間「不」加總——Google 的行程規劃本來就已經含在內，
        # 再加一次會重複計算。那些數字仍會出現在 step.waitSeconds 供前端顯示。
        plan["realSeconds"] = (
            plan.get("totalSeconds", 0) + (first_wait or 0) + adjust_total
        )

    # ④ 票價。Google 的 transitFare 優先；沒有才逐段查 TDX 官方票價並加總。
    await _fill_fares(candidates)

    # ⑤ 依實際總時間重新排序
    ranked = sorted(candidates, key=lambda p: p["realSeconds"])
    reordered = bool(candidates) and ranked[0] is not candidates[0]

    # ⑥ 回傳。googleOrder 保留 Google 原始順序的 realSeconds，供前端對照
    return {
        "queryTime": int(time.time()),
        "plans": ranked,
        "googleOrder": [p["realSeconds"] for p in candidates],
        "reordered": reordered,
        # 輪詢間隔由後端決定，前端照做。配額吃緊時改這一個數字就能讓
        # 所有客戶端一起放慢，不用重新部署前端。
        "nextPollSec": POLL_INTERVAL_SEC,
    }


# 前端與 API 由同一個服務提供。★ 這樣部署後只有一個網址，
# 而且前端用相對路徑打 API，CORS 完全用不到（跨來源問題直接消失）。
# ★ 一定要放在檔案最後：掛在 / 的 StaticFiles 會吃掉所有路徑，
#   寫在 /api/plans 前面的話 API 會被它蓋掉，變成回傳網頁而不是 JSON。
_WEB_DIR = Path(__file__).parent / "web"
if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
