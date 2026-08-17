// 搜尋卡：hero 輪播、起訖輸入（含站名建議）、日期時間、搜尋紀錄、運具圖例。
// 對應 index.html 的 #searchView 與 app.js 的 attachAutocomplete / 日期時間那幾個函式。

import 'dart:async';

import 'package:flutter/material.dart';

import '../logic/format.dart';
import '../theme/tokens.dart';

/// 站名推薦清單，與 app.js 的 STATIONS 完全相同。
const stations = [
  '台北車站', '台北 101', '士林夜市', '淡水捷運站', '新竹高鐵站',
  '西門町', '中山站', '板橋車站', '松山車站', '南港車站',
  '士林站', '北投站', '天母', '內湖', '松山機場',
  '桃園機場', '三重', '蘆洲', '新店', '永和',
  '中和', '大安森林公園站', '東門站', '忠孝復興站', '忠孝敦化站',
  '市政府站', '北車', '頂溪站', '景美站', '公館站',
  '古亭站', '大直', '劍潭站', '關渡', '紅樹林',
];

/// hero 背景輪播：四張圖交叉淡入淡出。
/// 對應 style.css 的 .hero-carousel 與那唯一一組 @keyframes。
class HeroCarousel extends StatefulWidget {
  const HeroCarousel({super.key});
  @override
  State<HeroCarousel> createState() => _HeroCarouselState();
}

class _HeroCarouselState extends State<HeroCarousel> {
  static const _images = [
    'assets/mrt.jpg',
    'assets/bus.jpg',
    'assets/high.jpg',
    'assets/train.jpg',
  ];
  int _index = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 6), (_) {
      if (mounted) setState(() => _index = (_index + 1) % _images.length);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(T.radiusXl),
        child: SizedBox(
          height: 210,
          width: double.infinity,
          child: Stack(
            fit: StackFit.expand,
            children: [
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 1200),
                switchInCurve: T.ease,
                switchOutCurve: T.ease,
                child: Image.asset(
                  _images[_index],
                  key: ValueKey(_index),
                  fit: BoxFit.cover,
                  // 圖片載入前先鋪底色，避免閃白
                  errorBuilder: (_, _, _) => Container(color: T.railBlueDark),
                ),
              ),
              // 對應 .hero-carousel__overlay 的深色漸層
              Container(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      T.railBlueDark.withValues(alpha: 0.55),
                      T.railBlueDark.withValues(alpha: 0.25),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}

class SearchView extends StatelessWidget {
  final TextEditingController originCtrl;
  final TextEditingController destCtrl;
  final DateTime dateTime;
  final String timeMode;
  final bool loading;
  final String? error;
  final VoidCallback onSwap;
  final VoidCallback onSubmit;
  final ValueChanged<DateTime> onDateTimeChanged;
  final void Function(String origin, String destination) onQuickPick;

  const SearchView({
    super.key,
    required this.originCtrl,
    required this.destCtrl,
    required this.dateTime,
    required this.timeMode,
    required this.loading,
    required this.error,
    required this.onSwap,
    required this.onSubmit,
    required this.onDateTimeChanged,
    required this.onQuickPick,
  });

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const HeroCarousel(),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: T.paperCard,
              borderRadius: BorderRadius.circular(T.radiusXl),
              border: Border.all(color: T.line),
              boxShadow: T.shadowMd,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _stationsRow(context),
                const SizedBox(height: 12),
                _dateRow(context),
                const SizedBox(height: 8),
                _timeRow(context),
                const SizedBox(height: 14),
                _submitButton(),
                if (error != null) ...[
                  const SizedBox(height: 8),
                  Text(error!,
                      style: const TextStyle(color: T.hsr, fontSize: 13)),
                ],
                const SizedBox(height: 16),
                _quickExamples(),
              ],
            ),
          ),
          const SizedBox(height: 12),
          _modeLegend(),
        ],
      );

  Widget _stationsRow(BuildContext context) => Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(child: _stationField(originCtrl, '出發站', T.railBlue)),
          IconButton(
            onPressed: onSwap,
            tooltip: '交換出發與到達',
            icon: const Icon(Icons.swap_horiz, color: T.railBlue),
          ),
          Expanded(child: _stationField(destCtrl, '到達站', T.destination)),
        ],
      );

  /// 對應 attachAutocomplete：輸入時即時比對 STATIONS，最多顯示 8 筆
  Widget _stationField(TextEditingController ctrl, String label, Color pill) =>
      Autocomplete<String>(
        optionsBuilder: (v) {
          final q = v.text.trim();
          if (q.isEmpty) return const Iterable<String>.empty();
          return stations.where((s) => s.contains(q)).take(8);
        },
        onSelected: (s) => ctrl.text = s,
        fieldViewBuilder: (context, textCtrl, focus, onSubmit) {
          // 讓外部 controller 與 Autocomplete 內部的保持同步
          if (textCtrl.text != ctrl.text) textCtrl.text = ctrl.text;
          return TextField(
            controller: textCtrl,
            focusNode: focus,
            onChanged: (v) => ctrl.text = v,
            onSubmitted: (_) => onSubmit(),
            decoration: InputDecoration(
              isDense: true,
              hintText: '輸入車站或地標',
              prefixIcon: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                      color: pill, borderRadius: BorderRadius.circular(T.radiusSm)),
                  child: Text(label,
                      style: const TextStyle(
                          color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
                ),
              ),
              prefixIconConstraints: const BoxConstraints(minWidth: 0),
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(T.radiusMd),
                borderSide: const BorderSide(color: T.line),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(T.radiusMd),
                borderSide: const BorderSide(color: T.line),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(T.radiusMd),
                borderSide: const BorderSide(color: T.lineStrong, width: 2),
              ),
            ),
          );
        },
      );

  Widget _dateRow(BuildContext context) => Row(
        children: [
          const SizedBox(width: 44, child: Text('日期', style: TextStyle(color: T.inkSoft))),
          OutlinedButton.icon(
            onPressed: () async {
              final picked = await showDatePicker(
                context: context,
                initialDate: dateTime,
                firstDate: DateTime.now().subtract(const Duration(days: 1)),
                lastDate: DateTime.now().add(const Duration(days: 90)),
              );
              if (picked != null) {
                onDateTimeChanged(DateTime(
                    picked.year, picked.month, picked.day, dateTime.hour, dateTime.minute));
              }
            },
            icon: const Icon(Icons.calendar_today, size: 15),
            label: Text('${dateTime.year}-${dateTime.month.toString().padLeft(2, '0')}'
                '-${dateTime.day.toString().padLeft(2, '0')}'),
          ),
        ],
      );

  Widget _timeRow(BuildContext context) => Row(
        children: [
          const SizedBox(width: 44, child: Text('時間', style: TextStyle(color: T.inkSoft))),
          _numberDropdown(24, dateTime.hour,
              (v) => onDateTimeChanged(DateTime(
                  dateTime.year, dateTime.month, dateTime.day, v, dateTime.minute))),
          const Text(' 時 '),
          // 對應 populateTimeSelects：分鐘每 5 分一個選項
          _numberDropdown(12, dateTime.minute ~/ 5,
              (v) => onDateTimeChanged(DateTime(
                  dateTime.year, dateTime.month, dateTime.day, dateTime.hour, v * 5)),
              multiplier: 5),
          const Text(' 分 '),
          TextButton(
            onPressed: () => onDateTimeChanged(DateTime.now()),
            child: const Text('目前時間', style: TextStyle(color: T.linkGreenDark)),
          ),
        ],
      );

  Widget _numberDropdown(int count, int value, ValueChanged<int> onChanged,
          {int multiplier = 1}) =>
      DropdownButton<int>(
        value: value.clamp(0, count - 1),
        underline: const SizedBox.shrink(),
        items: List.generate(
          count,
          (i) => DropdownMenuItem(
            value: i,
            child: Text((i * multiplier).toString().padLeft(2, '0'),
                style: const TextStyle(fontFamily: T.fontMono)),
          ),
        ),
        onChanged: (v) => v == null ? null : onChanged(v),
      );

  Widget _submitButton() => SizedBox(
        height: 46,
        child: FilledButton(
          onPressed: loading ? null : onSubmit,
          style: FilledButton.styleFrom(
            backgroundColor: T.submitOrangeDark,
            foregroundColor: T.ink,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(T.radiusMd)),
          ),
          child: Text(loading ? '查詢中…' : '查詢轉乘方案',
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        ),
      );

  Widget _quickExamples() {
    const examples = [
      ('台北車站', '淡水捷運站', '2026年8月17日 15:00 從台北車站出發 ⇒ 淡水捷運站'),
      ('台北車站', '新竹高鐵站', '2026年8月16日 09:30 從台北車站出發 ⇒ 新竹高鐵站'),
      ('台北101', '士林夜市', '2026年8月15日 18:00 從台北101出發 ⇒ 士林夜市'),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('搜尋紀錄',
            style: TextStyle(fontSize: 12, color: T.inkSoft, fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: examples
              .map((e) => GestureDetector(
                    onTap: () => onQuickPick(e.$1, e.$2),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(T.radiusFull),
                        border: Border.all(color: T.line),
                      ),
                      child: Text(e.$3,
                          style: const TextStyle(fontSize: 12, color: T.ink2)),
                    ),
                  ))
              .toList(),
        ),
      ],
    );
  }

  Widget _modeLegend() => Wrap(
        spacing: 16,
        alignment: WrapAlignment.center,
        children: ['BUS', 'METRO', 'TRAIN', 'HSR']
            .map((m) => Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 9,
                      height: 9,
                      decoration:
                          BoxDecoration(color: T.modeColor(m), shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 5),
                    Text(T.modeLabel(m),
                        style: const TextStyle(fontSize: 12, color: T.inkSoft)),
                  ],
                ))
            .toList(),
      );
}

/// 固定頁首：品牌 + 即時時鐘。對應 .site-header / .topbar / .live-clock。
class AppHeader extends StatefulWidget {
  const AppHeader({super.key});
  @override
  State<AppHeader> createState() => _AppHeaderState();
}

class _AppHeaderState extends State<AppHeader> {
  Timer? _timer;
  DateTime _now = DateTime.now();

  @override
  void initState() {
    super.initState();
    // 對應 app.js 的 tickClock，每秒更新一次
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hhmmss = '${formatClock(_now)}:${_now.second.toString().padLeft(2, '0')}';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: const BoxDecoration(
        color: T.railBlueDark,
        boxShadow: T.shadowSm,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: T.pageMaxWidth),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('大台北即時轉乘系統',
                  style: TextStyle(
                      color: Colors.white, fontSize: 17, fontWeight: FontWeight.w900)),
              Row(
                children: [
                  const Text('NOW',
                      style: TextStyle(
                          color: T.railBlueLight, fontSize: 10, fontWeight: FontWeight.w700)),
                  const SizedBox(width: 6),
                  Text(hhmmss,
                      style: const TextStyle(
                          color: Colors.white,
                          fontFamily: T.fontMono,
                          fontSize: 16,
                          fontWeight: FontWeight.w700)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
