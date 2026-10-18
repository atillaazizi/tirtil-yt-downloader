"""assets/icon.icns üretir (monokrom ATi__ rozet). Çalıştır: .venv/bin/python3 scripts/make_icon.py"""
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
S = 1024


def font(size):
    for p in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
m = 100
d.rounded_rectangle((m, m, S - m, S - m), radius=185, fill=(14, 14, 16, 255), outline=(255, 255, 255, 60), width=6)

# Dalga formu (ses dilimleri)
bars = [0.25, 0.45, 0.7, 0.95, 0.6, 0.35, 0.8, 1.0, 0.55, 0.3, 0.65, 0.4]
bw, gap = 34, 18
total = len(bars) * bw + (len(bars) - 1) * gap
x0, cy, hmax = (S - total) // 2, 610, 300
for i, h in enumerate(bars):
    x = x0 + i * (bw + gap)
    hh = int(hmax * h)
    shade = 255 if i % 4 != 3 else 120
    d.rounded_rectangle((x, cy - hh // 2, x + bw, cy + hh // 2), radius=bw // 2, fill=(shade, shade, shade, 255))


f = font(170)
text = "ATi__"
w = d.textbbox((0, 0), text, font=f)[2]
d.text(((S - w) // 2, 215), text, font=f, fill=(255, 255, 255, 255))

iconset = os.path.join(ASSETS, "icon.iconset")
os.makedirs(iconset, exist_ok=True)
img.save(os.path.join(ASSETS, "icon.png"))
for sz in (16, 32, 128, 256, 512):
    img.resize((sz, sz), Image.LANCZOS).save(os.path.join(iconset, f"icon_{sz}x{sz}.png"))
    img.resize((sz * 2, sz * 2), Image.LANCZOS).save(os.path.join(iconset, f"icon_{sz}x{sz}@2x.png"))
subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(ASSETS, "icon.icns")], check=True)
print("assets/icon.icns hazır")
