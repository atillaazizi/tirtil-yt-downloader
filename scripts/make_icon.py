"""assets/icon.png + assets/icon.icns üretir (Tırtıl ikonu).

Gerekli: Pillow (pip install Pillow). Çalıştır: python3 scripts/make_icon.py
"""
import math
import os
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SS = 2  # süper örnekleme (kenar yumuşatma)
S = 1024 * SS


def p(v):
    return int(v * SS)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


# --- Arka plan: macOS rozet, dikey gradyan ---
bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
top, bottom = (34, 40, 48, 255), (12, 14, 18, 255)
for y in range(S):
    gd.line((0, y, S, y), fill=lerp(top, bottom, y / S))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((p(100), p(100), S - p(100), S - p(100)), radius=p(185), fill=255)
bg.paste(grad, (0, 0), mask)
ImageDraw.Draw(bg).rounded_rectangle(
    (p(100), p(100), S - p(100), S - p(100)), radius=p(185), outline=(255, 255, 255, 40), width=p(5)
)

# --- Tırtıl ---
layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(layer)

dark = (46, 140, 62, 255)
mid = (88, 196, 84, 255)
light = (170, 236, 120, 255)

# Gövde segmentleri: soldan sağa dalga, kafaya doğru büyür
segs = []
n = 5
for i in range(n):
    t = i / (n - 1)
    x = 215 + i * 100
    y = 600 - 55 * math.sin(t * math.pi * 1.15)
    r = 78 + 10 * t
    segs.append((x, y, r))

# Bacaklar
for x, y, r in segs:
    for dx in (-26, 26):
        d.rounded_rectangle(
            (p(x + dx - 11), p(y + r - 30), p(x + dx + 11), p(y + r + 32)), radius=p(11), fill=(30, 98, 44, 255)
        )

# Segmentler (arkadan öne)
for i, (x, y, r) in enumerate(segs):
    d.ellipse((p(x - r), p(y - r), p(x + r), p(y + r)), fill=dark)
    d.ellipse((p(x - r + 8), p(y - r + 6), p(x + r - 8), p(y + r - 12)), fill=mid)
    # parlama
    d.ellipse((p(x - r * 0.55), p(y - r * 0.75), p(x + r * 0.1), p(y - r * 0.25)), fill=light)
    # sırt benekleri
    d.ellipse((p(x + 10), p(y - 18), p(x + 34), p(y + 6)), fill=(255, 214, 90, 255))

# Kafa
hx, hy, hr = 725, 500, 122
# antenler
for ax, tipx, tipy in ((-50, -95, -150), (40, 70, -165)):
    d.line((p(hx + ax), p(hy - hr + 25), p(hx + tipx), p(hy + tipy - 40)), fill=(30, 98, 44, 255), width=p(16))
    d.ellipse((p(hx + tipx - 24), p(hy + tipy - 64), p(hx + tipx + 24), p(hy + tipy - 16)), fill=(255, 98, 98, 255))
d.ellipse((p(hx - hr), p(hy - hr), p(hx + hr), p(hy + hr)), fill=dark)
d.ellipse((p(hx - hr + 9), p(hy - hr + 7), p(hx + hr - 9), p(hy + hr - 14)), fill=mid)
d.ellipse((p(hx - hr * 0.6), p(hy - hr * 0.8), p(hx), p(hy - hr * 0.3)), fill=light)

# Gözler
for ex in (-42, 42):
    cx, cy = hx + ex, hy - 18
    d.ellipse((p(cx - 32), p(cy - 38), p(cx + 32), p(cy + 38)), fill=(255, 255, 255, 255))
    d.ellipse((p(cx - 14 + 8), p(cy - 18 + 6), p(cx + 14 + 8), p(cy + 18 + 6)), fill=(20, 20, 24, 255))
    d.ellipse((p(cx + 4), p(cy - 6), p(cx + 12), p(cy + 2)), fill=(255, 255, 255, 255))

# Yanaklar + gülümseme
for ex in (-80, 80):
    d.ellipse((p(hx + ex - 20), p(hy + 34), p(hx + ex + 20), p(hy + 58)), fill=(255, 140, 140, 180))
d.arc((p(hx - 40), p(hy + 10), p(hx + 40), p(hy + 75)), start=20, end=160, fill=(20, 60, 28, 255), width=p(10))

# Gölge
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).ellipse((p(140), p(715), p(860), p(780)), fill=(0, 0, 0, 120))
shadow = shadow.filter(ImageFilter.GaussianBlur(p(18)))

img = Image.alpha_composite(bg, shadow)
img = Image.alpha_composite(img, layer)
img = img.resize((1024, 1024), Image.LANCZOS)

iconset = os.path.join(ASSETS, "icon.iconset")
os.makedirs(iconset, exist_ok=True)
img.save(os.path.join(ASSETS, "icon.png"))
for sz in (16, 32, 128, 256, 512):
    img.resize((sz, sz), Image.LANCZOS).save(os.path.join(iconset, f"icon_{sz}x{sz}.png"))
    img.resize((sz * 2, sz * 2), Image.LANCZOS).save(os.path.join(iconset, f"icon_{sz}x{sz}@2x.png"))
subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(ASSETS, "icon.icns")], check=True)
shutil.rmtree(iconset)
print("assets/icon.icns hazır")
