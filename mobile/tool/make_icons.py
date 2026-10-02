# Draws the Blastgate launcher icon (the 2x2 grid mark from the app bar, one
# gate "open") and writes all Android sizes. Run from mobile/:
#   python tool/make_icons.py
import os

from PIL import Image, ImageDraw

BG = (12, 22, 30, 255)       # P.bg      #0C161E
ACCENT = (34, 211, 238, 255)  # P.accent  #22D3EE
RES = "android/app/src/main/res"
SS = 4  # supersampling


def mark(size, scale):
    """Transparent size x size image with the grid mark; `scale` = share of the canvas it covers."""
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    span = s * scale            # width of the whole mark
    cell = span * 0.42          # one square
    gap = span - 2 * cell
    stroke = max(1, round(span * 0.085))
    radius = cell * 0.24
    x0 = (s - span) / 2
    for row in range(2):
        for col in range(2):
            x = x0 + col * (cell + gap)
            y = x0 + row * (cell + gap)
            box = [x, y, x + cell, y + cell]
            if (row, col) == (0, 1):  # the open gate
                d.rounded_rectangle(box, radius=radius, fill=ACCENT)
            else:
                d.rounded_rectangle(box, radius=radius, outline=ACCENT, width=stroke)
    return im.resize((size, size), Image.LANCZOS)


def legacy(size):
    s = size * SS
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(bg).rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=BG)
    bg = bg.resize((size, size), Image.LANCZOS)
    bg.alpha_composite(mark(size, 0.56))
    return bg


for name, px in [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]:
    folder = os.path.join(RES, "mipmap-" + name)
    legacy(px).save(os.path.join(folder, "ic_launcher.png"))
    # Adaptive icon foreground: 108dp canvas, the mark stays inside the 66dp safe zone
    fg = px * 108 // 48
    mark(fg, 0.40).save(os.path.join(folder, "ic_launcher_foreground.png"))
    print(name, px, fg)

legacy(512).save("tool/icon_preview.png")
