"""大台北公車靜態資料：下載、瘦身、建索引。

方案 B（自建轉乘圖）的資料層。設計重點：

  1. 六個請求抓完整個大台北（實測 74 秒、63MB 原始 JSON）
     Station / StopOfRoute / Schedule × Taipei / NewTaipei
  2. 原始資料太肥，載入時就砍掉用不到的欄位（英文名、地址、電話、VersionID…），
     只留 UID／座標／站序／班距。目標壓到 30MB 以內，Cloud Run 才裝得下。
  3. 瘦身後的結果落地磁碟，之後啟動不用重抓也不吃 TDX 配額。

★ 這裡完全不碰即時資料。跑演算法時一個 TDX 請求都不用打
  （只有第一段的即時候車會另外查 ETA），所以限流問題與本模組無關。
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime
from pathlib import Path

import rail_data
import tdx_client as tdx

CITIES = ["Taipei", "NewTaipei"]

# 公車平均車速（公尺／秒），已把站停時間攤提進去。
#
# ★ 這個值是校準出來的，不是猜的：拿 Google 對同一段的行駛時間當基準，
#   反推它隱含的車速，取中位數得 4.47 m/s（16.1 km/h）。取 4.4 略偏保守。
#   離散度很大（實測 11–29 km/h），因為路型差異本來就大——所以
#   graph.py 要求演算法必須贏過 Google 一定幅度才採用，見 MIN_GAIN_RATIO。
BUS_SPEED_MPS = 4.4


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
CACHE_DIR = Path(__file__).parent / "fixtures" / "cache"
SLIM_PATH = CACHE_DIR / "graph_static.json"
SLIM_TTL = 7 * 86400  # 靜態資料幾個月才變，一週重抓一次很夠

# 星期對應 Schedule.ServiceDay 的鍵名
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --------------------------------------------------------------------------
# 下載與瘦身
# --------------------------------------------------------------------------


async def _fetch_city(kind: str, city: str, retries: int = 4) -> list:
    """抓一份整城市的公車靜態資料，失敗就退避重試（理由同 rail_data._get_list）。"""
    for attempt in range(retries):
        data, status = await tdx._get(f"{tdx.BASE}/v2/Bus/{kind}/City/{city}")
        if status == "ok" and isinstance(data, list):
            return data
        await asyncio.sleep(6 * (attempt + 1))
    print(f"  ★ 取不到 Bus/{kind}/City/{city}")
    return []


def _pos(obj: dict, key: str) -> tuple[float, float] | None:
    p = obj.get(key) or {}
    lat, lng = p.get("PositionLat"), p.get("PositionLon")
    return (float(lat), float(lng)) if lat is not None and lng is not None else None


def _slim_stop_of_route(records: list) -> dict:
    """(路線名, 方向) -> 有序站牌清單。

    每站只留 [StopUID, 站名, lat, lng, 站序]，丟掉英文名與 StopBoarding。
    """
    out: dict[str, list] = {}
    for rec in records:
        route = (rec.get("RouteName") or {}).get("Zh_tw")
        direction = rec.get("Direction")
        if not route or direction is None:
            continue
        stops = []
        for s in rec.get("Stops") or []:
            uid = s.get("StopUID")
            pos = _pos(s, "StopPosition")
            seq = s.get("StopSequence")
            if not uid or pos is None or seq is None:
                continue
            stops.append([uid, (s.get("StopName") or {}).get("Zh_tw", ""), pos[0], pos[1], seq])
        if len(stops) < 2:
            continue
        stops.sort(key=lambda x: x[4])
        # 同一路線同方向可能有多個 SubRoute，保留站數最多的那個當主幹
        key = f"{route}|{direction}"
        if key not in out or len(stops) > len(out[key]):
            out[key] = stops
    return out


def _slim_station(records: list) -> dict:
    """StopUID -> 所屬車站群組 ID。

    Station 把「同一個地點、不同方向／不同路線」的站牌歸在一個 StationUID 底下。
    這個分組是免費且權威的轉乘資訊——同一群組內換車不用走路。
    """
    out: dict[str, str] = {}
    for rec in records:
        station = rec.get("StationUID")
        if not station:
            continue
        for s in rec.get("Stops") or []:
            uid = s.get("StopUID")
            if uid:
                out[uid] = station
    return out


def _hhmm(value) -> int | None:
    """"05:25" -> 325（當日分鐘數）。"""
    try:
        h, m = str(value).split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _day_mask(service_day: dict | None) -> int:
    sd = service_day or {}
    return sum(1 << i for i, d in enumerate(_WEEKDAYS) if sd.get(d))


def _slim_timetable(records: list) -> dict:
    """(路線名, 方向) -> 起站發車時刻清單 [[星期位元, 當日分鐘], ...]。

    ★ 實測結果：TDX 的公車 Timetables **只有起站發車時刻**，
      每個班次的 StopTimes 恆為 1 筆（單一路線端點也一樣）。
      所以沒有逐站時刻表可用，中途站的到站時刻必須自己推。

    這仍然很有價值——它是精確的發車時刻（南環幹線一天 139 班），
    比「班距 20 分鐘」這種平均值準得多，而且能反映末班車時間。
    中途站的偏移量用累積距離推算（見 StaticData.travel_sec）。
    """
    out: dict[str, list] = {}
    for rec in records:
        route = (rec.get("RouteName") or {}).get("Zh_tw")
        direction = rec.get("Direction")
        if not route or direction is None:
            continue
        deps = []
        for tt in rec.get("Timetables") or []:
            times = tt.get("StopTimes") or []
            if not times:
                continue
            mins = _hhmm(times[0].get("DepartureTime") or times[0].get("ArrivalTime"))
            if mins is not None:
                deps.append([_day_mask(tt.get("ServiceDay")), mins])
        if not deps:
            continue
        key = f"{route}|{direction}"
        prev = out.get(key)
        if prev is None or len(deps) > len(prev):
            out[key] = sorted(deps, key=lambda x: x[1])
    return out


def _slim_schedule(records: list) -> dict:
    """(路線名, 方向) -> 分時段班距。只有 9% 的路線沒有精確時刻表，用這個當備援。

    每筆存 [起, 迄, 最小班距分, 最大班距分, 適用星期位元]。
    """
    out: dict[str, list] = {}
    for rec in records:
        route = (rec.get("RouteName") or {}).get("Zh_tw")
        direction = rec.get("Direction")
        if not route or direction is None:
            continue
        bands = []
        for f in rec.get("Frequencys") or []:
            start, end = f.get("StartTime"), f.get("EndTime")
            lo, hi = f.get("MinHeadwayMins"), f.get("MaxHeadwayMins")
            if not start or not end or lo is None:
                continue
            bands.append(
                [start, end, int(lo), int(hi if hi is not None else lo), _day_mask(f.get("ServiceDay"))]
            )
        if not bands:
            continue
        key = f"{route}|{direction}"
        out.setdefault(key, []).extend(bands)
    return out


async def build(force: bool = False) -> dict:
    """抓取並瘦身。已有夠新的磁碟快取時直接讀檔。"""
    if not force and SLIM_PATH.exists():
        if time.time() - SLIM_PATH.stat().st_mtime < SLIM_TTL:
            return json.loads(SLIM_PATH.read_text(encoding="utf-8"))

    stops: dict = {}
    groups: dict = {}
    sched: dict = {}
    tables: dict = {}

    for city in CITIES:
        sor = await _fetch_city("StopOfRoute", city)
        stops.update(_slim_stop_of_route(sor))
        del sor

        sta = await _fetch_city("Station", city)
        groups.update(_slim_station(sta))
        del sta

        sch = await _fetch_city("Schedule", city)
        for k, v in _slim_schedule(sch).items():
            sched.setdefault(k, []).extend(v)
        tables.update(_slim_timetable(sch))
        del sch

    # ---- 轉成三種模式共用的統一結構 ----
    # 公車：行駛時間用距離推（TDX 的 S2STravelTime 對公車回空陣列），
    #       發車時刻只有起站（Timetables 每班次恆為 1 筆）。
    cumsec: dict[str, list] = {}
    deps: dict[str, dict] = {}
    modes: dict[str, str] = {}
    for key, route_stops in stops.items():
        acc, cum = 0.0, [0]
        for a, b in zip(route_stops, route_stops[1:]):
            acc += _haversine_m(a[2], a[3], b[2], b[3])
            cum.append(int(acc / BUS_SPEED_MPS))
        cumsec[key] = cum
        # ★ TDX 對很多公車路線只提供單一方向的班表（實測 660 有兩筆 Schedule，
        #   但兩筆都是 Direction=0）。不補的話 660/2235 個路線方向完全不可用，
        #   演算法會漏掉大量合理選項。公車雙向班距通常對稱，所以返程沿用去程，
        #   這是近似——精度不如原生資料，但總比整條路線消失好。
        route_name, _, direction = key.rpartition("|")
        other = f"{route_name}|{'1' if direction == '0' else '0'}"
        src_tt = tables.get(key) or tables.get(other)
        src_hw = sched.get(key) or sched.get(other)

        if src_tt:
            deps[key] = {"kind": "origin", "times": src_tt}
        elif src_hw:
            deps[key] = {"kind": "headway", "bands": src_hw}
        else:
            continue  # 兩個方向都沒資料，放進圖只會算出搭不到的路線
        modes[key] = "BUS"

    # ---- 併入捷運與台鐵 ----
    rail = await rail_data.load_all()
    stops.update(rail["routes"])
    cumsec.update(rail["cumsec"])
    deps.update(rail["deps"])
    modes.update(rail["modes"])

    data = {
        "builtAt": int(time.time()),
        "routes": stops,
        "groups": groups,
        "cumsec": cumsec,
        "deps": deps,
        "modes": modes,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SLIM_PATH.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data


# --------------------------------------------------------------------------
# 查詢介面
# --------------------------------------------------------------------------


class StaticData:
    """瘦身後的資料 + 反查索引。整個程式共用一份。"""

    def __init__(self, raw: dict):
        self.built_at = raw.get("builtAt", 0)
        # "路線|方向" -> [[StopUID, 名稱, lat, lng, 站序], ...]
        self.routes: dict[str, list] = raw.get("routes", {})
        self.groups: dict[str, str] = raw.get("groups", {})
        # 三種模式共用：累積行駛秒數、班次資訊、交通種類
        self.cumsec: dict[str, list] = raw.get("cumsec", {})
        self.deps: dict[str, dict] = raw.get("deps", {})
        self.modes: dict[str, str] = raw.get("modes", {})

        # StopUID -> [(路線|方向, 在該路線的索引位置)]
        self.stop_index: dict[str, list] = {}
        # StopUID -> (lat, lng, 站名)
        self.stop_meta: dict[str, tuple] = {}
        for key, stops in self.routes.items():
            for i, (uid, name, lat, lng, _seq) in enumerate(stops):
                self.stop_index.setdefault(uid, []).append((key, i))
                if uid not in self.stop_meta:
                    self.stop_meta[uid] = (lat, lng, name)

        # 車站群組 -> 該群組內所有站牌。轉乘要靠這個：TDX 的 StopUID 是
        # 「每條路線各自一份」，同一個實體站牌在不同路線是不同 UID，
        # 所以「這個地點有哪些路線」只能透過群組反查。
        self.group_stops: dict[str, list] = {}
        for uid in self.stop_meta:
            self.group_stops.setdefault(self.group_of(uid), []).append(uid)


    # -- 統計，給診斷腳本用 --
    def summary(self) -> dict:
        return {
            "routeDirections": len(self.routes),
            "stops": len(self.stop_meta),
            "stopRoutePairs": sum(len(v) for v in self.stop_index.values()),
            "stationGroups": len(self.group_stops),
            "timetableRoutes": len(self.timetable),
            "timetableTrips": sum(len(v) for v in self.timetable.values()),
            "headwayOnlyRoutes": len(set(self.schedule) - set(self.timetable)),
            "noScheduleRoutes": len(set(self.routes) - set(self.timetable) - set(self.schedule)),
        }

    def routes_at_group(self, group: str) -> list[tuple[str, str]]:
        """這個車站群組有哪些 (路線|方向, StopUID) 可搭。轉乘就是靠這個展開。"""
        out = []
        for uid in self.group_stops.get(group, ()):
            for key, _i in self.stop_index.get(uid, ()):
                out.append((key, uid))
        return out

    def group_of(self, stop_uid: str) -> str:
        """站牌所屬的車站群組；沒有分組資料時用自己當群組。"""
        return self.groups.get(stop_uid, stop_uid)

    def travel_sec(self, key: str, i: int, j: int) -> int | None:
        """站牌索引 i 到 j 的行駛秒數。

        公車是距離 ÷ 校準車速推的（TDX 的公車 S2STravelTime 回空陣列）；
        捷運用 S2STravelTime 的精確 RunTime；台鐵用該車次自己的到離時刻。
        """
        cum = self.cumsec.get(key)
        if not cum or not (0 <= i < j < len(cum)):
            return None
        return cum[j] - cum[i]

    def ride(
        self, key: str, i: int, j: int, after_min: int, weekday: int
    ) -> tuple[int, int, str] | None:
        """我在 after_min 抵達第 i 站，搭這條路線到第 j 站。

        回傳 (發車分鐘, 抵達分鐘, 資料來源)，搭不到回 None。

        ★ 這是時間相依的核心：同一段路，20 分鐘後出發等到的是不同班次，
          候車時間完全不同。所以每次展開都要用當下時刻重新查。

        三種班次資料的精度差很多：
          per_stop —— 每站都有發車時刻（捷運、台鐵），完全精確
          origin   —— 只有起站發車時刻（公車），中途站要用行駛時間往後推
          headway  —— 只有班距（文湖線、部分公車），期望等待取班距一半
        """
        travel = self.travel_sec(key, i, j)
        if travel is None:
            return None
        dep_info = self.deps.get(key)
        if not dep_info:
            return None
        kind = dep_info.get("kind")

        if kind == "per_stop":
            times = dep_info.get("times") or []
            if i >= len(times):
                return None
            for mask, dep in times[i]:
                if mask and not (mask >> weekday) & 1:
                    continue
                if dep >= after_min:
                    return dep, dep + travel // 60, "timetable"
            return None  # 今日該站已無班次

        if kind == "origin":
            offset = (self.cumsec.get(key) or [0])[i] // 60
            for mask, dep in dep_info.get("times") or []:
                if mask and not (mask >> weekday) & 1:
                    continue
                if dep + offset >= after_min:
                    d = dep + offset
                    return d, d + travel // 60, "timetable"
            return None

        if kind == "headway":
            hhmm = f"{(after_min // 60) % 24:02d}:{after_min % 60:02d}"
            for start, end, lo, hi, mask in dep_info.get("bands") or []:
                if mask and not (mask >> weekday) & 1:
                    continue
                in_band = start <= hhmm < end if start <= end else (hhmm >= start or hhmm < end)
                if in_band:
                    d = after_min + int((lo + hi) / 4)  # 期望等待 = 班距 / 2
                    return d, d + travel // 60, "headway"
            return None

        return None

    def headway_sec(self, route: str, direction: int, when: datetime) -> int | None:
        """指定時刻的班距（秒）。查不到回 None。

        取 Min 與 Max 的中間值——Min 太樂觀，Max 太悲觀。
        """
        bands = self.schedule.get(f"{route}|{direction}")
        if not bands:
            return None
        wd = when.weekday()  # 0=Monday
        hhmm = when.strftime("%H:%M")
        best = None
        for start, end, lo, hi, mask in bands:
            if mask and not (mask >> wd) & 1:
                continue
            # 跨午夜的時段（例如 23:00–01:00）
            in_band = start <= hhmm < end if start <= end else (hhmm >= start or hhmm < end)
            if not in_band:
                continue
            mid = (lo + hi) / 2
            if best is None or mid < best:
                best = mid
        if best is None:
            return None
        return int(best * 60)


_cached: StaticData | None = None


async def load(force: bool = False) -> StaticData:
    global _cached
    if _cached is None or force:
        _cached = StaticData(await build(force=force))
    return _cached


if __name__ == "__main__":

    async def _main() -> None:
        t0 = time.perf_counter()
        sd = await load(force="--force" in __import__("sys").argv)
        dt = time.perf_counter() - t0
        print(f"載入完成 {dt:.1f}s")
        print(f"磁碟檔案 {SLIM_PATH.stat().st_size / 1048576:.1f} MB")
        for k, v in sd.summary().items():
            print(f"  {k:18} {v:,}")
        now = datetime.now()
        after = now.hour * 60 + now.minute
        wd = now.weekday()
        print(f"\n上車查詢範例（現在 {now:%A %H:%M}，在該路線第 5 站）：")
        shown = 0
        for key in sd.timetable:
            if len(sd.routes.get(key, [])) <= 5:
                continue
            got = sd.board_at(key, 5, after, wd)
            route, _, d = key.rpartition("|")
            if got:
                dep, src = got
                print(f"  {route:12} 方向{d}  {dep // 60:02d}:{dep % 60:02d} 進站"
                      f"（等 {dep - after} 分，{src}）")
            else:
                print(f"  {route:12} 方向{d}  今日已無班次")
            shown += 1
            if shown >= 8:
                break

        print("\n行駛時間推算範例：")
        for key in list(sd.routes)[:4]:
            n = len(sd.routes[key])
            if n < 10:
                continue
            t10 = sd.travel_sec(key, 0, 9)
            km = sd.cum_m[key][9] / 1000
            route, _, d = key.rpartition("|")
            print(f"  {route:12} 方向{d}  前 10 站 {km:5.1f} km → {t10 // 60} 分")

    asyncio.run(_main())
