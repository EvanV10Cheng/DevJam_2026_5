// 詳情時刻表的資料結構，直譯自 app.js 的 buildTimeline。
//
// 拆成純邏輯（不含 Widget）有兩個好處：可以單獨測試，
// 而且那段「同站轉乘要合併成一個節點」的判斷很容易寫錯，值得單獨守住。

import '../api/models.dart';

enum RowKind { station, ride, walk }

class TimelineRow {
  final RowKind kind;

  // station
  final String name;
  final DateTime? arriveAt;
  final DateTime? departAt;
  final String mode;
  final TransitStep? walk; // 站內轉乘的步行
  final int waitSeconds;
  final bool isStart;
  final bool isEnd;

  // ride / walk
  final TransitStep? step;

  const TimelineRow({
    required this.kind,
    this.name = '',
    this.arriveAt,
    this.departAt,
    this.mode = '',
    this.walk,
    this.waitSeconds = 0,
    this.isStart = false,
    this.isEnd = false,
    this.step,
  });

  TimelineRow copyWith({bool? isStart, bool? isEnd}) => TimelineRow(
        kind: kind,
        name: name,
        arriveAt: arriveAt,
        departAt: departAt,
        mode: mode,
        walk: walk,
        waitSeconds: waitSeconds,
        isStart: isStart ?? this.isStart,
        isEnd: isEnd ?? this.isEnd,
        step: step,
      );
}

class _Pending {
  String stop;
  DateTime arriveAt;
  String mode;
  TransitStep? walk;
  _Pending(this.stop, this.arriveAt, this.mode, this.walk);
}

/// 把方案攤平成時刻表的列。
///
/// ★ step.waitSeconds 必須已經算在 plan.realSeconds 裡，
///   否則時刻表的到站時間會跟上方一覽表的抵達時間對不起來。
List<TimelineRow> buildTimeline(Plan plan, DateTime departAt, String destinationName) {
  var cursor = departAt;
  final rows = <TimelineRow>[];
  _Pending? pending;

  for (final step in plan.steps) {
    if (step.type == 'WALK') {
      if (pending != null) {
        // 下車之後的步行：先掛在到站節點上，
        // 等下一段車決定這是同站轉乘還是跨站移動
        pending.walk = step;
      } else {
        rows.add(TimelineRow(kind: RowKind.walk, step: step));
      }
      cursor = cursor.add(Duration(seconds: step.seconds));
      continue;
    }

    if (!step.isRide) continue;

    final waitSeconds = step.waitSeconds ?? 0;
    final departTime = cursor.add(Duration(seconds: waitSeconds));
    final arriveTime = departTime.add(Duration(seconds: step.seconds));

    if (pending != null && pending.stop == step.fromStop) {
      // 同一站轉乘 → 合併成「到達 / 出發」一個節點
      rows.add(TimelineRow(
        kind: RowKind.station,
        name: step.fromStop,
        arriveAt: pending.arriveAt,
        departAt: departTime,
        mode: step.mode,
        walk: pending.walk,
        waitSeconds: waitSeconds,
      ));
    } else {
      if (pending != null) {
        rows.add(TimelineRow(
          kind: RowKind.station,
          name: pending.stop,
          arriveAt: pending.arriveAt,
          mode: pending.mode,
        ));
        if (pending.walk != null) {
          rows.add(TimelineRow(kind: RowKind.walk, step: pending.walk));
        }
      }
      rows.add(TimelineRow(
        kind: RowKind.station,
        name: step.fromStop,
        departAt: departTime,
        mode: step.mode,
        waitSeconds: waitSeconds,
      ));
    }

    rows.add(TimelineRow(kind: RowKind.ride, step: step));
    pending = _Pending(step.toStop, arriveTime, step.mode, null);
    cursor = arriveTime;
  }

  if (pending != null) {
    rows.add(TimelineRow(
      kind: RowKind.station,
      name: pending.stop,
      arriveAt: pending.arriveAt,
      mode: pending.mode,
    ));
    if (pending.walk != null) {
      rows.add(TimelineRow(kind: RowKind.walk, step: pending.walk));
      rows.add(TimelineRow(
        kind: RowKind.station,
        name: destinationName.isEmpty ? '目的地' : destinationName,
        arriveAt: cursor,
      ));
    }
  }

  // 第一個／最後一個車站節點掛上「離開 / 到達」標籤
  final stationIdx = <int>[];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].kind == RowKind.station) stationIdx.add(i);
  }
  if (stationIdx.isNotEmpty) {
    rows[stationIdx.first] = rows[stationIdx.first].copyWith(isStart: true);
    rows[stationIdx.last] = rows[stationIdx.last].copyWith(isEnd: true);
  }

  return rows;
}

/// 對應 renderModeIcons：依出現順序取出不重複的運具
List<String> planModes(List<TransitStep> steps) {
  final modes = <String>[];
  for (final s in steps) {
    if (s.isRide && !modes.contains(s.mode)) modes.add(s.mode);
  }
  return modes;
}
