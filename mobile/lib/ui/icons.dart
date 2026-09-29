import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// Tabler icon (MIT, assets/icons) recolored — same icon set as the desktop app.
class Ic extends StatelessWidget {
  final String name;
  final Color color;
  final double size;
  const Ic(this.name, this.color, {super.key, this.size = 22});

  @override
  Widget build(BuildContext context) => SvgPicture.asset(
        'assets/icons/$name.svg',
        width: size,
        height: size,
        colorFilter: ColorFilter.mode(color, BlendMode.srcIn),
      );
}
