"""自建轉乘子圖 + 時間相依最短路徑（方案 B）。

為什麼需要這個：現有架構只能把 TDX 疊在 Google 給的候選上，
永遠產生不出 Google 沒回傳的路徑。但台鐵／公車誤點會讓「原本接不上的
轉乘」變成接得上——那條路徑 Google 用靜態班表規劃時就排除了，
再怎麼疊即時資料也疊不出來。

範圍界定（刻意的取捨）：
  · 起點與終點沿用 Google 找到的上車站／下車站，不自己做地理編碼。
    等於問「Google 說要從這裡上車、那裡下車，有沒有更好的車輛組合？」
  · 子圖限制在起訖點的走廊範圍內，節點數控制在數百到一兩千。
  · 公車、捷運、台鐵都納入。原本只算公車時實測慘敗（三峽→板橋差 3.1 倍），
    因為 Google 用捷運而我們沒有——拿單一模式比多模式必輸。

★ 時間相依是核心：等待成本是「抵達該站時刻」的函數，不是固定值。
  20 分鐘後到轉乘站，等到的是不同班次。所以不能用一般 Dijkstra 的
  固定邊權，每次展開都要用當下的時刻去查下一班。
"""

from __future__ import annotations

import heapq
import math
from datetime import datetime

from static_data import StaticData, _haversine_m

WALK_SPEED_MPS = 1.25  # 步行速率，約 4.5 km/h
TRANSFER_WALK_M = 300  # 轉乘可接受的步行距離
TRANSFER_PENALTY_SEC = 300  # 每次轉乘的心理成本（README §1 的成本函數）
MAX_TRANSFERS = 3
MAX_RIDE_STOPS = 45  # 一段最多坐幾站，避免展開整條長途路線
CORRIDOR_PAD_M = 2000  # 走廊範圍向外擴張多少
# 節點上限。長程起訖（例如新店→三重相距 15 公里）走廊內有一萬八千個站牌，
# 上限訂太低會在還沒走到終點前就被截斷（實測 4/7 組因此找不到路徑）。
MAX_NODES = 30000
MAX_SETTLED = 40000

# 演算法要贏過 Google 最佳方案這個幅度才採用。
#
# ★ 為什麼需要門檻：行駛時間是用距離 ÷ 校準車速推的，校準樣本的離散度
#   高達 11–29 km/h。小幅領先很可能只是估計誤差，不是真的更快。
#   設 15%，讓只有明顯的差距才會被當成發現。
MIN_GAIN_RATIO = 0.85


class Corridor:
    """起訖點之間的空間範圍 + 落在其中的站牌的格網索引。

    不做這個限制的話，大台北 61,519 個站牌全丟進 Dijkstra 會慢到無法用。
    """

    CELL = 0.005  # 約 550 公尺一格

    def __init__(self, sd: StaticData, points: list[tuple[float, float]]):
        self.sd = sd
        lats = [p[0] for p in points]
        lngs = [p[1] for p in points]
        pad_lat = CORRIDOR_PAD_M / 111000
        pad_lng = CORRIDOR_PAD_M / (111000 * max(math.cos(math.radians(sum(lats) / len(lats))), 0.1))
        self.min_lat, self.max_lat = min(lats) - pad_lat, max(lats) + pad_lat
        self.min_lng, self.max_lng = min(lngs) - pad_lng, max(lngs) + pad_lng

        self.grid: dict[tuple[int, int], list[str]] = {}
        self.stops: set[str] = set()
        for uid, (lat, lng, _name) in sd.stop_meta.items():
            if not (self.min_lat <= lat <= self.max_lat and self.min_lng <= lng <= self.max_lng):
                continue
            self.stops.add(uid)
            self.grid.setdefault((int(lat / self.CELL), int(lng / self.CELL)), []).append(uid)

    def nearby(self, uid: str, radius_m: float) -> list[tuple[str, float]]:
        """半徑內的其他站牌（含距離）。用格網只掃鄰近幾格。"""
        meta = self.sd.stop_meta.get(uid)
        if not meta:
            return []
        lat, lng, _ = meta
        ci, cj = int(lat / self.CELL), int(lng / self.CELL)
        out = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for other in self.grid.get((ci + di, cj + dj), ()):
                    if other == uid:
                        continue
                    m2 = self.sd.stop_meta[other]
                    d = _haversine_m(lat, lng, m2[0], m2[1])
                    if d <= radius_m:
                        out.append((other, d))
        return out


def nearest_stop(sd: StaticData, corridor: Corridor, pos: dict, limit_m=500.0) -> str | None:
    """座標找最近站牌。用座標而非站名，繞開「臺北 / 台北」異體字問題。"""
    if not pos:
        return None
    lat, lng = pos["lat"], pos["lng"]
    ci, cj = int(lat / Corridor.CELL), int(lng / Corridor.CELL)
    best, best_d = None, None
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for uid in corridor.grid.get((ci + di, cj + dj), ()):
                m = sd.stop_meta[uid]
                d = _haversine_m(lat, lng, m[0], m[1])
                if best_d is None or d < best_d:
                    best, best_d = uid, d
    return best if best_d is not None and best_d <= limit_m else None


class Label:
    """搜尋狀態。__slots__ 省記憶體，節點多的時候有感。"""

    __slots__ = ("cost", "arrive", "transfers", "stop", "prev", "leg")

    def __init__(self, cost, arrive, transfers, stop, prev, leg):
        self.cost = cost  # 排序依據：時間 + 轉乘懲罰
        self.arrive = arrive  # 抵達該站的當日分鐘數（時間相依查詢用）
        self.transfers = transfers
        self.stop = stop
        self.prev = prev  # 前一個 Label，用來回溯路徑
        self.leg = leg  # 走到這裡的那一段（給輸出用）

    def __lt__(self, other):  # heapq 需要
        return self.cost < other.cost


def search(
    sd: StaticData,
    sources: list[tuple[str, int]],
    targets: dict[str, int],
    depart: datetime,
    corridor: Corridor,
) -> Label | None:
    """時間相依 Dijkstra。

    sources: [(起始站 UID, 到該站已花的秒數)]  —— 沿用 Google 的第一段步行
    targets: {目標站 UID: 從該站到終點還要走幾秒}
    回傳最佳的終點 Label，找不到回 None。

    ★ 為什麼可以用 Dijkstra：邊權非負，而且等待函數滿足 FIFO
      （晚出發不會早到），所以先確定的節點不會被後來的路徑改進。
      成本裡加了轉乘懲罰，嚴格說會破壞這個保證，但懲罰是常數且
      轉乘次數有上限，實務上不影響結果——這是路徑規劃常見的取捨。
    """
    weekday = depart.weekday()
    start_min = depart.hour * 60 + depart.minute

    heap: list[Label] = []
    for uid, walk_sec in sources:
        if uid not in corridor.stops:
            continue
        lab = Label(walk_sec, start_min + walk_sec // 60, 0, uid, None, None)
        heapq.heappush(heap, lab)

    best_cost: dict[str, int] = {}
    settled = 0
    best_end: Label | None = None

    while heap and settled < MAX_SETTLED:
        cur = heapq.heappop(heap)
        if best_cost.get(cur.stop, 1 << 30) <= cur.cost:
            continue
        best_cost[cur.stop] = cur.cost
        settled += 1

        # 到終點了嗎
        if cur.stop in targets:
            total = cur.cost + targets[cur.stop]
            if best_end is None or total < best_end.cost:
                best_end = Label(total, cur.arrive, cur.transfers, cur.stop, cur.prev, cur.leg)
            continue  # 終點不再往外展開

        if cur.transfers > MAX_TRANSFERS:
            continue

        # ---- 步行邊：走到附近的站牌（含同一車站群組的其他站牌）----
        for other, dist in corridor.nearby(cur.stop, TRANSFER_WALK_M):
            walk = int(dist / WALK_SPEED_MPS)
            cost = cur.cost + walk
            if cost < best_cost.get(other, 1 << 30):
                heapq.heappush(
                    heap,
                    Label(
                        cost,
                        cur.arrive + walk // 60,
                        cur.transfers,
                        other,
                        cur,
                        {"type": "WALK", "seconds": walk, "meters": int(dist)},
                    ),
                )

        # ---- 搭乘邊：這站有哪些路線可搭，各能坐到哪些下游站 ----
        #
        # ★ 一定要走車站群組展開，不能用 stop_index[cur.stop]。
        #   TDX 的 StopUID 是「每條路線各一份」，同一個實體站牌被 10 條路線
        #   經過就有 10 個不同 UID，stop_index 查單一 UID 只會拿到 1 條路線，
        #   圖會幾乎是斷的（實測每站只能搭 1 條，4/7 組找不到路徑）。
        for key, board_uid in sd.routes_at_group(sd.group_of(cur.stop)):
            idx = next((i for k, i in sd.stop_index.get(board_uid, ()) if k == key), None)
            if idx is None:
                continue
            # 發車時刻只跟「在第 idx 站」有關，跟坐到第幾站無關，
            # 所以查一次就好，不要對每個下車站重複查。
            first = sd.ride(key, idx, idx + 1, cur.arrive, weekday)
            if first is None:
                continue  # 今日已無班次，或沒有班表資料
            dep_min, _arr, src = first
            wait = max((dep_min - cur.arrive) * 60, 0)

            stops = sd.routes.get(key) or []
            route, _, direction = key.rpartition("|")
            mode = sd.modes.get(key, "BUS")
            limit = min(len(stops), idx + 1 + MAX_RIDE_STOPS)
            for j in range(idx + 1, limit):
                ride = sd.travel_sec(key, idx, j)
                if ride is None:
                    continue
                nxt = stops[j][0]
                if nxt not in corridor.stops:
                    continue
                cost = cur.cost + wait + ride + TRANSFER_PENALTY_SEC
                if cost >= best_cost.get(nxt, 1 << 30):
                    continue
                heapq.heappush(
                    heap,
                    Label(
                        cost,
                        dep_min + ride // 60,
                        cur.transfers + 1,
                        nxt,
                        cur,
                        {
                            "type": "RIDE",
                            "mode": mode,
                            "routeName": route,
                            "direction": int(direction),
                            "fromStop": sd.stop_meta[board_uid][2],
                            "toStop": sd.stop_meta[nxt][2],
                            "seconds": ride,
                            "waitSeconds": wait,
                            "stopCount": j - idx,
                            "source": src,
                        },
                    ),
                )

        if len(best_cost) > MAX_NODES:
            break

    return best_end


def to_plan(end: Label, trailing_walk_sec: int) -> dict:
    """把 Label 鏈回溯成符合契約的 plan（README §3）。"""
    raw = []
    node = end
    while node is not None:
        if node.leg:
            raw.append(node.leg)
        node = node.prev
    raw.reverse()

    if trailing_walk_sec:
        raw.append({"type": "WALK", "seconds": trailing_walk_sec, "meters": 0})

    # 合併連續步行，並丟掉零長度的那些。
    # 零長度會出現是因為 TDX 的 StopUID 是「每條路線各一份」，同一個實體
    # 站牌在不同路線是不同 UID，走過去距離是 0——那不是真的要走路。
    legs: list[dict] = []
    for leg in raw:
        if leg["type"] == "WALK":
            if leg.get("seconds", 0) <= 0 and leg.get("meters", 0) <= 0:
                continue
            if legs and legs[-1]["type"] == "WALK":
                legs[-1]["seconds"] += leg["seconds"]
                legs[-1]["meters"] += leg.get("meters", 0)
                continue
        legs.append(dict(leg))

    rides = [x for x in legs if x["type"] == "RIDE"]
    total = sum(x["seconds"] for x in legs) + sum(x.get("waitSeconds", 0) for x in rides)
    first_wait = rides[0].get("waitSeconds") if rides else None

    return {
        "totalSeconds": total,
        "transferCount": max(len(rides) - 1, 0),
        "steps": legs,
        "polyline": "",  # 自建路徑沒有 Google 的 polyline
        "waitSeconds": first_wait,
        "waitSource": "班表推估",
        "realSeconds": total,
        "isLive": False,
        "source": "algo",
    }


def find_alternative(
    sd: StaticData, google_plans: list[dict], depart: datetime | None = None
) -> dict | None:
    """從 Google 的候選推導出起訖範圍，找一條 Google 沒給的路徑。

    回傳一個 plan（含 source="algo"），找不到回 None。
    """
    depart = depart or datetime.now()

    # 蒐集 Google 各候選的第一段上車站與最後一段下車站
    seeds: list[tuple[dict, int]] = []
    ends: list[tuple[dict, int]] = []
    for p in google_plans:
        rides = [s for s in p.get("steps", []) if s.get("type") == "RIDE"]
        if not rides:
            continue
        lead = 0
        for s in p["steps"]:
            if s.get("type") == "RIDE":
                break
            lead += s.get("seconds", 0)
        tail = 0
        for s in reversed(p["steps"]):
            if s.get("type") == "RIDE":
                break
            tail += s.get("seconds", 0)
        if rides[0].get("fromStopPos"):
            seeds.append((rides[0]["fromStopPos"], lead))
        if rides[-1].get("toStopPos"):
            ends.append((rides[-1]["toStopPos"], tail))

    if not seeds or not ends:
        return None

    pts = [(p["lat"], p["lng"]) for p, _ in seeds] + [(p["lat"], p["lng"]) for p, _ in ends]
    corridor = Corridor(sd, pts)

    sources = []
    for pos, lead in seeds:
        uid = nearest_stop(sd, corridor, pos)
        if uid:
            sources.append((uid, lead))
    targets: dict[str, int] = {}
    for pos, tail in ends:
        uid = nearest_stop(sd, corridor, pos)
        if uid and (uid not in targets or tail < targets[uid]):
            targets[uid] = tail
    if not sources or not targets:
        return None

    end = search(sd, sources, targets, depart, corridor)
    if end is None:
        return None

    plan = to_plan(end, targets.get(end.stop, 0))

    # 只有明顯贏過 Google 才回傳。理由見 MIN_GAIN_RATIO 的註解：
    # 行駛時間是估的，小幅領先分不出是真的更快還是估計誤差。
    best_google = min((p.get("totalSeconds", 0) for p in google_plans if p.get("totalSeconds")), default=0)
    if best_google and plan["totalSeconds"] > best_google * MIN_GAIN_RATIO:
        return None
    plan["gainSeconds"] = best_google - plan["totalSeconds"] if best_google else 0
    return plan
