import 'package:flutter/material.dart';

/// Color tokens — same values as desktop_qt/blastgate/ui/theme.py.
/// Semantic colors (open/closed/warning/error) are the same in every theme;
/// only surfaces and text change between dark and light.
class Pal {
  final Color bg, sidebar, card, cardHi, border, text, muted, track, accent, accentText, navActive;
  const Pal({
    required this.bg,
    required this.sidebar,
    required this.card,
    required this.cardHi,
    required this.border,
    required this.text,
    required this.muted,
    required this.track,
    required this.accent,
    required this.accentText,
    required this.navActive,
  });
}

const Pal darkPal = Pal(
  bg: Color(0xFF0C161E),
  sidebar: Color(0xFF0E1A23),
  card: Color(0xFF122029),
  cardHi: Color(0xFF16272F),
  border: Color(0xFF1F3340),
  text: Color(0xFFE6EDF3),
  muted: Color(0xFF8AA0B2),
  track: Color(0xFF23343F),
  accent: Color(0xFF22D3EE),
  accentText: Color(0xFF062A33),
  navActive: Color(0xFF113845),
);

const Pal lightPal = Pal(
  bg: Color(0xFFEEF2F5),
  sidebar: Color(0xFFE3E9EE),
  card: Color(0xFFFFFFFF),
  cardHi: Color(0xFFF5F8FA),
  border: Color(0xFFD3DCE3),
  text: Color(0xFF0F1A22),
  muted: Color(0xFF5A6C7A),
  track: Color(0xFFDDE5EB),
  accent: Color(0xFF0891B2),
  accentText: Color(0xFFFFFFFF),
  navActive: Color(0xFFCFEAF1),
);

const Map<String, Color> semantic = {
  'success': Color(0xFF22C55E), // gate open / machine running / suction on
  'warning': Color(0xFFFBBF24), // moving / manual / warning
  'danger': Color(0xFFEF4444), // error / offline / gate closed command
  'info': Color(0xFF38BDF8), // AUTO
  'idle': Color(0xFF8AA0B2), // idle / unknown
};

/// Active palette. The whole app rebuilds when the theme setting changes.
Pal P = darkPal;

void setTheme(String name) => P = name == 'light' ? lightPal : darkPal;

/// Tone name → color ('muted', 'accent', 'text' map to the active palette).
Color tone(String t) {
  switch (t) {
    case 'muted':
      return P.muted;
    case 'accent':
      return P.accent;
    case 'text':
      return P.text;
    default:
      return semantic[t] ?? P.muted;
  }
}

ThemeData buildTheme() {
  final dark = identical(P, darkPal);
  final base = dark ? ThemeData.dark() : ThemeData.light();
  return base.copyWith(
    scaffoldBackgroundColor: P.bg,
    canvasColor: P.card,
    dividerColor: P.border,
    colorScheme: (dark ? const ColorScheme.dark() : const ColorScheme.light()).copyWith(
      primary: P.accent,
      onPrimary: P.accentText,
      secondary: P.accent,
      surface: P.card,
      onSurface: P.text,
      error: semantic['danger'],
    ),
    textTheme: base.textTheme.apply(bodyColor: P.text, displayColor: P.text),
    appBarTheme: AppBarTheme(
      backgroundColor: P.bg,
      foregroundColor: P.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: TextStyle(color: P.text, fontSize: 20, fontWeight: FontWeight.w600),
    ),
    cardTheme: CardThemeData(
      color: P.card,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10), side: BorderSide(color: P.border)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: P.bg,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      labelStyle: TextStyle(color: P.muted),
      hintStyle: TextStyle(color: P.muted),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(6), borderSide: BorderSide(color: P.border)),
      enabledBorder:
          OutlineInputBorder(borderRadius: BorderRadius.circular(6), borderSide: BorderSide(color: P.border)),
      focusedBorder:
          OutlineInputBorder(borderRadius: BorderRadius.circular(6), borderSide: BorderSide(color: P.accent)),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: P.cardHi,
      contentTextStyle: TextStyle(color: P.text),
      behavior: SnackBarBehavior.floating,
    ),
    dialogTheme: DialogThemeData(backgroundColor: P.card),
    bottomSheetTheme: BottomSheetThemeData(backgroundColor: P.card),
    sliderTheme: SliderThemeData(
      activeTrackColor: semantic['warning'],
      inactiveTrackColor: P.track,
      thumbColor: P.text,
      overlayColor: P.accent.withValues(alpha: 0.1),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? P.accentText : P.muted),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? P.accent : P.track),
      trackOutlineColor: WidgetStateProperty.all(P.border),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: P.accent, linearTrackColor: P.track),
    tabBarTheme: TabBarThemeData(
      labelColor: P.accent,
      unselectedLabelColor: P.muted,
      indicatorColor: P.accent,
      dividerColor: P.border,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: P.sidebar,
      indicatorColor: P.navActive,
      surfaceTintColor: Colors.transparent,
      labelTextStyle: WidgetStateProperty.resolveWith((s) => TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: s.contains(WidgetState.selected) ? P.accent : P.muted)),
    ),
  );
}
