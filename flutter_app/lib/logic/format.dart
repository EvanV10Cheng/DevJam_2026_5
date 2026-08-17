// 格式化函式，逐一對照 transit/web/app.js 的同名函式。
//
// 刻意保留 JS 版的行為細節（四捨五入方式、單位切換門檻、全形字），
// 兩邊畫面才會長得一樣。

import '../api/models.dart';

const weekdays = ['日', '一', '二', '三', '四', '五', '六'];

/// formatClock：24 小時制的 HH:MM
String formatClock(DateTime d) =>
    '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

/// formatDuration：未滿一小時只顯示分鐘，超過才拆成「N 小時 M 分鐘」
String formatDuration(int seconds) {
  final mins = (seconds / 60).round();
  if (mins < 60) return '$mins 分鐘';
  final h = mins ~/ 60;
  final m = mins % 60;
  return m != 0 ? '$h 小時 $m 分鐘' : '$h 小時';
}

/// formatMeters：1 公里以上換算成公里並取一位小數；0 回空字串
String formatMeters(int meters) {
  if (meters == 0) return '';
  return meters >= 1000
      ? '${(meters / 1000).toStringAsFixed(1)} 公里'
      : '$meters 公尺';
}

/// formatFare：未知票價顯示破折號，不顯示 0
String formatFare(num? value) {
  if (value == null) return '—';
  // JS 的 `NT$${45}` 會印 45、`NT$${45.5}` 會印 45.5，Dart 要自己處理
  final s = value is int || value == value.roundToDouble()
      ? value.toInt().toString()
      : value.toString();
  return 'NT\$$s';
}

const timeModeLabels = {
  'depart': '出發',
  'arrive': '到達',
  'first': '首班',
  'last': '末班',
};

/// formatQueryBarLabel：「2026年8月18日（星期一）上午9:30出發」
String formatQueryBarLabel(DateTime dt, String timeMode) {
  final wd = weekdays[dt.weekday % 7]; // Dart 的 weekday 是 1..7（週一起算）
  final period = dt.hour < 12 ? '上午' : '下午';
  final h12 = dt.hour == 0 ? 12 : (dt.hour > 12 ? dt.hour - 12 : dt.hour);
  final mm = dt.minute.toString().padLeft(2, '0');
  final mode = timeModeLabels[timeMode] ?? '出發';
  return '${dt.year}年${dt.month}月${dt.day}日（星期$wd）$period$h12:$mm$mode';
}

/// getPlanTimes：出發時刻 + realSeconds = 抵達時刻
({DateTime start, DateTime end}) getPlanTimes(Plan plan, DateTime departAt) {
  final end = departAt.add(Duration(seconds: plan.realSeconds));
  return (start: departAt, end: end);
}

/// getTotalMeters：整條方案的總距離
int getTotalMeters(List<TransitStep> steps) =>
    steps.fold(0, (sum, s) => sum + s.meters);
