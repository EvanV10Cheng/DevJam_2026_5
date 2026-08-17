"""大台北即時轉乘 — 組裝層。

★ 擁有者：P4。P1/P2/P3 請勿修改本檔（README §8）。

核心邏輯只有一句話：Google 找候選 → TDX 補即時等待 → 依實際總時間重新排序。
若 ranked[0] 不是 Google 的第一名，reordered 為 true——那就是本專案成立的證據。
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


async def _wait_for(plan: dict) -> tuple[int | None, str]:
    """查這個方案第一段搭乘的等待時間。

    只有公車查得到即時（TDX 的 EstimatedTimeOfArrival 只涵蓋公車），
    捷運／台鐵／高鐵一律走班表推估。
    """
    ride = _first_ride(plan)
    if ride is None or ride.get("mode") != "BUS":
        return None, "班表推估"
    return await tdx_client.get_eta(ride.get("routeName", ""), ride.get("fromStop", ""))


@app.get("/api/plans")
async def plans(origin: str = Query(...), destination: str = Query(...)):
    # ① Google 找候選
    candidates = await google_client.get_routes(origin, destination)

    # ② 併發查每個方案的等待時間（不是序列，3 個方案就是 3 倍差距）
    waits = await asyncio.gather(*(_wait_for(p) for p in candidates))

    # ③ 補上等待相關欄位。★ 所有欄位一律存在，就算值是 null（README §3）
    for plan, (secs, src) in zip(candidates, waits):
        plan["waitSeconds"] = secs
        plan["waitSource"] = src
        plan["realSeconds"] = plan.get("totalSeconds", 0) + (secs or 0)
        plan["isLive"] = src == "即時"

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
