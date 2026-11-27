# KadaOS

The mark is an open command: a roadside stall awning above a terminal prompt. The canopy carries the thattukada’s promise of many useful things in one welcoming place; the prompt brings that promise to a workstation. A single blue cursor suggests the search box, ready for the next request, even late at night. Custom geometric lettering keeps the identity calm and practical, with no font dependency.

## Colour

| Colour | Hex | Use |
| --- | --- | --- |
| Ink | `#17171a` | Light-mode mark, lettering; dark hero background |
| Graphite | `#2c2c31` | Supporting dark surfaces |
| Paper | `#ffffff` | Dark-mode mark, lettering; light hero background |
| Accent blue | `#5b9cff` | Cursor only |

Banner captions use quiet neutrals `#62626b` on paper and `#bcbcc5` on ink. No warm accent is needed. The transparent logos take their background from the host surface; the banners include their backgrounds.

## Space & scale

Keep at least **24 units** of clear space around the visible mark on its 128-unit artboard (three cursor thicknesses). Preserve the supplied wordmark’s internal spacing; allow at least 24 units around its visible bounds, scaled with the artwork. The SVG artboards already include the nominal clear space. Do not crop them tighter.

Minimum: symbol **16 × 16 px** (prefer `favicon.svg` at 16–32 px), horizontal wordmark **160 px wide**, hero **640 px wide** when the caption must be read. Use the symbol alone below the wordmark minimum. Evaluate at actual size; fractional scaling can soften diagonal edges.

## Do / don’t

**Do:** use the matching background variant; preserve the aspect ratio and clear space; use the supplied blue cursor consistently.

**Don’t:** stretch or rotate the artwork; add shadows, gradients or outlines; add stall details or replace the custom lettering with typed text.

## Files

| File | Use |
| --- | --- |
| `kadaos-mark.svg` / `kadaos-mark-dark.svg` | Transparent symbol for light / dark app surfaces, avatars and icons |
| `kadaos-wordmark.svg` / `kadaos-wordmark-dark.svg` | Transparent horizontal identity for light / dark headers and documentation |
| `kadaos-banner.svg` / `kadaos-banner-dark.svg` | 1280 × 400 README hero, with complete tagline and fixed background |
| `favicon.svg` | Theme-aware browser icon with a native 16-unit grid |
| `kadaos-mark-128.png` / `kadaos-mark-512.png` | Transparent light-variant PNGs for tools requiring raster uploads |
| `preview.html` | Offline proof sheet: every image, both backgrounds, all five requested widths |

All logo lettering and banner captions are paths. `build_assets.py` preserves the hand-authored geometry and rebuilds the SVG set; rebuilding caption outlines requires Python fontTools and the existing DejaVu Sans system font. Viewing or using the exports requires neither.
