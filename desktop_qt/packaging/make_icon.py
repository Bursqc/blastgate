# Writes packaging/blastgate.ico — the same mark as the mobile launcher icon
# (mobile/tool/make_icons.py): 2x2 grid, one gate "open". Needs Pillow.
import os

from PIL import Image, ImageDraw

BG = (12, 22, 30, 255)        # #0C161E
ACCENT = (34, 211, 238, 255)  # #22D3EE
SS = 4


def icon(size):
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=BG)
    span = s * 0.56
    cell = span * 0.42
    gap = span - 2 * cell
    stroke = max(1, round(span * 0.085))
    x0 = (s - span) / 2
    for row in range(2):
        for col in range(2):
            x, y = x0 + col * (cell + gap), x0 + row * (cell + gap)
            box = [x, y, x + cell, y + cell]
            if (row, col) == (0, 1):
                d.rounded_rectangle(box, radius=cell * 0.24, fill=ACCENT)
            else:
                d.rounded_rectangle(box, radius=cell * 0.24, outline=ACCENT, width=stroke)
    return im.resize((size, size), Image.LANCZOS)


out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blastgate.ico")
icon(256).save(out, sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
print("wrote", out)
