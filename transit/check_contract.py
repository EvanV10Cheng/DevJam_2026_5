"""契約檢查器 — P4 擁有。（README §3 硬性規則、§9.4 驗收）

用途一（現在）：確認 mock.json 沒寫錯，P3 才敢信任它。
用途二（第 7 小時合併）：確認真實回傳與 mock.json 欄位名稱、型別完全一致。
    這一步用眼睛比對在時間壓力下一定會漏掉，所以寫成程式。

用法：
    python check_contract.py mock.json
    python check_contract.py "http://localhost:8080/api/plans?origin=台北車站&destination=淡水捷運站"

★ 檢查的核心是「所有欄位一律存在，就算值是 null」。
  JS 對缺欄位寬容，Dart 不是——階段二會直接閃退。
"""

import json
import sys
import urllib.parse
import urllib.request

# 欄位名 -> 允許的型別。None 代表允許 null。
TOP = {"queryTime": (int,), "plans": (list,), "googleOrder": (list,), "reordered": (bool,)}
PLAN = {
    "totalSeconds": (int,),
    "transferCount": (int,),
    "steps": (list,),
    "polyline": (str,),
    "waitSeconds": (int, type(None)),
    "waitSource": (str,),
    "realSeconds": (int,),
    "isLive": (bool,),
}
WALK = {"type": (str,), "seconds": (int,), "meters": (int,)}
RIDE = {
    "type": (str,),
    "mode": (str,),
    "routeName": (str,),
    "fromStop": (str,),
    "toStop": (str,),
    "seconds": (int,),
    "stopCount": (int,),
}

MODES = {"BUS", "METRO", "TRAIN", "HSR"}
# 「無班次」與「查詢受限」是為了需求 1 新增的：要能分辨「這站真的沒車」
# 與「被 TDX 限流」，舊版兩者都會顯示成「班表推估」。
SOURCES = {"即時", "班表推估", "末班已過", "無班次", "查詢受限"}

errors: list[str] = []
warnings: list[str] = []


def check(obj: dict, spec: dict, where: str) -> None:
    for key, types in spec.items():
        if key not in obj:
            errors.append(f"{where}: 缺少欄位 {key!r}（契約要求所有欄位一律存在）")
        elif not isinstance(obj[key], types):
            got = type(obj[key]).__name__
            want = "/".join(t.__name__ for t in types)
            errors.append(f"{where}.{key}: 型別是 {got}，契約要求 {want}")


def load(src: str) -> dict:
    if src.startswith("http"):
        parts = urllib.parse.urlsplit(src)
        # 中文參數必須 URL-encode，否則 uvicorn 會判成 Invalid HTTP request
        safe = urllib.parse.urlunsplit(
            parts._replace(query=urllib.parse.quote(parts.query, safe="=&"))
        )
        with urllib.request.urlopen(safe, timeout=20) as r:
            return json.load(r)
    with open(src, encoding="utf-8") as f:
        return json.load(f)


def main(src: str) -> int:
    data = load(src)
    check(data, TOP, "root")

    plans = data.get("plans") or []
    if not plans:
        errors.append("root.plans: 是空的，無法檢查方案結構")

    seen_modes, seen_sources, seen_live = set(), set(), set()

    for i, plan in enumerate(plans):
        where = f"plans[{i}]"
        check(plan, PLAN, where)

        if plan.get("waitSource") not in SOURCES:
            errors.append(f"{where}.waitSource: {plan.get('waitSource')!r} 不在 {SOURCES}")
        seen_sources.add(plan.get("waitSource"))
        seen_live.add(plan.get("isLive"))

        # realSeconds = totalSeconds + (waitSeconds or 0)
        expect = plan.get("totalSeconds", 0) + (plan.get("waitSeconds") or 0)
        if plan.get("realSeconds") != expect:
            errors.append(
                f"{where}.realSeconds: 是 {plan.get('realSeconds')}，依公式應為 {expect}"
            )

        if plan.get("isLive") != (plan.get("waitSource") == "即時"):
            errors.append(f"{where}.isLive: 與 waitSource 不一致")

        rides = 0
        for j, step in enumerate(plan.get("steps", [])):
            sw = f"{where}.steps[{j}]"
            if step.get("type") == "WALK":
                check(step, WALK, sw)
            elif step.get("type") == "RIDE":
                check(step, RIDE, sw)
                rides += 1
                if step.get("mode") not in MODES:
                    errors.append(f"{sw}.mode: {step.get('mode')!r} 不在 {MODES}")
                seen_modes.add(step.get("mode"))
            else:
                errors.append(f"{sw}.type: {step.get('type')!r} 必須是 WALK 或 RIDE")

        if plan.get("transferCount") != max(rides - 1, 0):
            errors.append(
                f"{where}.transferCount: 是 {plan.get('transferCount')}，"
                f"依 RIDE 步驟數應為 {max(rides - 1, 0)}"
            )

    if len(data.get("googleOrder") or []) != len(plans):
        errors.append("root.googleOrder: 長度與 plans 不同")

    ranked = [p.get("realSeconds") for p in plans]
    if ranked != sorted(ranked):
        errors.append("root.plans: 未依 realSeconds 遞增排序")

    # 以下是覆蓋度提醒，不算錯誤——但 mock.json 應該要全中
    for missing in MODES - seen_modes:
        warnings.append(f"沒有任何步驟用到 mode={missing}，P3 的圖示測不到")
    # 只提醒核心三種；「無班次」「查詢受限」是異常狀態，沒出現反而是好事
    for missing in {"即時", "班表推估", "末班已過"} - seen_sources:
        warnings.append(f"沒有任何方案的 waitSource={missing}")
    if "查詢受限" in seen_sources:
        warnings.append("★ 出現「查詢受限」——TDX 正在限流，這批資料不可信")
    if len(seen_live) < 2:
        warnings.append("isLive 只出現一種值，P3 的即時徽章測不到出現/消失")
    if not data.get("reordered"):
        warnings.append("reordered 是 false，P3 的黃色提示條測不到")

    for w in warnings:
        print(f"[提醒] {w}")
    for e in errors:
        print(f"[錯誤] {e}")

    print(
        f"\n{src}：{len(plans)} 個方案，{len(errors)} 個錯誤，{len(warnings)} 個提醒"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
