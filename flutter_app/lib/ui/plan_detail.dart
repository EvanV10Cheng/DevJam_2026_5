// 方案詳情：標頭 + 時刻表。
// 對應 app.js 的 renderPlanDetail / renderStationRow / renderRideRow / renderWalkRow。

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../logic/format.dart';
import '../logic/timeline.dart';
import '../theme/tokens.dart';

class PlanDetail extends StatelessWidget {
  final Plan plan;
  final int index;
  final DateTime departAt;
  final String destinationName;

  const PlanDetail({
    super.key,
    required this.plan,
    required this.index,
    required this.departAt,
    required this.destinationName,
  });

  @override
  Widget build(BuildContext context) {
    final times = getPlanTimes(plan, departAt);
    final meters = getTotalMeters(plan.steps);
    final rows = buildTimeline(plan, departAt, destinationName);

    return Container(
      decoration: BoxDecoration(
        color: T.paperCard,
        borderRadius: BorderRadius.circular(T.radiusXl),
        border: Border.all(color: T.line),
        boxShadow: T.shadowSm,
      ),
      margin: const EdgeInsets.only(top: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _header(times.start, times.end, meters),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
            child: Column(children: rows.map(_row).toList()),
          ),
        ],
      ),
    );
  }

  Widget _header(DateTime start, DateTime end, int meters) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: T.railBlueSoft,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(T.radiusXl)),
        border: const Border(bottom: BorderSide(color: T.line)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 排名圓標
          Container(
            width: 30,
            height: 30,
            alignment: Alignment.center,
            decoration: const BoxDecoration(color: T.railBlue, shape: BoxShape.circle),
            child: Text('${index + 1}',
                style: const TextStyle(
                    color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(formatClock(start),
                        style: const TextStyle(
                            fontFamily: T.fontMono,
                            fontSize: 22,
                            fontWeight: FontWeight.w700,
                            color: T.ink)),
                    const Text(' 出發', style: TextStyle(color: T.inkSoft, fontSize: 13)),
                    const Text('  ›  ', style: TextStyle(color: T.inkFaint, fontSize: 16)),
                    Text(formatClock(end),
                        style: const TextStyle(
                            fontFamily: T.fontMono,
                            fontSize: 22,
                            fontWeight: FontWeight.w700,
                            color: T.ink)),
                    const Text(' 到達', style: TextStyle(color: T.inkSoft, fontSize: 13)),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  '期間 ${formatDuration(plan.realSeconds)} · 轉乘 ${plan.transferCount} 次'
                  '${meters != 0 ? ' · 距離 ${formatMeters(meters)}' : ''}',
                  style: const TextStyle(color: T.inkSoft, fontSize: 13),
                ),
                const SizedBox(height: 6),
                Wrap(spacing: 6, children: _tags()),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Text('通常', style: TextStyle(color: T.inkFaint, fontSize: 11)),
              Text(formatFare(plan.fare),
                  style: const TextStyle(
                      fontFamily: T.fontMono,
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                      color: T.rose)),
              if (plan.icFare != null)
                Text('悠遊卡 ${formatFare(plan.icFare)}',
                    style: const TextStyle(color: T.inkSoft, fontSize: 11)),
            ],
          ),
        ],
      ),
    );
  }

  List<Widget> _tags() {
    final tags = <Widget>[];
    if (plan.isLive) tags.add(_tag('即時', T.linkGreenDark, T.linkGreen));
    if (plan.transferCount == 0) tags.add(_tag('樂', T.railBlueDark, T.railBlueLight));
    if (plan.realSeconds <= 1800) tags.add(_tag('快', T.signalAmberInk, T.submitOrange));
    return tags;
  }

  Widget _tag(String label, Color fg, Color bg) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
            color: bg.withValues(alpha: 0.25),
            borderRadius: BorderRadius.circular(T.radiusFull)),
        child: Text(label,
            style: TextStyle(color: fg, fontSize: 11, fontWeight: FontWeight.w700)),
      );

  Widget _row(TimelineRow r) => switch (r.kind) {
        RowKind.station => _stationRow(r),
        RowKind.ride => _rideRow(r.step!),
        RowKind.walk => _walkRow(r.step!),
      };

  /// 三欄結構：時間 / 軌道 / 內容，對應 CSS 的 .tl-row__time / __rail / __body
  ///
  /// ★ 一定要包 IntrinsicHeight。
  ///   軌道那一欄要「長到跟這一列一樣高」，用 CrossAxisAlignment.stretch 是自然的寫法，
  ///   但這個 Row 位在可捲動的 Column 裡，垂直方向的高度是無限的，
  ///   stretch 會丟出 "BoxConstraints forces an infinite height" 讓整個詳情畫不出來
  ///   ——症狀就是搜尋後看到一片空白。
  ///   IntrinsicHeight 先量出最高的子項再據以拉伸，才有有限的高度可用。
  Widget _shell({required Widget time, required Widget rail, required Widget body}) =>
      IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
                width: 84,
                child: Padding(padding: const EdgeInsets.only(top: 10), child: time)),
            SizedBox(width: 28, child: rail),
            Expanded(
                child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8), child: body)),
          ],
        ),
      );

  Widget _stationRow(TimelineRow s) {
    final color = T.modeColor(s.mode);
    final notes = <String>[];
    if (s.walk != null) {
      final w = s.walk!;
      notes.add('站內轉乘：步行 ${(w.seconds / 60).round()} 分'
          '${w.meters != 0 ? ' · ${formatMeters(w.meters)}' : ''}');
    }
    if (s.waitSeconds != 0) {
      // 第一段才是「你要等多久」；轉乘段只能說「該站現在下一班多久後到」，
      // 因為那個數字是從查詢當下算起的，不是從你抵達轉乘站的時刻算起。
      notes.add(s.waitIsActionable
          ? '候車 ${(s.waitSeconds / 60).round()} 分'
          : '該站目前下一班約 ${(s.waitSeconds / 60).round()} 分後');
    }

    return _shell(
      time: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (s.arriveAt != null)
            Text('${formatClock(s.arriveAt!)} 到達',
                style: const TextStyle(
                    fontFamily: T.fontMono, fontSize: 12, color: T.inkSoft)),
          if (s.departAt != null)
            Text('${formatClock(s.departAt!)} 出發',
                style: const TextStyle(
                    fontFamily: T.fontMono,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: T.ink)),
        ],
      ),
      rail: Center(
        child: Container(
          width: 13,
          height: 13,
          decoration: BoxDecoration(
            color: Colors.white,
            shape: BoxShape.circle,
            border: Border.all(color: color, width: 3),
          ),
        ),
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 6,
            runSpacing: 4,
            children: [
              if (s.isStart) _badge('離開', T.railBlue),
              if (s.isEnd) _badge('到達', T.destination),
              Text(s.name,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700, color: T.ink)),
              _tool('區域地圖'),
              _tool('時間表'),
            ],
          ),
          for (final n in notes)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(n, style: const TextStyle(fontSize: 12, color: T.inkSoft)),
            ),
        ],
      ),
    );
  }

  Widget _badge(String text, Color bg) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(T.radiusSm)),
        child: Text(text,
            style: const TextStyle(
                color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
      );

  Widget _tool(String text) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          border: Border.all(color: T.lineStrong),
          borderRadius: BorderRadius.circular(T.radiusSm),
        ),
        child: Text(text, style: const TextStyle(fontSize: 11, color: T.railBlue)),
      );

  Widget _rideRow(TransitStep step) {
    final color = T.modeColor(step.mode);
    return _shell(
      time: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text('${(step.seconds / 60).round()} 分鐘',
              style: const TextStyle(fontFamily: T.fontMono, fontSize: 12, color: T.ink2)),
          if (step.meters != 0)
            Text(formatMeters(step.meters),
                style: const TextStyle(fontSize: 11, color: T.inkFaint)),
        ],
      ),
      rail: Center(child: Container(width: 6, color: color)),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 6,
            runSpacing: 4,
            children: [
              _modeTag(T.modeLabel(step.mode), color),
              Text(step.routeName,
                  style: const TextStyle(fontWeight: FontWeight.w700, color: T.ink)),
              Text('往 ${step.toStop}',
                  style: const TextStyle(fontSize: 12, color: T.inkSoft)),
            ],
          ),
          if (step.platform.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(step.platform,
                  style: const TextStyle(fontSize: 12, color: T.railBlue)),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(
              '${step.stopCount != 0 ? '${step.stopCount} 站 · ' : ''}中間停靠',
              style: const TextStyle(fontSize: 12, color: T.inkFaint),
            ),
          ),
        ],
      ),
    );
  }

  Widget _walkRow(TransitStep step) => _shell(
        time: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text('${(step.seconds / 60).round()} 分鐘',
                style: const TextStyle(fontFamily: T.fontMono, fontSize: 12, color: T.ink2)),
            if (step.meters != 0)
              Text(formatMeters(step.meters),
                  style: const TextStyle(fontSize: 11, color: T.inkFaint)),
          ],
        ),
        // 步行用虛線，對應 CSS 的 .tl-bar--walk
        rail: Center(
          child: SizedBox(
            width: 6,
            child: Column(
              children: List.generate(
                8,
                (_) => Expanded(
                  child: Container(
                    margin: const EdgeInsets.symmetric(vertical: 1.5),
                    color: T.inkFaint.withValues(alpha: 0.5),
                  ),
                ),
              ),
            ),
          ),
        ),
        body: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _modeTag('步行', T.inkSoft),
            const Padding(
              padding: EdgeInsets.only(top: 2),
              child: Text('徒步移動', style: TextStyle(fontSize: 12, color: T.inkFaint)),
            ),
          ],
        ),
      );

  Widget _modeTag(String label, Color color) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(T.radiusSm)),
        child: Text(label,
            style: const TextStyle(
                color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
      );
}
