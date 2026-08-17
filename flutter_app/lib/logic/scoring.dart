// 推薦計分與五種排序，直譯自 transit/web/app.js。
//
// 這裡是純函式，沒有 UI 相依，所以可以用與 JS 版完全相同的測資驗證。

import '../api/models.dart';

/// 三個指標等權重，各佔三分之一。const 等同 JS 版的 Object.freeze。
class RecommendWeights {
  static const time = 1 / 3;
  static const fare = 1 / 3;
  static const transfer = 1 / 3;
}

double _normalize(num value, num min, num max) =>
    max == min ? 0 : (value - min) / (max - min);

/// 建立推薦分數計算函式。分數越低越推薦。
///
/// ★ 票價只有在「至少兩筆、且不全相同」時才拿來比較。
///   只有一筆時 _normalize 會回 0，等於把那唯一一筆判成最便宜——
///   但它其實只是唯一「知道價錢」的那筆，不代表真的比較便宜。
double Function(Plan) buildRecommendScorer(List<Plan> plans) {
  if (plans.isEmpty) return (_) => 0;

  final times = plans.map((p) => p.realSeconds).toList();
  final transfers = plans.map((p) => p.transferCount).toList();
  final fares = plans.map((p) => p.fare).whereType<num>().toList();

  final minTime = times.reduce((a, b) => a < b ? a : b);
  final maxTime = times.reduce((a, b) => a > b ? a : b);
  final minTransfer = transfers.reduce((a, b) => a < b ? a : b);
  final maxTransfer = transfers.reduce((a, b) => a > b ? a : b);
  final minFare = fares.isEmpty ? 0 : fares.reduce((a, b) => a < b ? a : b);
  final maxFare = fares.isEmpty ? 0 : fares.reduce((a, b) => a > b ? a : b);

  final fareComparable = fares.length >= 2 && maxFare > minFare;

  return (Plan plan) {
    final timeScore = _normalize(plan.realSeconds, minTime, maxTime);
    final transferScore = _normalize(plan.transferCount, minTransfer, maxTransfer);
    // 票價未知、或這批方案的票價無從比較時，一律給中性分數 0.5
    final fareScore = (plan.fare == null || !fareComparable)
        ? 0.5
        : _normalize(plan.fare!, minFare, maxFare);
    return RecommendWeights.time * timeScore +
        RecommendWeights.fare * fareScore +
        RecommendWeights.transfer * transferScore;
  };
}

const sortKeys = ['recommended', 'fastest', 'cheapest', 'fewest', 'live'];

const sortLabels = {
  'recommended': '推薦路線',
  'fastest': '最快路線',
  'cheapest': '票價較低',
  'fewest': '轉乘較少',
  'live': '即時優先',
};

/// 對應 app.js 的 sortPlans。回傳新的 list，不改動輸入。
List<Plan> sortPlans(List<Plan> plans, String sortKey) {
  final copy = [...plans];
  switch (sortKey) {
    case 'recommended':
      final score = buildRecommendScorer(copy);
      copy.sort((a, b) {
        final d = score(a).compareTo(score(b));
        return d != 0 ? d : a.realSeconds.compareTo(b.realSeconds);
      });
    case 'fastest':
      copy.sort((a, b) => a.realSeconds.compareTo(b.realSeconds));
    case 'fewest':
      copy.sort((a, b) {
        final d = a.transferCount.compareTo(b.transferCount);
        return d != 0 ? d : a.realSeconds.compareTo(b.realSeconds);
      });
    case 'cheapest':
      // 票價未知的方案一律排在所有已知票價之後
      num fareOf(Plan p) => p.fare ?? double.maxFinite;
      copy.sort((a, b) {
        final d = fareOf(a).compareTo(fareOf(b));
        return d != 0 ? d : a.realSeconds.compareTo(b.realSeconds);
      });
    case 'live':
      copy.sort((a, b) {
        final d = (b.isLive ? 1 : 0).compareTo(a.isLive ? 1 : 0);
        return d != 0 ? d : a.realSeconds.compareTo(b.realSeconds);
      });
  }
  return copy;
}
