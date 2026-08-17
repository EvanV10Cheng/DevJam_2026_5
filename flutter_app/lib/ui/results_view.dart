// 結果區：路線標頭、查詢條件列、五個排序頁籤、方案一覽表、詳情。
// 對應 app.js 的 renderResultsPage 與 index.html 的 #resultsView。

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../logic/format.dart';
import '../logic/scoring.dart';
import '../logic/timeline.dart';
import '../theme/tokens.dart';
import 'plan_detail.dart';

class ResultsView extends StatelessWidget {
  final PlanResponse data;
  final String origin;
  final String destination;
  final DateTime departAt;
  final String timeMode;
  final String currentSort;
  final int selectedIndex;
  final ValueChanged<String> onSortChanged;
  final ValueChanged<int> onSelect;
  final VoidCallback onBackToSearch;
  final VoidCallback onPrev;
  final VoidCallback onNext;

  const ResultsView({
    super.key,
    required this.data,
    required this.origin,
    required this.destination,
    required this.departAt,
    required this.timeMode,
    required this.currentSort,
    required this.selectedIndex,
    required this.onSortChanged,
    required this.onSelect,
    required this.onBackToSearch,
    required this.onPrev,
    required this.onNext,
  });

  @override
  Widget build(BuildContext context) {
    final plans = sortPlans(data.plans, currentSort);
    final selected = selectedIndex < plans.length ? selectedIndex : 0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _routeHeader(),
        const SizedBox(height: 8),
        Text(formatQueryBarLabel(departAt, timeMode),
            style: const TextStyle(fontSize: 13, color: T.inkSoft)),
        const SizedBox(height: 12),
        _sortTabs(),
        const SizedBox(height: 12),
        _summaryTable(plans, selected),
        const SizedBox(height: 8),
        const Text('關於時間表修訂 ｜ 關於票價顯示 ｜ 關於定期票價',
            style: TextStyle(fontSize: 12, color: T.inkFaint)),
        const SizedBox(height: 12),
        _shiftButtons(),
        if (plans.isNotEmpty)
          PlanDetail(
            plan: plans[selected],
            index: selected,
            departAt: departAt,
            destinationName: destination,
          ),
      ],
    );
  }

  Widget _routeHeader() => Row(
        children: [
          Expanded(
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 6,
              runSpacing: 4,
              children: [
                _badge('離開', T.railBlue),
                Text(origin,
                    style: const TextStyle(
                        fontSize: 17, fontWeight: FontWeight.w700, color: T.ink)),
                const Text('›', style: TextStyle(fontSize: 18, color: T.inkFaint)),
                _badge('到達', T.destination),
                Text(destination,
                    style: const TextStyle(
                        fontSize: 17, fontWeight: FontWeight.w700, color: T.ink)),
              ],
            ),
          ),
          TextButton(
            onPressed: onBackToSearch,
            child: const Text('更改搜尋條件',
                style: TextStyle(color: T.railBlue, fontSize: 13)),
          ),
        ],
      );

  Widget _badge(String text, Color bg) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(T.radiusSm)),
        child: Text(text,
            style: const TextStyle(
                color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
      );

  Widget _sortTabs() => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: sortKeys.map((key) {
            final active = key == currentSort;
            return Padding(
              padding: const EdgeInsets.only(right: 8),
              child: GestureDetector(
                onTap: () => onSortChanged(key),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(
                    color: active ? T.railBlue : Colors.white,
                    borderRadius: BorderRadius.circular(T.radiusFull),
                    border: Border.all(color: active ? T.railBlue : T.line),
                    boxShadow: active ? T.shadowXs : null,
                  ),
                  child: Text(
                    sortLabels[key]!,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: active ? Colors.white : T.ink2,
                    ),
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      );

  Widget _summaryTable(List<Plan> plans, int selected) => Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(T.radiusLg),
          border: Border.all(color: T.line),
          boxShadow: T.shadowSm,
        ),
        child: Column(
          children: [
            for (var i = 0; i < plans.length; i++)
              _summaryRow(plans[i], i, i == selected, i == plans.length - 1),
          ],
        ),
      );

  Widget _summaryRow(Plan plan, int idx, bool active, bool last) {
    final times = getPlanTimes(plan, departAt);
    final waitInfo = plan.waitSeconds != null
        ? '候車 ${(plan.waitSeconds! / 60).round()} 分（${plan.waitSource}）'
        : plan.waitSource;

    return InkWell(
      onTap: () => onSelect(idx),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        decoration: BoxDecoration(
          color: active ? T.railBlueSoft : Colors.transparent,
          border: last ? null : const Border(bottom: BorderSide(color: T.line)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Container(
              width: 26,
              height: 26,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: active ? T.railBlue : T.paper,
                shape: BoxShape.circle,
              ),
              child: Text('${idx + 1}',
                  style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: active ? Colors.white : T.ink2)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 4,
                    children: [
                      Text(formatClock(times.start),
                          style: const TextStyle(
                              fontFamily: T.fontMono,
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: T.ink)),
                      const Text('⇒', style: TextStyle(color: T.inkFaint)),
                      Text(formatClock(times.end),
                          style: const TextStyle(
                              fontFamily: T.fontMono,
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: T.ink)),
                      const SizedBox(width: 6),
                      Text(formatDuration(plan.realSeconds),
                          style: const TextStyle(
                              fontSize: 14, fontWeight: FontWeight.w700, color: T.ink2)),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Wrap(
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 8,
                    runSpacing: 4,
                    children: [
                      if (plan.isLive)
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                          decoration: BoxDecoration(
                              color: T.linkGreenDark,
                              borderRadius: BorderRadius.circular(T.radiusFull)),
                          child: const Text('即時',
                              style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 10,
                                  fontWeight: FontWeight.w700)),
                        ),
                      Text('${plan.transferCount} 次轉乘',
                          style: const TextStyle(fontSize: 12, color: T.inkSoft)),
                      Text(waitInfo,
                          style: const TextStyle(fontSize: 12, color: T.inkSoft)),
                      ...planModes(plan.steps).map((m) => Container(
                            width: 9,
                            height: 9,
                            margin: const EdgeInsets.only(top: 4),
                            decoration: BoxDecoration(
                                color: T.modeColor(m), shape: BoxShape.circle),
                          )),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(formatFare(plan.fare),
                    style: const TextStyle(
                        fontFamily: T.fontMono,
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: T.rose)),
                if (plan.icFare != null)
                  Text('悠遊卡 ${formatFare(plan.icFare)}',
                      style: const TextStyle(fontSize: 10, color: T.inkSoft)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// ★ 用 Wrap 不用 Row：這兩個標籤很長，在 360px 的手機寬度下並排會
  ///   overflow 51 px（widget test 抓到的）。Wrap 放不下就自動換行。
  Widget _shiftButtons() => Wrap(
        alignment: WrapAlignment.spaceBetween,
        spacing: 8,
        children: [
          TextButton(
              onPressed: onPrev,
              child: const Text('◀ 前幾班車的出發及抵達時間',
                  style: TextStyle(fontSize: 12, color: T.railBlue))),
          TextButton(
              onPressed: onNext,
              child: const Text('接下來幾班車的出發及抵達時間 ▶',
                  style: TextStyle(fontSize: 12, color: T.railBlue))),
        ],
      );
}
