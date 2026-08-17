// 大台北即時轉乘 — Flutter Web
//
// 對應 transit/web/app.js 的 runSearch / refreshPlans / 輪詢生命週期。
// 契約完全沿用後端既有的 /api/plans（README §3），後端一行都不用改。

import 'package:flutter/material.dart';

import 'api/client.dart';
import 'api/models.dart';
import 'logic/scoring.dart';
import 'theme/tokens.dart';
import 'ui/results_view.dart';
import 'ui/search_view.dart';

void main() => runApp(const TransitApp());

class TransitApp extends StatelessWidget {
  const TransitApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: '大台北即時轉乘系統',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          scaffoldBackgroundColor: T.paper,
          fontFamily: T.fontBody,
          colorScheme: ColorScheme.fromSeed(
            seedColor: T.railBlue,
            surface: T.paper,
          ),
        ),
        home: const HomePage(),
      );
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  final _api = TransitApi();
  final _originCtrl = TextEditingController(text: '台北車站');
  final _destCtrl = TextEditingController(text: '淡水捷運站');

  late final PollController _poll;

  DateTime _dateTime = DateTime.now();
  final String _timeMode = 'depart';

  PlanResponse? _data;
  String _searchedOrigin = '';
  String _searchedDestination = '';
  String _currentSort = 'recommended';
  int _selectedIndex = 0;

  bool _loading = false;
  String? _error;
  bool _empty = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _poll = PollController(_refresh);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll.dispose();
    _originCtrl.dispose();
    _destCtrl.dispose();
    super.dispose();
  }

  /// 分頁切走暫停、切回來立刻更新一次。對應網頁版的 visibilitychange。
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (_data != null) _poll.onLifecycle(state);
  }

  Future<void> _search() async {
    final origin = _originCtrl.text.trim();
    final destination = _destCtrl.text.trim();
    if (origin.isEmpty || destination.isEmpty) {
      setState(() => _error = '請輸入出發站與到達站');
      return;
    }

    _poll.stop(); // 新查詢開始前先停掉舊的輪詢，避免兩組結果互相蓋
    setState(() {
      _loading = true;
      _error = null;
      _empty = false;
      // 主動發起的新查詢才重設排序與選取
      _currentSort = 'recommended';
      _selectedIndex = 0;
    });

    try {
      final res = await _api.fetchPlans(origin, destination);
      if (!mounted) return;
      if (res.plans.isEmpty) {
        setState(() {
          _data = null;
          _empty = true;
        });
        return;
      }
      setState(() {
        _data = res;
        _searchedOrigin = origin;
        _searchedDestination = destination;
      });
      _poll.start(seconds: res.nextPollSec);
    } catch (e) {
      if (mounted) setState(() => _error = '查詢失敗，請稍後再試');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// 自動更新：不顯示載入中、不重設排序與選取、失敗時保留舊資料。
  Future<void> _refresh() async {
    if (_searchedOrigin.isEmpty || _searchedDestination.isEmpty) return;

    // 先記下目前選的是「哪一個方案」，重排後才找得回來
    final sortedNow = sortPlans(_data?.plans ?? const [], _currentSort);
    final keepSig =
        _selectedIndex < sortedNow.length ? sortedNow[_selectedIndex].signature : null;

    try {
      final res = await _api.fetchPlans(_searchedOrigin, _searchedDestination);
      if (!mounted || res.plans.isEmpty) return;

      // 重排後把選取移回原本那個方案
      var idx = _selectedIndex;
      if (keepSig != null) {
        final resorted = sortPlans(res.plans, _currentSort);
        final found = resorted.indexWhere((p) => p.signature == keepSig);
        idx = found >= 0 ? found : 0;
      }

      setState(() {
        _data = res;
        _selectedIndex = idx;
      });

      if (res.nextPollSec != _poll.seconds) {
        _poll.start(seconds: res.nextPollSec); // 後端改了間隔就跟著調整
      }
    } catch (_) {
      // ★ 失敗時什麼都不動。網路抖一下就把查詢結果清成空白是很糟的體驗，
      //   反正下一輪還會再試。
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return Scaffold(
      body: Column(
        children: [
          const AppHeader(),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: T.pageMaxWidth),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // ★ 有結果時搜尋卡整個隱藏，只顯示結果頁。
                      //   對應網頁版 showResultsView() 的 searchView.hidden = true——
                      //   原本兩個疊著顯示是移植錯誤，畫面會跟原版不一樣。
                      if (data == null)
                        SearchView(
                          originCtrl: _originCtrl,
                          destCtrl: _destCtrl,
                          dateTime: _dateTime,
                          timeMode: _timeMode,
                          loading: _loading,
                          error: _error,
                          onSwap: () {
                            final a = _originCtrl.text;
                            _originCtrl.text = _destCtrl.text;
                            _destCtrl.text = a;
                            setState(() {});
                          },
                          onSubmit: _search,
                          onDateTimeChanged: (d) => setState(() => _dateTime = d),
                          onQuickPick: (o, d) {
                            _originCtrl.text = o;
                            _destCtrl.text = d;
                            _search();
                          },
                        ),
                      if (data == null && _empty)
                        const Padding(
                          padding: EdgeInsets.symmetric(vertical: 32),
                          child: Text('找不到路線，換個地點再試試。',
                              textAlign: TextAlign.center,
                              style: TextStyle(color: T.inkSoft)),
                        ),
                      if (data != null) ...[
                        ResultsView(
                          data: data,
                          origin: _searchedOrigin,
                          destination: _searchedDestination,
                          departAt: _dateTime,
                          timeMode: _timeMode,
                          currentSort: _currentSort,
                          selectedIndex: _selectedIndex,
                          onSortChanged: (k) => setState(() {
                            _currentSort = k;
                            _selectedIndex = 0;
                          }),
                          onSelect: (i) => setState(() => _selectedIndex = i),
                          onBackToSearch: () => setState(() {
                            _data = null;
                            _poll.stop();
                          }),
                          onPrev: () => _shift(-15),
                          onNext: () => _shift(15),
                        ),
                      ],
                      const SizedBox(height: 32),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 前／後幾班車：把查詢時刻前後推 15 分鐘再查一次。對應 shiftQueryTime。
  void _shift(int minutes) {
    setState(() => _dateTime = _dateTime.add(Duration(minutes: minutes)));
    _search();
  }
}
