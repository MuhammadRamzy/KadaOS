#!/usr/bin/env python3
"""Render the PNG formats of the KadaOS mark from the SVGs here (headless Chrome, transparent, pixel-exact).

  python3 config/brand/render.py

The PNGs are committed: nothing renders at run time. Re-run only when the SVGs change.
  app icon   kadaos-icon.svg + icons/<N>.png   (hicolor app icon: the mark on a graphite tile)
  boot theme plymouth/{mark,cursor}.png           (the KadaOS boot screen: the mark as glass, its cursor glowing)
  backdrop   kadaos-backdrop.jpg                 (lock background: the mark as glass, its cursor glowing)
             kadaos-backdrop-login.jpg           (the same, dimmer, for the login screen)
"""
import re, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = (HERE / "kadaos-mark-dark.svg").read_text()
SHAPES = "\n".join(re.findall(r"\s*<path [^>]+/>", MARK))


ICON = f"""<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect x="4" y="4" width="120" height="120" rx="28" fill="#17171a"/>
  <rect x="4.5" y="4.5" width="119" height="119" rx="27.5" fill="none" stroke="#ffffff" stroke-opacity=".08"/>
  <g transform="translate(64 62) scale(.78) translate(-64 -60)">{SHAPES}
  </g>
</svg>
"""




def render(svg_text, out, w, h):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "a.svg").write_text(svg_text)
        (Path(d) / "a.html").write_text(f'<html><body style="margin:0;background:transparent">'
                                        f'<img src="a.svg" style="display:block;width:{w}px;height:{h}px"></body></html>')
        subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={w},{h}", "--default-background-color=00000000", f"--screenshot={out}",
                        f"file://{d}/a.html"], check=True, capture_output=True, timeout=60)


def backdrop(out, w=2560, h=1600, dim=1.0):
    """The login and lock backdrop: graphite, and the KadaOS mark drawn huge as glass (a faint fill with light
    catching its edges), bleeding off the screen. Its cursor glows blue from below like a light source.
    Computed in floating point and dithered before rounding, so the dark gradients don't band."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    s = 0.98 * h / 72                                            # the mark (72 units tall) as tall as the screen
    ox, oy = w / 2 - 64 * s, 0.535 * h - 60 * s                  # the cursor's base just meets the bottom edge
    P = lambda pts: [(ox + x * s, oy + y * s) for x, y in pts]
    def mask(*polys, blur=0):
        m = Image.new("L", (w, h), 0); d = ImageDraw.Draw(m)
        for poly in polys: d.polygon(P(poly), fill=255)
        if blur: m = m.filter(ImageFilter.GaussianBlur(blur))
        return np.asarray(m, np.float32) / 255
    awning = [(24, 48), (40, 24), (88, 24), (104, 48)]
    chevron = [(32, 64), (56, 80), (32, 96), (32, 88), (44, 80), (32, 72)]
    cursor = [(64, 88), (96, 88), (96, 96), (64, 96)]
    body = mask(awning, chevron, blur=1.2)
    edge = np.clip(body - mask(awning, chevron, blur=9), 0, 1) * 2.2   # light along the edges, strongest at the rim
    cur = mask(cursor, blur=1.2)
    y = np.mgrid[0:h, 0:w][0].astype(np.float32) / h
    img = np.empty((h, w, 3), np.float32); img[:] = (17, 17, 19)
    def over(color, alpha):
        img[:] += (np.array(color, np.float32) - img) * np.clip(alpha, 0, 1)[..., None]
    over((255, 255, 255), body * (0.035 - 0.02 * y))             # the glass: a touch brighter at the top
    over((255, 255, 255), edge * (0.13 - 0.05 * y))
    over((91, 156, 255), mask(cursor, blur=h * 0.09) * 0.55)       # the cursor's glow, then the cursor itself
    over((91, 156, 255), cur * 0.10)
    over((140, 186, 255), np.clip(cur - mask(cursor, blur=9), 0, 1) * 2.2 * 0.45)   # its lit rim
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    vign = np.clip(np.hypot((xx - w / 2) / w, (yy - h * 0.45) / h) * 1.6 - 0.25, 0, 1)
    over((8, 8, 10), vign * 0.55)                                # quiet edges keep the eye in the middle
    img *= dim                                                   # the login variant sits a little darker
    img += np.random.default_rng(7).uniform(-0.5, 0.5, (h, w, 1)) + np.random.default_rng(8).uniform(-0.5, 0.5, (h, w, 1))
    Image.fromarray(np.clip(img.round(), 0, 255).astype(np.uint8)).save(out, quality=94, subsampling=0)


def boot_assets(out_dir, s=3.0):
    """The boot screen in the login's language: the mark as glass (faint fill, lit edges) and its cursor glowing blue.
    Drawn 4x and downsampled for clean edges. mark.png covers the whole mark; cursor.png is the cursor plus its glow,
    padded by PAD units on every side (kadaos.script places it with the same numbers)."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    k = 4; S = s * k
    awning = [(24, 48), (40, 24), (88, 24), (104, 48)]
    chevron = [(32, 64), (56, 80), (32, 96), (32, 88), (44, 80), (32, 72)]
    def mask(polys, w, h, ox, oy, blur=0):
        m = Image.new("L", (w, h), 0); d = ImageDraw.Draw(m)
        for poly in polys: d.polygon([((x - ox) * S, (y - oy) * S) for x, y in poly], fill=255)
        if blur: m = m.filter(ImageFilter.GaussianBlur(blur * k))
        return np.asarray(m, np.float32) / 255
    def save(rgb, alpha, out):
        a = np.clip(alpha, 0, 1)
        img = np.dstack([np.broadcast_to(np.array(rgb, np.float32), a.shape + (3,)), a * 255]).round().astype(np.uint8)
        im = Image.fromarray(img, "RGBA"); im.resize((im.width // k, im.height // k), Image.LANCZOS).save(out)
    w, h = int(80 * S), int(72 * S)                                     # the mark's box: x 24..104, y 24..96
    body = mask([awning, chevron], w, h, 24, 24)
    edge = np.clip(body - mask([awning, chevron], w, h, 24, 24, blur=2.2), 0, 1) * 2.2
    save((255, 255, 255), body * 0.10 + edge * 0.55, out_dir / "mark.png")
    PAD = 14                                                            # glow room around the 32x8 cursor
    w, h = int((32 + 2 * PAD) * S), int((8 + 2 * PAD) * S)
    cur = [(64, 88), (96, 88), (96, 96), (64, 96)]
    c = mask([cur], w, h, 64 - PAD, 88 - PAD)
    glow = mask([cur], w, h, 64 - PAD, 88 - PAD, blur=6) * 0.9
    rim = np.clip(c - mask([cur], w, h, 64 - PAD, 88 - PAD, blur=1.5), 0, 1) * 2
    a = np.clip(glow + c * 0.25 + rim * 0.8, 0, 1)
    save((110, 168, 255), a, out_dir / "cursor.png")


if __name__ == "__main__":
    (HERE / "kadaos-icon.svg").write_text(ICON)
    (HERE / "icons").mkdir(exist_ok=True)
    for n in (16, 24, 32, 48, 64, 128, 256, 512):
        render(ICON, HERE / f"icons/{n}.png", n, n)
    (HERE / "plymouth").mkdir(exist_ok=True)
    boot_assets(HERE / "plymouth")
    backdrop(HERE / "kadaos-backdrop.jpg")
    backdrop(HERE / "kadaos-backdrop-login.jpg", dim=0.72)
    print("rendered into", HERE)
