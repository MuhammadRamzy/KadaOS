#!/usr/bin/env python3
"""myos-pick — a themed GTK picker that replaces plain rofi/dmenu lists everywhere.

Reads items on stdin (one per line), prints the chosen one to stdout (exit 1 if cancelled) — a drop-in for
`rofi -dmenu`. Rich items: "label\\ticon-name\\tsubtitle" (icon and subtitle optional).

Short menus render as a tile grid; long menus as an icon list with search. Both are keyboard-first:
type to search, arrows to move, 1-9 to pick, Enter/click to choose; Esc clears the search, then cancels.
With --back (submenus): a back arrow, or Backspace on an empty search, exits with status 2 ("go back").

  ... | myos-pick --title "Screenshot" --grid
  ... | myos-pick --title "Apps"
"""
import sys


def parse_items(lines):
    """[(label, icon_or_None, subtitle_or_None)] from dmenu-style lines (tab extras optional)."""
    items = []
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        label = parts[0]
        icon = (parts[1].strip() or None) if len(parts) > 1 else None
        sub = (parts[2].strip() or None) if len(parts) > 2 else None
        items.append((label, icon, sub))
    return items


def matches(item, query):
    if not query:
        return True
    hay = " ".join(x for x in item if x).lower()
    return all(w in hay for w in query.lower().split())


def choose_layout(n_items, grid_flag, list_flag):
    """Grid for a handful of actions; list once there are many (search likely)."""
    if grid_flag:
        return "grid"
    if list_flag:
        return "list"
    return "grid" if n_items <= 8 else "list"


def nav(sel, key, n, cols):
    """New selected index after an arrow key in a grid with `cols` columns (list: cols=1). Clamped, no wrap."""
    if n == 0:
        return 0
    step = {"left": -1, "right": 1, "up": -cols, "down": cols}[key]
    new = sel + step
    if key in ("left", "right") and cols > 1 and new // cols != sel // cols:
        return sel                                   # don't jump rows with left/right
    return min(max(new, 0), n - 1)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", "-p", default="Select")
    ap.add_argument("--placeholder", default="Type to search")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--list", action="store_true", dest="list_mode")
    ap.add_argument("--icon", default=None, help="header icon name")
    ap.add_argument("--columns", type=int, default=3)
    ap.add_argument("--back", action="store_true", help="submenu: offer Back (exit status 2)")
    ap.add_argument("--input", action="store_true", help="free-text entry (returns what the user types)")
    args, _unknown = ap.parse_known_args()
    items = [] if args.input else parse_items(sys.stdin.readlines())
    if not items and not args.input:
        return 1
    layout = "input" if args.input else choose_layout(len(items), args.grid, args.list_mode)
    cols = args.columns if layout == "grid" else 1

    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
    import time

    CSS = """
    window.pick { background: #17171a; border: 1px solid #38383e; border-radius: 16px; }
    .pick-title { font-size: 13pt; font-weight: 700; }
    .pick-head image { -gtk-icon-size: 20px; color: @accent_color; }
    .pick entry { min-height: 38px; border-radius: 10px; }
    .tile { background: #212125; border-radius: 14px; padding: 14px 8px 12px 8px; min-width: 128px; min-height: 92px;
            border: 1px solid transparent; transition: background 120ms ease, border-color 120ms ease; }
    .tile:hover { background: #2a2a30; }
    .tile.sel { background: alpha(@accent_bg_color, .18); border-color: alpha(@accent_bg_color, .75); }
    .tile image { -gtk-icon-size: 28px; margin-bottom: 8px; color: @accent_color; }
    .tile-label { font-size: 10.5pt; font-weight: 600; color: #f2f2f5; }
    .tile-sub { font-size: 9pt; color: #a8a8b0; margin-top: 2px; }
    .key { font-family: "JetBrains Mono", monospace; font-size: 8.5pt; font-weight: 700; color: #c4c4ca;
           background: #2c2c31; border-radius: 6px; padding: 1px 6px; margin: 7px; min-width: 9px; }
    .tile.sel .key { background: @accent_bg_color; color: #0e0e10; }
    row.pk { border-radius: 10px; padding: 8px 10px; border: 1px solid transparent; }
    row.pk:hover { background: #2a2a30; }
    row.pk.sel { background: alpha(@accent_bg_color, .18); border-color: alpha(@accent_bg_color, .6); }
    .pk-label { font-size: 11pt; color: #f2f2f5; }
    .pk-sub { font-size: 9pt; color: #a8a8b0; }
    .row-key { font-family: "JetBrains Mono", monospace; font-size: 8.5pt; font-weight: 700; color: #c4c4ca;
               background: #2c2c31; border-radius: 6px; padding: 1px 6px; }
    .empty-title { font-size: 12pt; font-weight: 600; color: #f2f2f5; }
    .hint { font-size: 8.5pt; color: #8b8b92; }
    .thumb { border-radius: 10px; margin-bottom: 8px; }
    """
    result = {"v": None, "code": 1}

    class Win(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title=args.title, default_width=580 if layout == "grid" else 560,
                             css_classes=["pick"], resizable=False)
            self.sel = 0
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                            margin_top=14, margin_start=14, margin_end=14, margin_bottom=12)
            head = Gtk.Box(spacing=8, css_classes=["pick-head"])
            if args.back:
                b = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat", "circular"], tooltip_text="Back (Backspace)")
                b.connect("clicked", lambda *_: self.back()); head.append(b)
            if args.icon:
                head.append(Gtk.Image(icon_name=args.icon))
            head.append(Gtk.Label(label=args.title, xalign=0, css_classes=["pick-title"], hexpand=True,
                                  ellipsize=Pango.EllipsizeMode.END))
            outer.append(head)
            key = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)   # before the entry eats keys
            key.connect("key-pressed", self.on_key); self.add_controller(key)
            self._born = time.time(); self.connect("notify::is-active", self._focus)
            if layout == "input":
                self.entry = Gtk.Entry(placeholder_text=args.placeholder, hexpand=True)
                self.entry.connect("activate", lambda *_: self.done(self.entry.get_text(), 0))
                outer.append(self.entry)
                outer.append(Gtk.Label(label="Enter to confirm · Esc to cancel", xalign=0, css_classes=["hint"]))
                self.set_content(outer); return
            self.search = Gtk.SearchEntry(placeholder_text=args.placeholder)
            self.search.connect("search-changed", lambda *_: (setattr(self, "sel", 0), self.refill()))
            # Quick pick by the text itself, so it works however the keystroke arrives (key event or input method):
            # a single digit typed into an empty search chooses that numbered item.
            self._prev = ""
            self.search.connect("changed", self._typed)
            outer.append(self.search)
            if layout == "grid":
                self.container = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=cols,
                                             min_children_per_line=cols, homogeneous=True,
                                             row_spacing=10, column_spacing=10, valign=Gtk.Align.START)
            else:
                self.container = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["navigation-sidebar"])
                self.container.connect("row-activated", lambda _l, r: self.done(r.label, 0))
            self.sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                         max_content_height=600 if layout == "grid" else 480)
            self.sw.set_child(self.container)
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=26, margin_bottom=26, halign=Gtk.Align.CENTER)
            empty.append(Gtk.Image(icon_name="edit-find-symbolic", pixel_size=36, opacity=0.5))
            self.empty_title = Gtk.Label(css_classes=["empty-title"], ellipsize=Pango.EllipsizeMode.END, max_width_chars=40)
            empty.append(self.empty_title)
            empty.append(Gtk.Label(label="Esc clears the search", css_classes=["hint"]))
            clear = Gtk.Button(label="Clear search", css_classes=["pill"], halign=Gtk.Align.CENTER, margin_top=6)
            clear.connect("clicked", lambda *_: (self.search.set_text(""), self.search.grab_focus())); empty.append(clear)
            self.empty = empty
            outer.append(self.sw); outer.append(empty)
            hint = ("↑↓←→ move" if layout == "grid" else "↑↓ move") + " · Enter choose · 1–9 pick · Esc close"
            if args.back: hint += " · ⌫ back"
            outer.append(Gtk.Label(label=hint, xalign=0, css_classes=["hint"]))
            self.set_content(outer)
            self.refill()

        def _typed(self, entry):
            text, prev = entry.get_text(), self._prev
            self._prev = text
            if prev == "" and len(text) == 1 and text in "123456789":
                if int(text) <= len(items):
                    GLib.idle_add(lambda: self.done(items[int(text) - 1][0], 0) or False)
                else:
                    GLib.idle_add(lambda: entry.set_text("") or False)    # no such item: ignore the digit

        def _focus(self, *_):
            if not self.is_active() and time.time() - self._born > 0.6:
                self.close()

        def visible(self):
            return [it for it in items if matches(it, self.search.get_text())]

        def refill(self):
            self.container.remove_all()
            self.widgets = []
            vis = self.visible()
            self.sw.set_visible(bool(vis)); self.empty.set_visible(not vis)
            if not vis:
                self.empty_title.set_label(f"No matches for “{self.search.get_text()}”")
            for i, (label, icon, sub) in enumerate(vis):
                num = str(i + 1) if i < 9 else ""
                if layout == "grid":
                    btn = Gtk.Button(css_classes=["tile"], focusable=False)
                    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
                    if icon and icon.startswith("/"):
                        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, css_classes=["thumb"], can_shrink=True)
                        pic.set_size_request(150, 90)
                        try: pic.set_filename(icon)
                        except Exception: pass
                        col.append(pic)
                    elif icon:
                        col.append(Gtk.Image(icon_name=icon))
                    col.append(Gtk.Label(label=label, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=16,
                                         css_classes=["tile-label"]))
                    if sub:
                        col.append(Gtk.Label(label=sub, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=18,
                                             lines=2, ellipsize=Pango.EllipsizeMode.END, css_classes=["tile-sub"]))
                    ov = Gtk.Overlay(); ov.set_child(col)
                    if num:
                        ov.add_overlay(Gtk.Label(label=num, css_classes=["key"], halign=Gtk.Align.START, valign=Gtk.Align.START))
                    btn.set_child(ov)
                    btn.connect("clicked", lambda _b, l=label: self.done(l, 0))
                    self.container.append(btn); self.widgets.append(btn)
                else:
                    row = Gtk.ListBoxRow(css_classes=["pk"]); row.label = label
                    r = Gtk.Box(spacing=11)
                    if icon:
                        r.append(Gtk.Image(icon_name=icon, pixel_size=20))
                    txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
                    txt.append(Gtk.Label(label=label, xalign=0, css_classes=["pk-label"], ellipsize=Pango.EllipsizeMode.END))
                    if sub:
                        txt.append(Gtk.Label(label=sub, xalign=0, css_classes=["pk-sub"], ellipsize=Pango.EllipsizeMode.END))
                    r.append(txt)
                    if num:
                        r.append(Gtk.Label(label=num, css_classes=["row-key"], valign=Gtk.Align.CENTER))
                    row.set_child(r); self.container.append(row); self.widgets.append(row)
            self.highlight()

        def highlight(self):
            for i, w in enumerate(self.widgets):
                (w.add_css_class if i == self.sel else w.remove_css_class)("sel")
            if self.widgets:     # keep the keyboard selection in view (grid and list)
                adj = self.sw.get_vadjustment(); w = self.widgets[min(self.sel, len(self.widgets) - 1)]
                ok, rect = w.compute_bounds(self.container)
                if ok:
                    y, h, pad = rect.get_y(), rect.get_height(), 8
                    if y - pad < adj.get_value(): adj.set_value(max(y - pad, 0))
                    elif y + h + pad > adj.get_value() + adj.get_page_size(): adj.set_value(y + h + pad - adj.get_page_size())

        def on_key(self, _c, keyval, _code, state):
            if layout == "input":
                if keyval == Gdk.KEY_Escape: self.close(); return True
                return False
            text = self.search.get_text()
            if keyval == Gdk.KEY_Escape:
                if text: self.search.set_text(""); return True
                self.close(); return True
            if keyval == Gdk.KEY_BackSpace and not text and args.back:
                self.back(); return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                vis = self.visible()
                if vis: self.done(vis[min(self.sel, len(vis) - 1)][0], 0)
                return True
            if Gdk.KEY_1 <= keyval <= Gdk.KEY_9 and not text and not state & Gdk.ModifierType.CONTROL_MASK:
                idx = keyval - Gdk.KEY_1; vis = self.visible()
                if idx < len(vis): self.done(vis[idx][0], 0)
                return True
            arrows = {Gdk.KEY_Up: "up", Gdk.KEY_Down: "down", Gdk.KEY_Left: "left", Gdk.KEY_Right: "right", Gdk.KEY_Tab: "right"}
            if keyval in arrows and (layout == "grid" or keyval in (Gdk.KEY_Up, Gdk.KEY_Down)):
                if keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and text:
                    return False                     # editing the search text
                self.sel = nav(self.sel, arrows[keyval], len(self.widgets), cols); self.highlight(); return True
            return False

        def back(self):
            self.done(None, 2)

        def done(self, value, code):
            result["v"], result["code"] = value, code; self.close()

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id="org.myos.Pick", flags=Gio.ApplicationFlags.NON_UNIQUE)

        def do_activate(self):
            prov = Gtk.CssProvider(); prov.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            Win(self).present()

    App().run([])
    if result["code"] == 0 and result["v"] is not None:
        print(result["v"]); return 0
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
