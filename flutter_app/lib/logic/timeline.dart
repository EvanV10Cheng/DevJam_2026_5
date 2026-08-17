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

  /// 這個候車時間是不是「你現在真的要等的」。
  ///
  /// 只有第一段搭乘是 true。轉乘段的 waitSeconds 來自 TDX 的 EstimateTime，
  /// 那是「從查詢當下算起」的數字——你要三十分鐘後才會抵達轉乘站，
  /// 那班車早就開走了，拿它推算未來時刻在數學上不成立。
  final bool waitIsActionable;
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
    this.waitIsActionable = false,
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
        waitIsActionable: waitIsActionable,
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
  var seenRide = false; // 用來判斷這是不是第一段搭乘

  // ★ Google 的 totalSeconds 比各步驟 staticDuration 的加總還大，
  //   差額就是它內含的「轉乘等待」——任何單一步驟裡都沒有這段時間
  //   （實測：加總 1919s、totalSeconds 2154s，差 235s；
  //    Google 自己的時刻也顯示上段 23:34:30 抵達、下段 23:39:35 發車）。
  //   把這個差額補在轉乘點上，時刻表的總和才會等於一覽表的 realSeconds。
  final rides = plan.rides;
  final transferCount = rides.length > 1 ? rides.length - 1 : 0;
  final stepTotal = plan.steps.fold<int>(0, (a, s) => a + s.seconds);
  final firstWait = rides.isEmpty ? 0 : (rides.first.waitSeconds ?? 0);
  final slack = plan.realSeconds - stepTotal - firstWait;
  final perTransfer = (transferCount > 0 && slack > 0) ? slack ~/ transferCount : 0;
  // 除不盡的餘數補在最後一個轉乘點，總和才會完全相等
  final remainder = (transferCount > 0 && slack > 0) ? slack % transferCount : 0;
  var transferSeen = 0;

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
    // ★ 只有第一段的候車會推進時間軸。
    //   轉乘段的候車是「從現在算起」的即時值，加進去會產生不存在的班次時刻，
    //   而且會讓時刻表的抵達時間比一覽表多出十幾二十分鐘（實測 +16 ~ +28 分）。
    final actionable = !seenRide;
    int advance;
    if (actionable) {
      advance = waitSeconds; // 第一段：用 TDX 的即時候車，那個是真的
    } else {
      // 轉乘段：用 Google 內含的轉乘等待，不用 TDX 的即時值
      transferSeen++;
      advance = perTransfer + (transferSeen == transferCount ? remainder : 0);
    }
    final departTime = cursor.add(Duration(seconds: advance));
    final arriveTime = departTime.add(Duration(seconds: step.seconds));
    seenRide = true;

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
        waitIsActionable: actionable,
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
        waitIsActionable: actionable,
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
