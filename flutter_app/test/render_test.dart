// 實際把結果頁與詳情渲染出來，抓版面例外。
//
// 前幾輪一直用 HTTP 狀態碼當驗證標準，但 200 不代表畫面畫得出來。
// widget test 會在沒有瀏覽器的情況下真的跑一次 layout，
// 任何 RenderFlex overflow 或 constraint 錯誤都會讓測試失敗。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:transit_app/api/models.dart';
import 'package:transit_app/logic/timeline.dart';
import 'package:transit_app/ui/plan_detail.dart';
import 'package:transit_app/ui/results_view.dart';

TransitStep ride(String mode, String route, String from, String to,
        {int? wait, String platform = ''}) =>
    TransitStep(
      type: 'RIDE',
      seconds: 900,
      meters: 8600,
      mode: mode,
      routeName: route,
      fromStop: from,
      toStop: to,
      stopCount: 12,
      waitSeconds: wait,
      platform: platform,
      departAt: '',
      arriveAt: '',
    );

const walk = TransitStep(
  type: 'WALK',
  seconds: 180,
  meters: 220,
  mode: '',
  routeName: '',
  fromStop: '',
  toStop: '',
  stopCount: 0,
  waitSeconds: null,
  platform: '',
  departAt: '',
  arriveAt: '',
);

Plan plan({
  required List<TransitStep> steps,
  int real = 2100,
  int transfers = 1,
  num? fare = 50,
  bool live = true,
  int? wait = 120,
  String src = '即時',
}) =>
    Plan(
      totalSeconds: real,
      transferCount: transfers,
      steps: steps,
      polyline: '',
      waitSeconds: wait,
      waitSource: src,
      realSeconds: real,
      isLive: live,
      fare: fare,
      icFare: null,
    );

PlanResponse response(List<Plan> plans) => PlanResponse(
      queryTime: 0,
      plans: plans,
      googleOrder: plans.map((p) => p.realSeconds).toList(),
      reordered: false,
      nextPollSec: 60,
    );

Widget host(Widget child) => MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(child: child),
      ),
    );

void main() {
  final departAt = DateTime(2026, 8, 18, 9, 30);

  final samples = <String, Plan>{
    '單段捷運': plan(
      steps: [walk, ride('METRO', '淡水信義線', '台北車站', '淡水', platform: '2號月台'), walk],
      transfers: 0,
    ),
    '同站轉乘': plan(
      steps: [
        walk,
        ride('BUS', '307', '台北車站', '西門', wait: 120),
        ride('METRO', '板南線', '西門', '板橋', wait: 90),
        walk,
      ],
    ),
    '跨站轉乘（中間有步行）': plan(
      steps: [
        walk,
        ride('TRAIN', '區間車', '台北', '板橋'),
        walk,
        ride('BUS', '藍22', '板橋公車站', '樹林', wait: 300),
        walk,
      ],
    ),
    '票價未知 + 非即時': plan(
      steps: [ride('HSR', '台灣高鐵', '板橋', '新竹')],
      fare: null,
      live: false,
      wait: null,
      src: '末班已過',
      transfers: 0,
    ),
    '全程步行': plan(steps: [walk], transfers: 0, fare: null, wait: null, src: '班表推估'),
  };

  group('PlanDetail 能渲染各種方案而不拋例外', () {
    for (final entry in samples.entries) {
      testWidgets(entry.key, (tester) async {
        await tester.pumpWidget(host(PlanDetail(
          plan: entry.value,
          index: 0,
          departAt: departAt,
          destinationName: '淡水捷運站',
        )));
        expect(tester.takeException(), isNull);
      });
    }
  });

  group('ResultsView', () {
    testWidgets('多個方案能完整渲染', (tester) async {
      await tester.pumpWidget(host(ResultsView(
        data: response(samples.values.toList()),
        origin: '台北車站',
        destination: '淡水捷運站',
        departAt: departAt,
        timeMode: 'depart',
        currentSort: 'recommended',
        selectedIndex: 0,
        onSortChanged: (_) {},
        onSelect: (_) {},
        onBackToSearch: () {},
        onPrev: () {},
        onNext: () {},
      )));
      expect(tester.takeException(), isNull);
      // 五個排序頁籤都要在
      for (final label in ['推薦路線', '最快路線', '票價較低', '轉乘較少', '即時優先']) {
        expect(find.text(label), findsOneWidget, reason: '缺少頁籤 $label');
      }
      expect(find.text('台北車站'), findsWidgets);
    });

    testWidgets('五種排序都渲染得出來', (tester) async {
      for (final sort in ['recommended', 'fastest', 'cheapest', 'fewest', 'live']) {
        await tester.pumpWidget(host(ResultsView(
          data: response(samples.values.toList()),
          origin: '台北車站',
          destination: '淡水捷運站',
          departAt: departAt,
          timeMode: 'depart',
          currentSort: sort,
          selectedIndex: 0,
          onSortChanged: (_) {},
          onSelect: (_) {},
          onBackToSearch: () {},
          onPrev: () {},
          onNext: () {},
        )));
        expect(tester.takeException(), isNull, reason: '排序 $sort 渲染失敗');
      }
    });

    testWidgets('手機寬度（360px）不應 overflow', (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(host(ResultsView(
        data: response(samples.values.toList()),
        origin: '台北車站',
        destination: '淡水捷運站',
        departAt: departAt,
        timeMode: 'depart',
        currentSort: 'recommended',
        selectedIndex: 0,
        onSortChanged: (_) {},
        onSelect: (_) {},
        onBackToSearch: () {},
        onPrev: () {},
        onNext: () {},
      )));
      expect(tester.takeException(), isNull);
    });
  });

  group('時間軸一致性', _timelineConsistency);
}

// ── 時間軸與一覽表必須對得起來（本次修的 bug）──────────────────────────
void _timelineConsistency() {
  final departAt = DateTime(2026, 8, 18, 9, 0);

  /// 這是最重要的不變式：時刻表最後一站的抵達時刻，
  /// 必須等於一覽表顯示的抵達時刻（departAt + realSeconds）。
  void expectConsistent(Plan p, String label) {
    final rows = buildTimeline(p, departAt, '終點');
    final stations = rows.where((r) => r.kind == RowKind.station).toList();
    if (stations.isEmpty) return;
    expect(
      stations.last.arriveAt,
      departAt.add(Duration(seconds: p.realSeconds)),
      reason: '$label：時刻表抵達時刻與一覽表對不起來',
    );
  }

  test('無轉乘', () {
    expectConsistent(
      plan(steps: [walk, ride('METRO', '淡水信義線', 'A', 'B'), walk],
          transfers: 0, real: 180 + 900 + 180),
      '無轉乘',
    );
  });

  test('一次轉乘，Google 內含轉乘等待', () {
    // 各步驟加總 2160，realSeconds 多 300 秒 = Google 內含的轉乘等待
    expectConsistent(
      plan(steps: [
        walk,
        ride('BUS', '307', 'A', 'B'),
        ride('METRO', '板南線', 'B', 'C'),
        walk,
      ], real: 180 + 900 + 900 + 180 + 300),
      '一次轉乘',
    );
  });

  test('兩次轉乘，差額要平均分配且總和不變', () {
    expectConsistent(
      plan(steps: [
        ride('BUS', '307', 'A', 'B'),
        ride('METRO', '板南線', 'B', 'C'),
        ride('BUS', '藍22', 'C', 'D'),
      ], transfers: 2, real: 900 * 3 + 301), // 301 除以 2 除不盡，測餘數處理
      '兩次轉乘',
    );
  });

  test('第一段有即時候車時也要一致', () {
    expectConsistent(
      plan(steps: [
        walk,
        ride('BUS', '307', 'A', 'B', wait: 120),
        ride('METRO', '板南線', 'B', 'C', wait: 1800),
        walk,
      ], real: 180 + 900 + 900 + 180 + 120 + 300),
      '含即時候車',
    );
  });

  test('★ 轉乘段的 TDX 即時候車不得推進時間軸', () {
    // 轉乘段 waitSeconds=1800（來自 TDX「從現在算」），不得被加進去
    final p = plan(steps: [
      ride('BUS', '307', 'A', 'B', wait: 120),
      ride('METRO', '板南線', 'B', 'C', wait: 1800),
    ], real: 900 + 900 + 120);
    final rows = buildTimeline(p, departAt, 'C');
    final last = rows.lastWhere((r) => r.kind == RowKind.station);
    expect(last.arriveAt, departAt.add(const Duration(seconds: 900 + 900 + 120)),
        reason: '轉乘段的 1800 秒不該出現在時間軸上');
  });

  test('第一段的候車仍然要算進去', () {
    final p = plan(steps: [ride('BUS', '307', 'A', 'B', wait: 300)],
        transfers: 0, real: 900 + 300);
    final rows = buildTimeline(p, departAt, 'B');
    final first = rows.firstWhere((r) => r.kind == RowKind.station);
    expect(first.departAt, departAt.add(const Duration(seconds: 300)));
    expect(first.waitIsActionable, isTrue);
  });

  test('轉乘段標記為不可行動（文案要不一樣）', () {
    final p = plan(steps: [
      ride('BUS', '307', 'A', 'B', wait: 120),
      ride('METRO', '板南線', 'B', 'C', wait: 1800),
    ]);
    final stations = buildTimeline(p, departAt, 'C')
        .where((r) => r.kind == RowKind.station && r.waitSeconds != 0)
        .toList();
    expect(stations.first.waitIsActionable, isTrue);
    expect(stations.last.waitIsActionable, isFalse);
  });
}
