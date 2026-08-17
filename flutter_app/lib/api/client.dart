// 後端 API 客戶端，含自動更新輪詢。
//
// 對應 transit/web/app.js 的 buildUrl / runSearch / refreshPlans /
// startPolling / stopPolling 與 visibilitychange 處理。

import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;

import 'models.dart';

/// 後端位置。空字串 = 相對路徑（前端與 API 同源時使用）。
///
/// Flutter 建置產物若放進 Cloud Run 服務的 /app 路徑，就與 API 同源，
/// 這裡維持空字串即可。開發期從別的 port 打線上 API 時填完整網址——
/// 後端的 CORS 是 allow_origins=["*"]，跨來源沒問題。
const apiBase = String.fromEnvironment('API_BASE', defaultValue: '');

const defaultPollSeconds = 30;

class TransitApi {
  final http.Client _http;
  TransitApi([http.Client? client]) : _http = client ?? http.Client();

  Uri _url(String origin, String destination) {
    final path = '/api/plans';
    final query = {'origin': origin, 'destination': destination};
    if (apiBase.isEmpty) {
      // 相對路徑：沿用目前頁面的 scheme/host
      return Uri.base.replace(path: path, queryParameters: query);
    }
    final base = Uri.parse(apiBase);
    return base.replace(
      path: '${base.path.replaceAll(RegExp(r'/$'), '')}$path',
      queryParameters: query,
    );
  }

  Future<PlanResponse> fetchPlans(String origin, String destination) async {
    final res = await _http.get(_url(origin, destination));
    if (res.statusCode != 200) {
      throw HttpException('HTTP ${res.statusCode}');
    }
    // 後端一律回 UTF-8 JSON；用 bodyBytes 解碼避免中文變亂碼
    final decoded = jsonDecode(utf8.decode(res.bodyBytes));
    if (decoded is! Map<String, dynamic>) {
      throw const HttpException('回應格式不正確');
    }
    return PlanResponse.fromJson(decoded);
  }
}

class HttpException implements Exception {
  final String message;
  const HttpException(this.message);
  @override
  String toString() => message;
}

/// 自動更新的計時器管理。
///
/// 三個行為與網頁版一致：
///   1. in-flight 旗標，避免慢回應堆疊成多個請求
///   2. 分頁隱藏時暫停，切回前景立刻更新一次再繼續
///   3. 失敗時不動畫面（由呼叫端決定），下一輪自然會再試
///
/// ★ 分頁可見性用 Flutter 的 AppLifecycleState 而不是 dart:html。
///   dart:html 已棄用，而且綁死 Web；用 lifecycle 的話同一份程式碼
///   之後要建 Android APK 也能直接運作。
class PollController {
  final Future<void> Function() onTick;
  Timer? _timer;
  int _seconds = defaultPollSeconds;
  bool _busy = false;

  PollController(this.onTick);

  int get seconds => _seconds;
  bool get isRunning => _timer != null;

  void start({int? seconds}) {
    if (seconds != null && seconds > 0) _seconds = seconds;
    stop();
    _timer = Timer.periodic(Duration(seconds: _seconds), (_) => _run());
  }

  /// 由 UI 層的 WidgetsBindingObserver 呼叫。
  void onLifecycle(AppLifecycleState state) {
    final visible = state == AppLifecycleState.resumed;
    if (!visible) {
      stop();
    } else {
      _run(); // 切回前景先更新一次，看到的才不是 30 秒前的資料
      start();
    }
  }

  Future<void> _run() async {
    if (_busy) return;
    _busy = true;
    try {
      await onTick();
    } finally {
      _busy = false;
    }
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  void dispose() => stop();
}
