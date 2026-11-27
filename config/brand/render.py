#!/usr/bin/env python3
"""Render the PNG formats of the KadaOS mark from the SVGs here (headless Chrome, transparent, pixel-exact).

  python3 config/brand/render.py

The PNGs are committed: nothing renders at run time. Re-run only when the SVGs change.
  app icon   kadaos-icon.svg + icons/<N>.png   (hicolor app icon: the mark on a graphite tile)
  boot       kadaos-boot.png                     (Plymouth watermark: white wordmark, 1x)
  login      kadaos-login.png                    (GDM logo: white wordmark, 2x of its 48 px slot)
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


def render(svg_text, out, w, h):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "a.svg").write_text(svg_text)
        (Path(d) / "a.html").write_text(f'<html><body style="margin:0;background:transparent">'
                                        f'<img src="a.svg" style="display:block;width:{w}px;height:{h}px"></body></html>')
        subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={w},{h}", "--default-background-color=00000000", f"--screenshot={out}",
                        f"file://{d}/a.html"], check=True, capture_output=True, timeout=60)


if __name__ == "__main__":
    (HERE / "kadaos-icon.svg").write_text(ICON)
    (HERE / "icons").mkdir(exist_ok=True)
    for n in (16, 24, 32, 48, 64, 128, 256, 512):
        render(ICON, HERE / f"icons/{n}.png", n, n)
    word = tight_word()
    render(word, HERE / "kadaos-boot.png", 205, 36)
    render(word, HERE / "kadaos-login.png", 547, 96)
    print("rendered into", HERE)
