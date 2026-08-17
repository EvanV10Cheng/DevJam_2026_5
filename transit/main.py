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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

import google_client
import tdx_client

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

    # ④ 依實際總時間重新排序
    ranked = sorted(candidates, key=lambda p: p["realSeconds"])
    reordered = bool(candidates) and ranked[0] is not candidates[0]

    # ⑤ 回傳。googleOrder 保留 Google 原始順序的 realSeconds，供前端對照
    return {
        "queryTime": int(time.time()),
        "plans": ranked,
        "googleOrder": [p["realSeconds"] for p in candidates],
        "reordered": reordered,
    }
