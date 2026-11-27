#!/usr/bin/env python3
"""Render the PNG formats of the KadaOS mark from the SVGs here (headless Chrome, transparent, pixel-exact).

  python3 config/brand/render.py

The PNGs are committed: nothing renders at run time. Re-run only when the SVGs change.
  app icon   kadaos-icon.svg + icons/<N>.png   (hicolor app icon: the mark on a graphite tile)
  boot theme plymouth/{mark,cursor,word}.png      (the KadaOS boot screen: mark, blinking cursor, wordmark)
  backdrop   kadaos-backdrop.jpg                 (lock background: the mark as glass, its cursor glowing)
             kadaos-backdrop-login.jpg           (the same, dimmer, for the login screen)
"""
import re, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = (HERE / "kadaos-mark-dark.svg").read_text()
SHAPES = "\n".join(re.findall(r"\s*<path [^>]+/>", MARK))
WORD = (HERE / "kadaos-wordmark-dark.svg").read_text()


def tight_word():   # the wordmark without its built-in clear space
    return re.sub(r'width="\d+" height="\d+" viewBox="[^"]+"', 'width="456" height="80" viewBox="20 20 456 80"', WORD, count=1)


ICON = f"""<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect x="4" y="4" width="120" height="120" rx="28" fill="#17171a"/>
  <rect x="4.5" y="4.5" width="119" height="119" rx="27.5" fill="none" stroke="#ffffff" stroke-opacity=".08"/>
  <g transform="translate(64 62) scale(.78) translate(-64 -60)">{SHAPES}
  </g>
</svg>
"""


AWNING = '<path fill="#ffffff" d="M24 48 40 24h48l16 24Z"/><path fill="#ffffff" d="m32 64 24 16-24 16v-8l12-8-12-8Z"/>'
BOOT_MARK = f'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="72" viewBox="24 24 80 72">{AWNING}</svg>'
BOOT_CURSOR = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="8" viewBox="0 0 32 8"><rect width="32" height="8" fill="#5b9cff"/></svg>'


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


if __name__ == "__main__":
    (HERE / "kadaos-icon.svg").write_text(ICON)
    (HERE / "icons").mkdir(exist_ok=True)
    for n in (16, 24, 32, 48, 64, 128, 256, 512):
        render(ICON, HERE / f"icons/{n}.png", n, n)
    word = tight_word()
    (HERE / "plymouth").mkdir(exist_ok=True)
    render(BOOT_MARK, HERE / "plymouth/mark.png", 120, 108)
    render(BOOT_CURSOR, HERE / "plymouth/cursor.png", 48, 12)
    render(word, HERE / "plymouth/word.png", 137, 24)
    backdrop(HERE / "kadaos-backdrop.jpg")
    backdrop(HERE / "kadaos-backdrop-login.jpg", dim=0.72)
    print("rendered into", HERE)
