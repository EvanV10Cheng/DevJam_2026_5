// 對應 README §3 的凍結契約。
//
// ★ 契約的硬性規則：所有欄位一律存在，就算值是 null。
//   README 特別提醒過 Dart 的風險——jsonDecode 給 null、當成 int 用就直接
//   拋 exception，App 當場閃退。所以這裡每個可能為 null 的欄位都宣告成
//   可空型別，並用 _asInt / _asNum 做防禦性轉換。

int _asInt(dynamic v, [int fallback = 0]) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? fallback;
  return fallback;
}

int? _asIntOrNull(dynamic v) {
  if (v == null) return null;
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v);
  return null;
}

/// 票價：可能是 int、double 或 null。
/// 對應 app.js 的 toFare —— null/空字串/NaN/負數一律視為未知。
num? asFare(dynamic v) {
  if (v == null) return null;
  if (v is num) return (v.isFinite && v >= 0) ? v : null;
  if (v is String) {
    if (v.isEmpty) return null;
    final n = num.tryParse(v);
    return (n != null && n.isFinite && n >= 0) ? n : null;
  }
  return null;
}

String _asStr(dynamic v, [String fallback = '']) => v is String ? v : fallback;

class TransitStep {
  final String type; // WALK | RIDE
  final int seconds;
  final int meters;

  // 以下只有 RIDE 才有意義
  final String mode; // BUS | METRO | TRAIN | HSR
  final String routeName;
  final String fromStop;
  final String toStop;
  final int stopCount;
  final int? waitSeconds;
  final String platform;
  final String departAt;
  final String arriveAt;

  const TransitStep({
    required this.type,
    required this.seconds,
    required this.meters,
    required this.mode,
    required this.routeName,
    required this.fromStop,
    required this.toStop,
    required this.stopCount,
    required this.waitSeconds,
    required this.platform,
    required this.departAt,
    required this.arriveAt,
  });

  bool get isRide => type == 'RIDE';

  factory TransitStep.fromJson(Map<String, dynamic> j) => TransitStep(
        type: _asStr(j['type'], 'WALK'),
        seconds: _asInt(j['seconds']),
        meters: _asInt(j['meters']),
        mode: _asStr(j['mode']),
        routeName: _asStr(j['routeName']),
        fromStop: _asStr(j['fromStop']),
        toStop: _asStr(j['toStop']),
        stopCount: _asInt(j['stopCount']),
        waitSeconds: _asIntOrNull(j['waitSeconds']),
        platform: _asStr(j['platform']),
        departAt: _asStr(j['departAt']),
        arriveAt: _asStr(j['arriveAt']),
      );
}

class Plan {
  final int totalSeconds;
  final int transferCount;
  final List<TransitStep> steps;
  final String polyline;
  final int? waitSeconds;
  final String waitSource;
  final int realSeconds;
  final bool isLive;
  final num? fare;
  final num? icFare;

  const Plan({
    required this.totalSeconds,
    required this.transferCount,
    required this.steps,
    required this.polyline,
    required this.waitSeconds,
    required this.waitSource,
    required this.realSeconds,
    required this.isLive,
    required this.fare,
    required this.icFare,
  });

  factory Plan.fromJson(Map<String, dynamic> j) => Plan(
        totalSeconds: _asInt(j['totalSeconds']),
        transferCount: _asInt(j['transferCount']),
        steps: ((j['steps'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(TransitStep.fromJson)
            .toList(),
        polyline: _asStr(j['polyline']),
        waitSeconds: _asIntOrNull(j['waitSeconds']),
        waitSource: _asStr(j['waitSource'], '班表推估'),
        realSeconds: _asInt(j['realSeconds']),
        isLive: j['isLive'] == true,
        fare: asFare(j['fare']),
        icFare: asFare(j['icFare']),
      );

  List<TransitStep> get rides => steps.where((s) => s.isRide).toList();

  /// 方案的識別碼：搭哪幾班車、從哪站到哪站。
  /// 對應 app.js 的 planSignature —— 重新排序後用它找回使用者原本選的方案。
  String get signature =>
      rides.map((s) => '${s.mode}|${s.routeName}|${s.fromStop}|${s.toStop}').join('>>');
}

class PlanResponse {
  final int queryTime;
  final List<Plan> plans;
  final List<int> googleOrder;
  final bool reordered;
  final int nextPollSec;

  const PlanResponse({
    required this.queryTime,
    required this.plans,
    required this.googleOrder,
    required this.reordered,
    required this.nextPollSec,
  });

  factory PlanResponse.fromJson(Map<String, dynamic> j) => PlanResponse(
        queryTime: _asInt(j['queryTime']),
        plans: ((j['plans'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(Plan.fromJson)
            .toList(),
        googleOrder:
            ((j['googleOrder'] as List?) ?? const []).map((e) => _asInt(e)).toList(),
        reordered: j['reordered'] == true,
        // 後端沒給就用 30 秒，與 app.js 的 DEFAULT_POLL_MS 一致
        nextPollSec: _asInt(j['nextPollSec'], 30),
      );
}
