"""捷運與台鐵的靜態資料載入（方案 B 的軌道部分）。

為什麼要另外一支：公車與軌道的資料形狀差很多，硬塞進同一個載入器會很難讀。
兩邊最後都轉成 static_data 的統一結構（routes / cumsec / deps / modes）。

★ 軌道的資料品質遠優於公車，這是把它們納入圖的主要價值：

  | 需要什麼   | 公車              | 捷運              | 台鐵            |
  |-----------|-------------------|-------------------|-----------------|
  | 行駛時間   | S2STravelTime 空， | S2STravelTime     | 車次自己的到離   |
  |           | 只能距離÷車速估    | 精確 RunTime      | 時刻，精確       |
  | 發車時刻   | 只有起站          | 每一站都有        | 每站每車次都有   |

  所以捷運／台鐵段在圖裡是精確值，不是估計值。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import tdx_client as tdx

METRO_OPERATORS = ["TRTC", "NTMC"]  # 台北捷運、新北捷運（環狀線）

# LineID -> 中文線名。TDX 的 StationOfRoute.RouteName 是「頂埔－南港展覽館」
# 這種起訖描述，不是線名，所以自己對照。
METRO_LINE_NAMES = {
    "BL": "板南線",
    "BR": "文湖線",
    "R": "淡水信義線",
    "G": "松山新店線",
    "O": "中和新蘆線",
    "Y": "環狀線",
}

# 大台北的台鐵車站。台鐵是全國路網，只留這些站進圖，否則節點會爆掉。
TRA_TAIPEI_STATIONS = {
    "0900": "基隆", "0910": "三坑", "0920": "八堵", "0930": "七堵", "0940": "百福",
    "0950": "五堵", "0960": "汐止", "0970": "汐科", "0980": "南港", "0990": "松山",
    "1000": "臺北", "1010": "萬華", "1020": "板橋", "1030": "浮洲", "1040": "樹林",
    "1050": "山佳", "1060": "鶯歌", "1070": "桃園",
}

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _hhmm(value) -> int | None:
    try:
        h, m = str(value).split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _mask(service_day: dict | None) -> int:
    sd = service_day or {}
    m = sum(1 << i for i, d in enumerate(_WEEKDAYS) if sd.get(d))
    return m or 0b1111111  # 沒寫就當每天行駛


async def _get_list(path: str, key: str | None = None, retries: int = 4) -> list:
    """抓一份靜態清單，失敗就退避重試。

    ★ 一定要重試：整個靜態建置會連續打十幾個請求，TDX 的限流很緊
      （實測單金鑰每 0.5 秒一次就有一半被擋），沒有重試的話會靜默漏資料——
      第一次實作時台鐵整份沒進去、環狀線也不見了，而且完全沒有錯誤訊息。
      這份資料一天才建一次，慢幾秒無所謂。
    """
    for attempt in range(retries):
        data, status = await tdx._get(f"{tdx.BASE}{path}")
        if status == "ok":
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if key and isinstance(data.get(key), list):
                    return data[key]
                for v in data.values():
                    if isinstance(v, list) and v:
                        return v
            return []
        await asyncio.sleep(6 * (attempt + 1))
    print(f"  ★ 取不到 {path}（重試 {retries} 次仍失敗）")
    return []


# --------------------------------------------------------------------------
# 捷運
# --------------------------------------------------------------------------


async def load_metro() -> dict:
    """回傳 {routes, cumsec, deps, modes, coords}，鍵為 "線名|方向"。"""
    routes: dict[str, list] = {}
    cumsec: dict[str, list] = {}
    deps: dict[str, dict] = {}
    modes: dict[str, str] = {}

    for op in METRO_OPERATORS:
        # 站點座標
        coords: dict[str, tuple] = {}
        for st in await _get_list(f"/v2/Rail/Metro/Station/{op}", "Stations"):
            sid = st.get("StationID")
            p = st.get("StationPosition") or {}
            lat, lng = p.get("PositionLat"), p.get("PositionLon")
            if sid and lat is not None and lng is not None:
                coords[sid] = (float(lat), float(lng), (st.get("StationName") or {}).get("Zh_tw", ""))

        # 站間精確行駛秒數：(起站, 迄站) -> RunTime + StopTime
        seg: dict[tuple, int] = {}
        for rec in await _get_list(f"/v2/Rail/Metro/S2STravelTime/{op}"):
            for tt in rec.get("TravelTimes") or []:
                a, b = tt.get("FromStationID"), tt.get("ToStationID")
                run, stop = tt.get("RunTime"), tt.get("StopTime") or 0
                if a and b and run is not None:
                    seg[(a, b)] = int(run) + int(stop)

        # 每一站的發車時刻：(LineID, Direction) -> {StationID: [(星期位元, 分鐘)]}
        dep_map: dict[tuple, dict] = {}
        for rec in await _get_list(f"/v2/Rail/Metro/StationTimeTable/{op}"):
            line, direction = rec.get("LineID"), rec.get("Direction")
            sid = rec.get("StationID")
            if not line or direction is None or not sid:
                continue
            m = _mask(rec.get("ServiceDay"))
            bucket = dep_map.setdefault((line, direction), {}).setdefault(sid, [])
            for tt in rec.get("Timetables") or []:
                mins = _hhmm(tt.get("DepartureTime"))
                if mins is not None:
                    bucket.append((m, mins))

        # 班距，給沒有站別時刻表的線用（實測文湖線 BR 完全沒有 StationTimeTable）
        headways: dict[tuple, list] = {}
        for rec in await _get_list(f"/v2/Rail/Metro/Frequency/{op}"):
            line = rec.get("LineID")
            if not line:
                continue
            m = _mask(rec.get("ServiceDay"))
            for hw in rec.get("Headways") or []:
                lo, hi = hw.get("MinHeadwayMins"), hw.get("MaxHeadwayMins")
                if lo is None:
                    continue
                headways.setdefault(line, []).append(
                    [hw.get("StartTime"), hw.get("EndTime"), int(lo), int(hi or lo), m]
                )

        # 站序，組成統一結構
        for rec in await _get_list(f"/v2/Rail/Metro/StationOfRoute/{op}"):
            line, direction = rec.get("LineID"), rec.get("Direction")
            stations = rec.get("Stations") or []
            if not line or direction is None or len(stations) < 2:
                continue
            stations = sorted(stations, key=lambda s: s.get("Sequence", 0))

            stops, cum = [], [0]
            ok = True
            prev_id = None
            for s in stations:
                sid = s.get("StationID")
                meta = coords.get(sid)
                if not sid or not meta:
                    ok = False
                    break
                stops.append([sid, meta[2], meta[0], meta[1], s.get("Sequence", 0)])
                if prev_id is not None:
                    # 站間時間表只給單一方向，反向就把起訖顛倒過來查
                    secs = seg.get((prev_id, sid)) or seg.get((sid, prev_id))
                    cum.append(cum[-1] + (secs if secs else 180))  # 查不到就給 3 分鐘
                prev_id = sid
            if not ok or len(stops) < 2:
                continue

            name = METRO_LINE_NAMES.get(line, line)
            key = f"{name}|{direction}"
            # 同一條線有多個 RouteID（板南線 BL-1 有 23 站、BL-2 只有 19 站，
            # 那是區間車路線），保留站數最多的主幹，不要被短的覆蓋掉。
            if key in routes and len(routes[key]) >= len(stops):
                continue

            times = [sorted(dep_map.get((line, direction), {}).get(s[0], [])) for s in stops]
            if any(times):
                deps[key] = {"kind": "per_stop", "times": times}
            elif headways.get(line):
                # 文湖線沒有站別時刻表，退回班距推估
                deps[key] = {"kind": "headway", "bands": headways[line]}
            else:
                continue  # 沒有任何班次資訊就不要放進圖，免得算出搭不到的路線

            routes[key] = stops
            cumsec[key] = cum
            modes[key] = "METRO"

    return {"routes": routes, "cumsec": cumsec, "deps": deps, "modes": modes}


# --------------------------------------------------------------------------
# 台鐵
# --------------------------------------------------------------------------


async def load_tra() -> dict:
    """每個車次當成一條「路線」，鍵為 "車種 車次|0"。

    台鐵每個車次的停靠站不同，用路線來模型化會失真；直接把車次當路線，
    上車時刻與抵達時刻都是該車次自己的時刻表，完全精確。
    只留停靠大台北的車次（實測 908 車次中有 329 個）。
    """
    routes: dict[str, list] = {}
    cumsec: dict[str, list] = {}
    deps: dict[str, dict] = {}
    modes: dict[str, str] = {}

    coords: dict[str, tuple] = {}
    for st in await _get_list("/v3/Rail/TRA/Station", "Stations"):
        sid = st.get("StationID")
        p = st.get("StationPosition") or {}
        lat, lng = p.get("PositionLat"), p.get("PositionLon")
        if sid and lat is not None and lng is not None:
            coords[sid] = (float(lat), float(lng), (st.get("StationName") or {}).get("Zh_tw", ""))

    for rec in await _get_list("/v3/Rail/TRA/DailyTrainTimetable/Today", "TrainTimetables"):
        info = rec.get("TrainInfo") or {}
        train_no = info.get("TrainNo")
        if not train_no or info.get("SuspendedFlag"):
            continue

        # 只留大台北範圍內的停靠站，且必須至少兩站才有搭乘意義
        picked = []
        for st in sorted(rec.get("StopTimes") or [], key=lambda x: x.get("StopSequence", 0)):
            sid = st.get("StationID")
            if sid not in TRA_TAIPEI_STATIONS or st.get("SuspendedFlag"):
                continue
            dep = _hhmm(st.get("DepartureTime"))
            arr = _hhmm(st.get("ArrivalTime"))
            meta = coords.get(sid)
            if dep is None or meta is None:
                continue
            picked.append((sid, meta, dep, arr if arr is not None else dep))
        if len(picked) < 2:
            continue

        kind = (info.get("TrainTypeName") or {}).get("Zh_tw", "").split("(")[0] or "區間"
        key = f"{kind} {train_no}|0"
        base = picked[0][2]
        stops, cum, times = [], [], []
        for i, (sid, meta, dep, arr) in enumerate(picked):
            stops.append([sid, meta[2], meta[0], meta[1], i + 1])
            # 跨午夜的車次：時刻回捲時補一天
            span = (arr - base) * 60
            cum.append(span if span >= 0 else span + 86400)
            times.append([(_mask(None), dep if dep >= base else dep + 1440)])

        routes[key] = stops
        cumsec[key] = cum
        deps[key] = {"kind": "per_stop", "times": times}
        modes[key] = "TRAIN"

    return {"routes": routes, "cumsec": cumsec, "deps": deps, "modes": modes}


async def load_all() -> dict:
    metro, tra = await load_metro(), await load_tra()
    out = {"routes": {}, "cumsec": {}, "deps": {}, "modes": {}}
    for part in (metro, tra):
        for k in out:
            out[k].update(part[k])
    return out


if __name__ == "__main__":

    async def _main() -> None:
        m = await load_metro()
        print(f"捷運：{len(m['routes'])} 條線方向")
        for key in list(m["routes"])[:4]:
            stops, cum = m["routes"][key], m["cumsec"][key]
            times = m["deps"][key]["times"]
            covered = sum(1 for t in times if t)
            print(f"  {key:16} {len(stops):>3} 站  全程 {cum[-1] // 60} 分  "
                  f"有發車時刻的站 {covered}/{len(stops)}")

        t = await load_tra()
        print(f"\n台鐵：{len(t['routes'])} 個車次（已過濾成只停大台北）")
        now = datetime.now()
        after = now.hour * 60 + now.minute
        shown = 0
        for key, stops in t["routes"].items():
            dep = t["deps"][key]["times"][0][0][1]
            if dep < after:
                continue
            names = " → ".join(s[1] for s in stops[:4])
            print(f"  {key:14} {dep // 60:02d}:{dep % 60:02d} 發  "
                  f"全程 {t['cumsec'][key][-1] // 60:>3} 分  {names}")
            shown += 1
            if shown >= 6:
                break

    asyncio.run(_main())
