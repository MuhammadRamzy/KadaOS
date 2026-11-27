#!/usr/bin/env python3
"""KadaOS Shortcuts — a categorized, searchable keyboard cheatsheet built from live `hyprctl binds`.

Super+/ opens it. Type to filter, Esc or click-away closes. Grouped so you can scan, not hunt.
"""
import json, subprocess, sys

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

# ───────────────────────── pure logic (tested) ─────────────────────────
KEYSYM = {"slash": "/", "Return": "Enter", "space": "Space", "Escape": "Esc", "Print": "Print",
          "left": "←", "right": "→", "up": "↑", "down": "↓", "Tab": "Tab", "mouse_down": "Scroll ↓",
          "mouse_up": "Scroll ↑", "XF86Launch2": "Omen key", "F4": "F4"}
CATEGORIES = ["Apps & launch", "Windows", "Workspaces", "AI & voice", "Screenshots",
              "Clipboard & capture", "System & session", "Help", "Other"]

def mods_from_mask(mask):
    out = []
    if mask & 64: out.append("Super")
    if mask & 8: out.append("Alt")
    if mask & 4: out.append("Ctrl")
    if mask & 1: out.append("Shift")
    return out

def key_label(key):
    if key.startswith("mouse:"): return None   # pointer binds live in the guide, not the cheatsheet
    return KEYSYM.get(key, key if len(key) > 1 else key.upper())

def categorize(desc, dispatcher):
    d = desc.lower()
    if dispatcher in ("workspace", "movetoworkspace", "movetoworkspacesilent", "togglespecialworkspace"): return "Workspaces"
    if dispatcher in ("movefocus", "movewindow", "resizeactive", "togglefloating", "fullscreen", "pseudo",
                      "togglesplit", "pin", "killactive", "cyclenext", "swapwindow", "centerwindow"): return "Windows"
    if "screenshot" in d: return "Screenshots"
    if "clipboard" in d or "color picker" in d: return "Clipboard & capture"
    if any(k in d for k in ("dictat", "voice", "ocr", "search files", "ai ", "ai:", "ai chat", "ai on")): return "AI & voice"
    if any(k in d for k in ("terminal", "browser", "file manager", "launcher", "agent", "claude", "codex",
                            "obsidian", "security lab", "vs code")): return "Apps & launch"
    if "help" in d or "guide" in d: return "Help"
    if any(k in d for k in ("wi-fi", "night", "power", "lock", "settings", "notification", "disturb", "wallpaper",
                            "tablet", "hz", "reload", "mouse", "brightness", "volume", "task manager")): return "System & session"
    return "Other"

def build_groups(binds):
    """[(category, [(keys:list[str], description)])] in CATEGORIES order, de-duplicated."""
    groups = {c: [] for c in CATEGORIES}; seen = set()
    for b in binds:
        desc = (b.get("description") or "").strip()
        if not desc: continue
        kl = key_label(b.get("key", ""))
        if kl is None: continue
        combo = tuple(mods_from_mask(b.get("modmask", 0)) + [kl])
        sig = (combo, desc)
        if sig in seen: continue
        seen.add(sig)
        groups[categorize(desc, b.get("dispatcher", ""))].append((list(combo), desc))
    return [(c, groups[c]) for c in CATEGORIES if groups[c]]

# ───────────────────────── UI ─────────────────────────
CSS = """
/* dark glass: Hyprland still blurs the wallpaper behind, but text stays readable on bright wallpapers */
window.cheats { border-radius: 18px; background: alpha(#17171a, .92); }
.cheat-title { font-size: 18pt; font-weight: 800; }
.cat { font-size: 11pt; font-weight: 700; color: @accent_color; margin: 14px 4px 2px 4px; }
.keycap { background: alpha(@view_fg_color, .10); border-radius: 7px; padding: 1px 9px;
          font-family: "Adwaita Mono", monospace; font-size: 10pt; min-width: 10px; }
.keyplus { color: alpha(@view_fg_color, .4); font-size: 9pt; }
.krow { padding: 6px 8px; border-radius: 9px; }
.krow:hover { background: alpha(@view_fg_color, .05); }
.kdesc { font-size: 10.5pt; }
"""

def run_app():
    class Win(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Keyboard Shortcuts", default_width=880, default_height=720,
                             css_classes=["cheats"])
            self.rows = []
            tv = Adw.ToolbarView(); hb = Adw.HeaderBar(show_title=False)
            hb.set_title_widget(Gtk.Label(label="Keyboard Shortcuts", css_classes=["cheat-title"])); tv.add_top_bar(hb)
            self.search = Gtk.SearchEntry(placeholder_text="Search shortcuts (e.g. screenshot, workspace, AI)",
                                          margin_start=16, margin_end=16, margin_top=12, margin_bottom=4)
            self.search.connect("search-changed", self.filter)
            self.search.connect("stop-search", lambda *_: self.close())
            self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=16, margin_end=16, margin_bottom=16)
            sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER); sw.set_child(self.box)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); body.append(self.search); body.append(sw)
            self.empty = Adw.StatusPage(icon_name="edit-find-symbolic", title="No matching shortcuts", vexpand=True)
            self.stack = Gtk.Stack(); self.stack.add_named(body, "list"); self.stack.add_named(self.empty, "empty")
            tv.set_content(self.stack); self.set_content(tv)
            self.build()
            key = Gtk.EventControllerKey(); key.connect("key-pressed", self.on_key); self.add_controller(key)
            self.connect("notify::is-active", lambda *_: (not self.is_active()) and self.close())

        def build(self):
            try:
                sig = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, timeout=5).stdout
                groups = build_groups(json.loads(sig))
            except Exception as e:
                self.box.append(Gtk.Label(label=f"Could not read shortcuts: {e}", css_classes=["dim-label"])); return
            for cat, items in groups:
                self.box.append(Gtk.Label(label=cat, css_classes=["cat"], xalign=0))
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
                cat_rows = []
                for i, (keys, desc) in enumerate(items):
                    row = Gtk.Box(spacing=12, css_classes=["krow"])
                    kb = Gtk.Box(spacing=3, halign=Gtk.Align.START); kb.set_size_request(230, -1)
                    for j, k in enumerate(keys):
                        if j: kb.append(Gtk.Label(label="+", css_classes=["keyplus"], valign=Gtk.Align.CENTER))
                        kb.append(Gtk.Label(label=k, css_classes=["keycap"], valign=Gtk.Align.CENTER))
                    row.append(kb)
                    row.append(Gtk.Label(label=desc, xalign=0, hexpand=True, wrap=True, css_classes=["kdesc"]))
                    card.append(row)
                    if i < len(items) - 1: card.append(Gtk.Separator(css_classes=["spacer"]))
                    haystack = (" ".join(keys) + " " + desc + " " + cat).lower()
                    self.rows.append((row, haystack)); cat_rows.append(row)
                self.box.append(card)

        def filter(self, *_):
            q = self.search.get_text().lower().strip()
            any_vis = False
            for row, hay in self.rows:
                vis = all(w in hay for w in q.split())
                row.set_visible(vis); any_vis |= vis
            # hide a category card + its heading when all its rows are filtered out
            child = self.box.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                if isinstance(child, Gtk.Label) and "cat" in child.get_css_classes():
                    card = nxt
                    rows_vis = card and any(r.get_visible() for r, _ in self.rows if r.get_parent() is card)
                    child.set_visible(bool(rows_vis)); card and card.set_visible(bool(rows_vis))
                child = nxt
            self.stack.set_visible_child_name("list" if any_vis or not q else "empty")

        def on_key(self, _c, keyval, *_):
            if keyval == Gdk.KEY_Escape: self.close(); return True
            return False

    class App(Adw.Application):
        def __init__(self): super().__init__(application_id="org.myos.Shortcuts", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        def do_activate(self):
            if (w := self.props.active_window): w.present(); return
            prov = Gtk.CssProvider(); prov.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            Win(self).present()

    return App().run(sys.argv)

if __name__ == "__main__":
    sys.exit(run_app())
