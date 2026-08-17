// 用與 JS 版完全相同的測資驗證排序邏輯。
// 對照組是 transit/web/app.js 那輪 QuickJS 測試的 17 個案例。

import 'package:flutter_test/flutter_test.dart';
import 'package:transit_app/api/models.dart';
import 'package:transit_app/logic/format.dart';
import 'package:transit_app/logic/scoring.dart';

Plan mk({
  int real = 1000,
  int transfers = 0,
  num? fare,
  bool live = false,
  List<List<String>> rides = const [],
}) =>
    Plan(
      totalSeconds: real,
      transferCount: transfers,
      steps: rides
          .map((r) => TransitStep(
                type: 'RIDE',
                seconds: 600,
                meters: 1000,
                mode: r[0],
                routeName: r[1],
                fromStop: r[2],
                toStop: r[3],
                stopCount: 5,
                waitSeconds: null,
                platform: '',
                departAt: '',
                arriveAt: '',
              ))
          .toList(),
      polyline: '',
      waitSeconds: null,
      waitSource: '班表推估',
      realSeconds: real,
      isLive: live,
      fare: fare,
      icFare: null,
    );

void main() {
  group('asFare（對應 JS 的 toFare）', () {
    test('null / 空字串 / 負數 / 非數字都視為未知', () {
      expect(asFare(null), isNull);
      expect(asFare(''), isNull);
      expect(asFare(-5), isNull);
      expect(asFare('abc'), isNull);
      expect(asFare(double.nan), isNull);
    });
    test('有效值', () {
      expect(asFare(0), 0); // 0 元是有效票價，不是未知
      expect(asFare('45'), 45);
      expect(asFare(45.5), 45.5);
    });
  });

  group('推薦計分', () {
    test('權重總和為 1、各佔三分之一', () {
      const sum =
          RecommendWeights.time + RecommendWeights.fare + RecommendWeights.transfer;
      expect(sum, closeTo(1, 1e-9));
      expect(RecommendWeights.fare, closeTo(1 / 3, 1e-9));
    });

    test('★ 只有一筆票價時，不得把那筆判成最便宜', () {
      final plans = [mk(fare: 50), mk(fare: null)];
      final score = buildRecommendScorer(plans);
      expect(score(plans[0]), closeTo(score(plans[1]), 1e-9));
    });

    test('票價全部相同時也不比較', () {
      final plans = [mk(fare: 50), mk(fare: 50)];
      final score = buildRecommendScorer(plans);
      expect(score(plans[0]), closeTo(score(plans[1]), 1e-9));
    });

    test('兩筆不同票價才比較高低', () {
      final plans = [mk(fare: 20), mk(fare: 80)];
      final score = buildRecommendScorer(plans);
      expect(score(plans[0]), lessThan(score(plans[1])));
    });
  });

  group('sortPlans', () {
    test('票價較低：未知票價排在所有已知之後', () {
      final plans = [mk(real: 900, fare: null), mk(real: 800, fare: 60), mk(real: 700, fare: 30)];
      expect(sortPlans(plans, 'cheapest').map((p) => p.fare).toList(), [30, 60, null]);
    });

    test('最快 / 轉乘較少 / 即時優先', () {
      final plans = [
        mk(real: 900, transfers: 2, live: false),
        mk(real: 700, transfers: 1, live: true),
      ];
      expect(sortPlans(plans, 'fastest').map((p) => p.realSeconds).toList(), [700, 900]);
      expect(sortPlans(plans, 'fewest').map((p) => p.transferCount).toList(), [1, 2]);
      expect(sortPlans(plans, 'live').first.isLive, isTrue);
    });

    test('不改動輸入的 list', () {
      final plans = [mk(real: 900), mk(real: 700)];
      sortPlans(plans, 'fastest');
      expect(plans.first.realSeconds, 900);
    });
  });

  group('planSignature', () {
    test('同路線不同時間 → 相同簽章；不同路線 → 不同', () {
      final a = mk(real: 1000, rides: [['BUS', '307', '台北', '西門']]);
      final b = mk(real: 2000, rides: [['BUS', '307', '台北', '西門']]);
      final c = mk(rides: [['METRO', '板南線', '台北', '板橋']]);
      expect(a.signature, b.signature);
      expect(a.signature, isNot(c.signature));
    });

    test('全程步行 → 空字串', () => expect(mk().signature, ''));

    test('重排後仍能定位回原方案', () {
      final metro = mk(real: 1000, rides: [['METRO', '板南線', '台北', '板橋']]);
      final bus = mk(real: 1000, rides: [['BUS', '307', '台北', '西門']]);
      final keep = bus.signature;
      // 更新後 307 變快了，排到第 0
      final faster = mk(real: 500, rides: [['BUS', '307', '台北', '西門']]);
      final after = sortPlans([metro, faster], 'fastest');
      expect(after.indexWhere((p) => p.signature == keep), 0);
    });
  });

  group('格式化（對照 app.js 同名函式）', () {
    test('formatDuration', () {
      expect(formatDuration(1800), '30 分鐘');
      expect(formatDuration(3600), '1 小時');
      expect(formatDuration(4500), '1 小時 15 分鐘');
    });
    test('formatMeters', () {
      expect(formatMeters(0), '');
      expect(formatMeters(510), '510 公尺');
      expect(formatMeters(21500), '21.5 公里');
    });
    test('formatFare', () {
      expect(formatFare(null), '—');
      expect(formatFare(50), 'NT\$50');
      expect(formatFare(45.5), 'NT\$45.5');
    });
    test('formatClock 補零', () {
      expect(formatClock(DateTime(2026, 8, 18, 9, 5)), '09:05');
      expect(formatClock(DateTime(2026, 8, 18, 0, 27)), '00:27');
    });
    test('formatQueryBarLabel 的上下午與星期', () {
      // 2026-08-18 是星期二
      expect(formatQueryBarLabel(DateTime(2026, 8, 18, 9, 30), 'depart'),
          '2026年8月18日（星期二）上午9:30出發');
      expect(formatQueryBarLabel(DateTime(2026, 8, 18, 13, 5), 'arrive'),
          '2026年8月18日（星期二）下午1:05到達');
      // 午夜要顯示 12 而不是 0
      expect(formatQueryBarLabel(DateTime(2026, 8, 18, 0, 0), 'depart'),
          '2026年8月18日（星期二）上午12:00出發');
    });
  });

  group('契約防禦（README §3：欄位一律存在，值可能是 null）', () {
    test('缺欄位不應拋例外', () {
      final p = Plan.fromJson({});
      expect(p.realSeconds, 0);
      expect(p.fare, isNull);
      expect(p.waitSource, '班表推估');
      expect(p.steps, isEmpty);
    });
    test('null 值不會被當成數字使用', () {
      final p = Plan.fromJson({'waitSeconds': null, 'fare': null, 'isLive': null});
      expect(p.waitSeconds, isNull);
      expect(p.fare, isNull);
      expect(p.isLive, isFalse);
    });
    test('nextPollSec 缺少時用預設 30', () {
      expect(PlanResponse.fromJson({'plans': []}).nextPollSec, 30);
    });
  });
}
