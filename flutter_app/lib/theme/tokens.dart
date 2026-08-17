// 設計變數，1:1 對應 transit/web/style.css 的 :root。
//
// 移植原則：原本 CSS 怎麼寫，這裡就怎麼放，變數名也盡量對齊，
// 之後兩邊要對照調整時才找得到對應的那一行。

import 'package:flutter/material.dart';

class T {
  T._();

  // ---- 色彩 ----
  static const ink = Color(0xFF262A33);
  static const ink2 = Color(0xFF3B3F49);
  static const paper = Color(0xFFF0F2F6);
  static const paperCard = Color(0xFFF8F9FB);
  static const line = Color(0xFFCFE3ED);
  static const lineStrong = Color(0xFF5FACD3);

  static const railBlue = Color(0xFF39587F);
  static const railBlueDark = Color(0xFF253D5B);
  static const railBlueLight = Color(0xFF7F9BBD);
  static const railBlueSoft = Color(0x1439587F); // rgba(57,88,127,.08)

  static const destination = Color(0xFF2F656A);
  static const destinationDark = Color(0xFF1F484C);
  static const rose = Color(0xFF2F656A);
  static const roseDark = Color(0xFF1F484C);
  static const roseSoft = Color(0x142F656A); // rgba(47,101,106,.08)

  static const submitOrange = Color(0xFFF3CD97);
  static const submitOrangeDark = Color(0xFFE9B367);
  static const linkGreen = Color(0xFF74AAA1);
  static const linkGreenDark = Color(0xFF224942);
  static const signalAmber = Color(0xFF866F27);
  static const signalAmberInk = Color(0xFF5D4222);

  static const inkSoft = Color(0xFF6B7080);
  static const inkFaint = Color(0xFF9AA0AD);

  // 四種運具色
  static const bus = Color(0xFF3E6F58);
  static const metro = Color(0xFF39587F);
  static const train = Color(0xFF6F533E);
  static const hsr = Color(0xFF9A4248);

  static Color modeColor(String mode) => switch (mode) {
        'BUS' => bus,
        'METRO' => metro,
        'TRAIN' => train,
        'HSR' => hsr,
        _ => inkSoft,
      };

  /// 對應 app.js 的 renderModeIcons
  static String modeLabel(String mode) => switch (mode) {
        'BUS' => '公車',
        'METRO' => '捷運',
        'TRAIN' => '台鐵',
        'HSR' => '高鐵',
        _ => '',
      };

  static IconData modeIcon(String mode) => switch (mode) {
        'BUS' => Icons.directions_bus,
        'METRO' => Icons.subway,
        'TRAIN' => Icons.train,
        'HSR' => Icons.directions_railway,
        _ => Icons.directions_walk,
      };

  // ---- 字體 ----
  // web/index.html 保留了 Google Fonts 的 <link>，所以這裡直接指名即可，
  // 不需要 google_fonts 套件（少一個相依）。
  static const fontDisplay = 'Noto Sans TC';
  static const fontBody = 'Noto Sans TC';
  static const fontMono = 'JetBrains Mono';

  // ---- 尺寸 ----
  static const radiusXl = 20.0;
  static const radiusLg = 14.0;
  static const radiusMd = 10.0;
  static const radiusSm = 7.0;
  static const radiusFull = 999.0;

  // ---- 陰影分層 ----
  static const shadowXs = [
    BoxShadow(color: Color(0x0D121B2D), offset: Offset(0, 1), blurRadius: 2),
  ];
  static const shadowSm = [
    BoxShadow(color: Color(0x0F121B2D), offset: Offset(0, 2), blurRadius: 6),
    BoxShadow(color: Color(0x0D121B2D), offset: Offset(0, 1), blurRadius: 2),
  ];
  static const shadowMd = [
    BoxShadow(color: Color(0x1A121B2D), offset: Offset(0, 8), blurRadius: 24),
    BoxShadow(color: Color(0x0D121B2D), offset: Offset(0, 2), blurRadius: 6),
  ];
  static const shadowLg = [
    BoxShadow(color: Color(0x24121B2D), offset: Offset(0, 16), blurRadius: 40),
  ];

  // ---- 動效 ----
  static const ease = Cubic(0.4, 0, 0.2, 1);

  /// 版面最大寬度（對應 .page 的 max-width）
  static const pageMaxWidth = 960.0;
}
