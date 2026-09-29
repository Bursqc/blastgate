import 'package:flutter/material.dart';

import 'icons.dart';
import 'theme.dart';

/// Reusable widgets in the look of the Blastgate mockups (desktop_qt/blastgate/ui/widgets.py).

TextStyle tsTitle([double size = 26]) => TextStyle(fontSize: size, fontWeight: FontWeight.w600, color: P.text);
TextStyle tsSection() => TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: P.text);
TextStyle tsMuted([double size = 14]) => TextStyle(fontSize: size, color: P.muted);
TextStyle tsSmall() => TextStyle(fontSize: 12, color: P.muted);
TextStyle tsBig([double size = 38]) => TextStyle(fontSize: size, fontWeight: FontWeight.w700, color: P.text);
TextStyle tsMid() => TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: P.text);

class BgCard extends StatelessWidget {
  final Widget child;
  final VoidCallback? onTap;
  final bool inset;
  final EdgeInsets padding;
  const BgCard({super.key, required this.child, this.onTap, this.inset = false, this.padding = const EdgeInsets.all(16)});

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(inset ? 8 : 10);
    return Material(
      color: inset ? P.cardHi : P.card,
      shape: RoundedRectangleBorder(borderRadius: radius, side: BorderSide(color: P.border)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(onTap: onTap, child: Padding(padding: padding, child: child)),
    );
  }
}

class Dot extends StatelessWidget {
  final String toneName;
  final double size;
  const Dot(this.toneName, {super.key, this.size = 10});

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: tone(toneName), shape: BoxShape.circle),
      );
}

/// Colored dot + uppercase status text.
class StatusLabel extends StatelessWidget {
  final String text;
  final String toneName;
  final double size;
  const StatusLabel(this.text, this.toneName, {super.key, this.size = 12});

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        Dot(toneName),
        const SizedBox(width: 7),
        Flexible(
          child: Text(text,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: tone(toneName), fontSize: size, fontWeight: FontWeight.w600)),
        ),
      ]);
}

/// Horizontal bar with a threshold marker and its caption under it.
class ValueBar extends StatelessWidget {
  final double? value;
  final double? threshold;
  final double max;
  final double barHeight;
  const ValueBar({super.key, this.value, this.threshold, required this.max, this.barHeight = 10});

  @override
  Widget build(BuildContext context) => SizedBox(
        height: barHeight + 22,
        width: double.infinity,
        child: CustomPaint(painter: _BarPainter(value, threshold, max < 1 ? 1 : max, barHeight)),
      );
}

class _BarPainter extends CustomPainter {
  final double? value, thr;
  final double max, h;
  _BarPainter(this.value, this.thr, this.max, this.h);

  @override
  void paint(Canvas canvas, Size size) {
    const top = 4.0;
    final w = size.width;
    final r = Radius.circular(h / 2);
    canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(0, top, w, h), r), Paint()..color = P.track);
    final v = value;
    if (v != null && v > 0) {
      final frac = (v / max).clamp(0.0, 1.0);
      final above = thr != null && v >= thr!;
      final fw = (w * frac) < h ? h : w * frac;
      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(0, top, fw, h), r),
          Paint()..color = above ? semantic['success']! : P.accent);
    }
    final t = thr;
    if (t != null && t > 0) {
      final x = (w * t / max).clamp(2.0, w - 2);
      canvas.drawLine(Offset(x, top - 3), Offset(x, top + h + 3), Paint()
        ..color = P.text
        ..strokeWidth = 2);
      final tp = TextPainter(
        text: TextSpan(text: 'prag ${_g(t)}', style: TextStyle(color: P.muted, fontSize: 10.5)),
        textDirection: TextDirection.ltr,
      )..layout();
      final tx = (x - tp.width / 2).clamp(0.0, w - tp.width);
      tp.paint(canvas, Offset(tx, top + h + 5));
    }
  }

  @override
  bool shouldRepaint(_BarPainter o) => o.value != value || o.thr != thr || o.max != max;
}

/// Number without trailing ".0" (Python's :g for our ranges).
String _g(double v) => v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);
String fmtG(double v) => _g(v);

class SegOption {
  final String key, text, icon, toneName;
  const SegOption(this.key, this.text, this.icon, this.toneName);
}

/// Row of exclusive buttons, e.g. AUTO | MANUAL.
/// The selected button always shows what the HUB says; a tap is shown as
/// "pending" (faded outline) until the hub status confirms it or 3 s pass.
class Segmented extends StatefulWidget {
  final List<SegOption> options;
  final String? current;
  final ValueChanged<String> onChosen;
  final bool enabled;
  final bool compact;
  const Segmented({
    super.key,
    required this.options,
    required this.current,
    required this.onChosen,
    this.enabled = true,
    this.compact = false,
  });

  @override
  State<Segmented> createState() => SegmentedState();
}

class SegmentedState extends State<Segmented> {
  String? _pending;
  DateTime? _pendingAt;

  void clearPending() => setState(() => _pending = null);

  @override
  void didUpdateWidget(Segmented oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_pending != null &&
        (_pending == widget.current || DateTime.now().difference(_pendingAt!).inMilliseconds > 3000)) {
      _pending = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    for (final o in widget.options) {
      if (children.isNotEmpty) children.add(const SizedBox(width: 8));
      final selected = o.key == widget.current;
      final pending = o.key == _pending;
      final col = tone(o.toneName);
      final active = (selected || pending) && widget.enabled;
      final fg = active ? col : P.muted.withValues(alpha: widget.enabled ? 1 : 0.5);
      children.add(Expanded(
        child: Material(
          color: selected && widget.enabled ? col.withValues(alpha: 0.10) : Colors.transparent,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(7),
            side: BorderSide(
              color: selected && widget.enabled
                  ? col
                  : pending
                      ? col.withValues(alpha: 0.55)
                      : P.border,
              width: pending ? 1.6 : 1,
            ),
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(7),
            onTap: widget.enabled
                ? () {
                    setState(() {
                      _pending = o.key;
                      _pendingAt = DateTime.now();
                    });
                    widget.onChosen(o.key);
                  }
                : null,
            child: SizedBox(
              height: widget.compact ? 40 : 48,
              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                if (o.icon.isNotEmpty) ...[Ic(o.icon, fg, size: widget.compact ? 17 : 20), const SizedBox(width: 6)],
                Flexible(
                  child: Text(o.text,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: fg, fontWeight: FontWeight.w600, fontSize: widget.compact ? 13 : 14)),
                ),
              ]),
            ),
          ),
        ),
      ));
    }
    return Row(children: children);
  }
}

/// Icon + small caption + value (Zatvarač / Signal row element).
class IconValue extends StatelessWidget {
  final String icon, caption, value, toneName;
  const IconValue(this.icon, this.caption, this.value, {super.key, this.toneName = 'muted'});

  @override
  Widget build(BuildContext context) => Row(children: [
        Ic(icon, tone(toneName), size: 24),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(caption, style: tsSmall()),
            Text(value, overflow: TextOverflow.ellipsis, style: tsMid()),
          ]),
        ),
      ]);
}

/// Outlined pill with icon + text (AUTO / MANUAL / OTVOREN / ZATVOREN on tiles).
class Badge extends StatelessWidget {
  final String text, icon, toneName;
  const Badge(this.text, this.icon, this.toneName, {super.key});

  @override
  Widget build(BuildContext context) {
    final col = tone(toneName);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      constraints: const BoxConstraints(minWidth: 118),
      decoration: BoxDecoration(border: Border.all(color: col), borderRadius: BorderRadius.circular(7)),
      child: Row(mainAxisSize: MainAxisSize.min, mainAxisAlignment: MainAxisAlignment.center, children: [
        Ic(icon, col, size: 17),
        const SizedBox(width: 6),
        Text(text, style: TextStyle(color: col, fontWeight: FontWeight.w600, fontSize: 13)),
      ]),
    );
  }
}

class Banner extends StatelessWidget {
  final String text, toneName, icon;
  const Banner(this.text, {super.key, this.toneName = 'info', this.icon = 'info-circle'});

  @override
  Widget build(BuildContext context) {
    final col = tone(toneName);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: col.withValues(alpha: 0.12),
        border: Border.all(color: col),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Ic(icon, col, size: 20),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: TextStyle(color: col, fontSize: 13.5))),
      ]),
    );
  }
}

/// A message shown under a form: (text, tone, icon) or null.
typedef Msg = (String, String, String)?;

Widget msgBanner(Msg m) =>
    m == null ? const SizedBox.shrink() : Padding(padding: const EdgeInsets.only(top: 10), child: Banner(m.$1, toneName: m.$2, icon: m.$3));

class Btn extends StatelessWidget {
  final String text;
  final String icon;
  final String variant; // '', 'primary', 'outline', 'danger'
  final VoidCallback? onTap;
  final bool expand;
  const Btn(this.text, {super.key, this.icon = '', this.variant = '', this.onTap, this.expand = false});

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null;
    final Color fg, border, bg;
    switch (variant) {
      case 'primary':
        fg = enabled ? P.accentText : P.muted;
        bg = enabled ? P.accent : P.track;
        border = bg;
      case 'outline':
        fg = enabled ? P.accent : P.muted;
        bg = Colors.transparent;
        border = enabled ? P.accent : P.border;
      case 'danger':
        fg = enabled ? semantic['danger']! : P.muted;
        bg = Colors.transparent;
        border = enabled ? semantic['danger']! : P.border;
      default:
        fg = enabled ? P.text : P.muted;
        bg = Colors.transparent;
        border = P.border;
    }
    final row = Row(
      mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (icon.isNotEmpty) ...[Ic(icon, fg, size: 18), const SizedBox(width: 7)],
        Flexible(
          child: Text(text,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: fg, fontWeight: variant == 'primary' ? FontWeight.w600 : FontWeight.w500)),
        ),
      ],
    );
    return Material(
      color: bg,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7), side: BorderSide(color: border)),
      child: InkWell(
        borderRadius: BorderRadius.circular(7),
        onTap: onTap,
        child: Padding(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11), child: row),
      ),
    );
  }
}

/// Page title + subtitle (+ optional trailing widget), like the desktop pages.
class PageHeader extends StatelessWidget {
  final String title, subtitle;
  final Widget? trailing;
  const PageHeader(this.title, this.subtitle, {super.key, this.trailing});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: tsTitle()),
              if (subtitle.isNotEmpty) Text(subtitle, style: tsMuted(13)),
            ]),
          ),
          ?trailing,
        ]),
      );
}

class Section extends StatelessWidget {
  final String title;
  final List<Widget> children;
  final Widget? trailing;
  final bool inset;
  const Section(this.title, this.children, {super.key, this.trailing, this.inset = true});

  @override
  Widget build(BuildContext context) => BgCard(
        inset: inset,
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [Expanded(child: Text(title, style: tsSection())), ?trailing]),
          const SizedBox(height: 10),
          ...children,
        ]),
      );
}

class KV extends StatelessWidget {
  final String k, v;
  final String? toneName;
  const KV(this.k, this.v, {super.key, this.toneName});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(flex: 4, child: Text(k, style: tsMuted(13))),
          Expanded(
            flex: 5,
            child: Text(v,
                style: TextStyle(
                    fontWeight: FontWeight.w600, color: toneName == null ? P.text : tone(toneName!))),
          ),
        ]),
      );
}

Future<bool> confirm(BuildContext context, String title, String text, {String ok = 'Da'}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: Text(text),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Otkaži')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(ok)),
      ],
    ),
  );
  return r ?? false;
}

void toast(BuildContext context, String text) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
