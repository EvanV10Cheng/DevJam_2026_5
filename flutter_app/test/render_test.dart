// 實際把結果頁與詳情渲染出來，抓版面例外。
//
// 前幾輪一直用 HTTP 狀態碼當驗證標準，但 200 不代表畫面畫得出來。
// widget test 會在沒有瀏覽器的情況下真的跑一次 layout，
// 任何 RenderFlex overflow 或 constraint 錯誤都會讓測試失敗。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:transit_app/api/models.dart';
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
}
