#!/usr/bin/env python3
"""KadaOS Quick Settings — native live panels: Wi-Fi, Bluetooth, Clipboard history.

  panel.py wifi | bluetooth | clipboard | calendar | inbox | remote | phone | storage | security | battery | projects | services | tasks   open that page (again = close; another page = switch)

One resident GTK4/libadwaita process: the first open takes ~1 s, later opens are instant. Pages listen to
NetworkManager / BlueZ / the clipboard database, so they update live while open. Closes on Esc or focus loss.
"""
import json, os, shlex, subprocess, sys, threading, time
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("NM", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, NM, Pango

HOME = Path.home()
CLIPDB = HOME / ".cache/cliphist/db"
PINS = HOME / ".local/share/myos/clipboard-pins.json"
W, H = 400, 600

# ───────────────────────── pure helpers (tested) ─────────────────────────
def signal_icon(strength):
    s = "excellent" if strength >= 75 else "good" if strength >= 50 else "ok" if strength >= 25 else "weak"
    return f"network-wireless-signal-{s}-symbolic"

def ap_secured(flags, wpa, rsn):
    return bool(flags & 1) or bool(wpa) or bool(rsn)   # NM_802_11_AP_FLAGS_PRIVACY or any WPA/RSN flags

def ap_enterprise(wpa, rsn):
    return bool((wpa | rsn) & 0x200)                   # NM_802_11_AP_SEC_KEY_MGMT_802_1X

def best_networks(aps):
    """aps: dicts(ssid, strength, ...). One row per SSID (strongest), hidden SSIDs dropped, strongest first."""
    best = {}
    for a in aps:
        if a["ssid"] and (a["ssid"] not in best or a["strength"] > best[a["ssid"]]["strength"]): best[a["ssid"]] = a
    return sorted(best.values(), key=lambda a: (not a.get("active"), -a["strength"], a["ssid"].lower()))

def parse_cliphist(lines):
    """cliphist list lines -> [(id, preview, is_image)]."""
    out, seen = [], set()
    for line in lines:
        if "\t" not in line: continue
        cid, prev = line.split("\t", 1)
        if prev in seen: continue          # same text copied again: keep only the newest
        seen.add(prev)
        out.append((cid, prev, prev.startswith("[[ binary data") and any(t in prev for t in ("png", "jpeg", "jpg", "webp", "bmp", "gif"))))
    return out

def panel_origin(mon, width, right=10, top=8, bar=32):  # same margins as the notification centre (swaync)
    """Top-left for a panel: every bar item that opens one (clock, Wi-Fi, Bluetooth…) sits at the right end
    of the top bar, so panels drop down at the top-right, just under the bar."""
    mw = int(mon["width"] / mon["scale"])
    return mon["x"] + mw - width - right, mon["y"] + bar + top

def thumb_texture(data, width):
    """Decode an image already scaled down to `width` px (never holds the full-size pixels)."""
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    loader = GdkPixbuf.PixbufLoader()
    def size(l, w, h):                 # use the loader passed in: closing over `loader` makes a cycle that keeps
        if w > width: l.set_size(width, max(1, h * width // w))       # the full-size decoder alive (~25 MB each)
    loader.connect("size-prepared", size)
    loader.write(data); loader.close()
    pb = loader.get_pixbuf()
    return Gdk.Texture.new_for_pixbuf(pb) if pb else None

# ───────────────────────── shared UI helpers ─────────────────────────
CSS = """
window.panel { border-radius: 16px; background: alpha(#17171a, .92); }  /* dark glass: readable over white pages */
.panel-title { font-size: 15pt; font-weight: 700; }
.clip-text { font-family: "Adwaita Mono", monospace; font-size: 10pt; }
.clip-thumb { border-radius: 8px; }
.hint { font-size: 9pt; }
.cal-time { font-size: 30pt; font-weight: 800; }
.cal-date { font-size: 11pt; opacity: .65; margin-top: -2px; }
calendar { font-size: 11pt; padding: 4px; }
calendar:selected { background: @accent_bg_color; color: @accent_fg_color; border-radius: 8px; }
calendar.highlight, calendar:backdrop.highlight { color: @accent_color; font-weight: 800; }
.cal-up { font-size: 10pt; font-weight: 700; opacity: .6; }
.cal-ev { padding: 6px 8px; border-radius: 9px; }
.cal-ev:hover { background: alpha(@view_fg_color, .05); }
.cal-ev-when { font-size: 9pt; opacity: .75; }
.cal-ev-title { font-size: 11pt; }
.cal-ev-cal { font-size: 8.5pt; opacity: .5; }
.phone-card { padding-top: 6px; padding-bottom: 6px; }
.phone-icon.on { color: @accent_color; }
.phone-icon.away { opacity: .45; }
.phone-action { border-radius: 14px; padding: 0; }
.storage-free { font-size: 13pt; }
.sec-headline { font-size: 13pt; font-weight: 700; }
.bat-big { font-size: 26pt; }
.bat-chart { margin: 0 6px; }
progressbar.disk-bar trough, progressbar.disk-bar progress { min-height: 8px; border-radius: 99px; }
progressbar.disk-bar.warn progress { background: @warning_color; }
progressbar.disk-bar.crit progress { background: @error_color; }
"""

def header(title, extra=None):
    box = Gtk.Box(spacing=8, margin_start=18, margin_end=14, margin_top=14, margin_bottom=6)
    box.append(Gtk.Label(label=title, css_classes=["panel-title"], hexpand=True, xalign=0))
    if extra: box.append(extra)
    return box

def footer_button(label, cmd, win):
    b = Gtk.Button(label=label, css_classes=["flat"], margin_bottom=8)
    def run(*_):
        win.hide_panel(); subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    b.connect("clicked", run); return b

def scroller(child):
    sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    clamp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=12, margin_end=12, margin_bottom=8); clamp.append(child)
    sw.set_child(clamp); return sw

def status(icon, title, desc=""):
    return Adw.StatusPage(icon_name=icon, title=title, description=desc, vexpand=True, css_classes=["compact"])

# ───────────────────────── Wi-Fi (NetworkManager, live) ─────────────────────────
class WifiPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.client, self.dev, self.pending = win, None, None, None
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Wi-Fi on/off")
        self.switch.update_property([Gtk.AccessibleProperty.LABEL], ["Wi-Fi"])
        self.spinner = Adw.Spinner(visible=False, tooltip_text="Scanning")
        hb = Gtk.Box(spacing=10); hb.append(self.spinner); hb.append(self.switch)
        self.append(header("Wi-Fi", hb))
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.group = Adw.PreferencesGroup(); self.stack.add_named(scroller(self.group), "list")
        self.off = status("network-wireless-disabled-symbolic", "Wi-Fi is off", "Turn it on to see networks.")
        self.none = status("network-wireless-no-route-symbolic", "No Wi-Fi adapter", "No wireless device was found.")
        self.empty = status("network-wireless-acquiring-symbolic", "Looking for networks…")
        for n, w in (("off", self.off), ("none", self.none), ("empty", self.empty)): self.stack.add_named(w, n)
        self.append(self.stack)
        self.append(footer_button("Wi-Fi settings…", ["gnome-control-center", "wifi"], win))
        self._timer = 0
        NM.Client.new_async(None, self._ready)

    def _ready(self, _src, res):
        try: self.client = NM.Client.new_finish(res)
        except GLib.Error as e: self.stack.set_visible_child(status("dialog-error-symbolic", "NetworkManager unavailable", e.message)); return
        self.switch.set_active(self.client.wireless_get_enabled())
        self.switch.connect("notify::active", lambda s, _p: self.client.wireless_get_enabled() != s.get_active()
                            and self.client.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, "WirelessEnabled",
                                                              GLib.Variant("b", s.get_active()), -1, None, None))
        self.client.connect("notify::wireless-enabled", lambda *_: (self.switch.set_active(self.client.wireless_get_enabled()), self.refresh_soon()))
        self.client.connect("device-added", lambda *_: self._pick_device()); self.client.connect("device-removed", lambda *_: self._pick_device())
        self._pick_device()

    def _pick_device(self):
        self.dev = next((d for d in self.client.get_devices() if isinstance(d, NM.DeviceWifi)), None)
        if self.dev:
            for sig in ("access-point-added", "access-point-removed", "notify::active-access-point", "state-changed", "notify::last-scan"):
                self.dev.connect(sig, lambda *a: self.refresh_soon())
        self.refresh(); self.scan()

    def on_show(self): self.scan(); self.refresh()

    def scan(self):
        if self.dev and self.client and self.client.wireless_get_enabled():
            self.spinner.set_visible(True)
            self.dev.request_scan_async(None, lambda d, r: self._scanned(d, r))

    def _scanned(self, dev, res):
        try: dev.request_scan_finish(res)
        except GLib.Error: pass   # "scan already running" is normal
        GLib.timeout_add(2500, lambda: self.spinner.set_visible(False) or False)

    def refresh_soon(self):  # coalesce bursts of AP/strength signals
        if not self._timer: self._timer = GLib.timeout_add(400, self._tick)
    def _tick(self): self._timer = 0; self.refresh(); return False

    def refresh(self):
        if not self.client: return
        if not self.dev: self.stack.set_visible_child_name("none"); return
        if not self.client.wireless_get_enabled(): self.stack.set_visible_child_name("off"); return
        active = self.dev.get_active_access_point()
        known = {c.get_setting_wireless().get_ssid().get_data().decode(errors="replace"): c
                 for c in self.client.get_connections() if c.get_setting_wireless() and c.get_setting_wireless().get_ssid()}
        aps = []
        for ap in self.dev.get_access_points():
            ssid = ap.get_ssid().get_data().decode(errors="replace") if ap.get_ssid() else ""
            aps.append({"ssid": ssid, "strength": ap.get_strength(), "ap": ap, "active": bool(active and ap.get_path() == active.get_path()),
                        "secured": ap_secured(int(ap.get_flags()), int(ap.get_wpa_flags()), int(ap.get_rsn_flags())),
                        "enterprise": ap_enterprise(int(ap.get_wpa_flags()), int(ap.get_rsn_flags()))})
        nets = best_networks(aps)
        self.stack.remove(self.stack.get_child_by_name("list")); self.group = Adw.PreferencesGroup()
        self.stack.add_named(scroller(self.group), "list")
        state = self.dev.get_state()
        for n in nets:
            row = Adw.ActionRow(title=GLib.markup_escape_text(n["ssid"]), activatable=True)
            row.add_prefix(Gtk.Image(icon_name=signal_icon(n["strength"])))
            sub = []
            if n["active"]: sub.append("Connected" if state == NM.DeviceState.ACTIVATED else "Connecting…")
            elif n["ssid"] == self.pending: sub.append("Connecting…")
            elif n["ssid"] in known: sub.append("Saved")
            if n["enterprise"]: sub.append("Enterprise")
            row.set_subtitle(" · ".join(sub))
            if n["secured"]: row.add_suffix(Gtk.Image(icon_name="system-lock-screen-symbolic", tooltip_text="Secured", css_classes=["dim-label"]))
            if n["active"]:
                b = Gtk.Button(label="Disconnect", valign=Gtk.Align.CENTER, css_classes=["flat"])
                b.connect("clicked", lambda *_: self.dev.disconnect_async(None, None)); row.add_suffix(b)
            else:
                row.connect("activated", lambda _r, n=n: self.connect_to(n, known.get(n["ssid"])))
            self.group.add(row)
        self.stack.set_visible_child_name("list" if nets else "empty")

    def connect_to(self, n, conn):
        self.pending = n["ssid"]; self.refresh()
        done = lambda c, r: self._activated(c.add_and_activate_connection_finish, r, n["ssid"])
        if conn:
            self.client.activate_connection_async(conn, self.dev, n["ap"].get_path(), None,
                                                  lambda c, r: self._activated(c.activate_connection_finish, r, n["ssid"])); return
        if n["enterprise"]:
            self.win.toast("Enterprise network: finish setup in Wi-Fi settings")
            subprocess.Popen(["gnome-control-center", "wifi"], start_new_session=True); return
        if not n["secured"]:
            self.client.add_and_activate_connection_async(None, self.dev, n["ap"].get_path(), None, done); return
        d = Adw.AlertDialog(heading=f"Connect to “{n['ssid']}”", body="Enter the network password.")
        e = Adw.PasswordEntryRow(title="Password", activates_default=True); g = Adw.PreferencesGroup(); g.add(e)
        d.set_extra_child(g); d.add_response("cancel", "Cancel"); d.add_response("ok", "Connect")
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED); d.set_default_response("ok"); d.set_close_response("cancel")
        def resp(_d, r):
            if r != "ok" or not e.get_text(): self.pending = None; self.refresh(); return
            c = NM.SimpleConnection.new(); sec = NM.SettingWirelessSecurity.new()
            sec.set_property("key-mgmt", "wpa-psk"); sec.set_property("psk", e.get_text()); c.add_setting(sec)
            self.client.add_and_activate_connection_async(c, self.dev, n["ap"].get_path(), None, done)
        d.connect("response", resp); d.present(self.win); GLib.idle_add(e.grab_focus)

    def _activated(self, finish, res, ssid):
        try: finish(res)
        except GLib.Error as e: self.win.toast(f"Couldn't connect to {ssid}: {e.message}")
        self.pending = None; self.refresh_soon()

# ───────────────────────── Bluetooth (GNOME Bluetooth, live) ─────────────────────────
class BluetoothPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Bluetooth on/off")
        self.switch.update_property([Gtk.AccessibleProperty.LABEL], ["Bluetooth"])
        self.append(header("Bluetooth", self.switch))
        self.stack = Gtk.Stack(vexpand=True); self.append(self.stack)
        self.append(footer_button("Pair a new device…", ["blueman-manager"], win))
        try:
            gi.require_version("GnomeBluetooth", "3.0"); from gi.repository import GnomeBluetooth
            self.client = GnomeBluetooth.Client()
        except Exception as e:
            self.client = None; self.stack.add_named(status("bluetooth-disabled-symbolic", "Bluetooth unavailable", str(e)), "err"); return
        self.client.connect("notify::default-adapter-powered", lambda *_: self.refresh())
        self.client.connect("notify::default-adapter", lambda *_: self.refresh())
        self.switch.connect("notify::active", self._toggle)
        self.devices = self.client.get_devices()
        self.devices.connect("items-changed", lambda *_: self.refresh())
        self._watched = set(); self.refresh()

    def _toggle(self, s, _p):
        if self.client and self.client.props.default_adapter_powered != s.get_active():
            self.client.props.default_adapter_powered = s.get_active()

    def on_show(self): self.refresh()

    def refresh(self):
        if not self.client: return
        has = bool(self.client.props.default_adapter); on = has and self.client.props.default_adapter_powered
        self.switch.set_sensitive(has); self.switch.set_active(bool(on))
        old = self.stack.get_child_by_name("view")
        if old: self.stack.remove(old)
        if not has: view = status("bluetooth-disabled-symbolic", "No Bluetooth adapter", "Try: rfkill unblock bluetooth")
        elif not on: view = status("bluetooth-disabled-symbolic", "Bluetooth is off", "Turn it on to use your devices.")
        else:
            group = Adw.PreferencesGroup(title="My devices")
            devs = [self.devices.get_item(i) for i in range(self.devices.get_n_items())]
            devs = sorted([d for d in devs if d.props.paired or d.props.connected], key=lambda d: (not d.props.connected, (d.props.alias or "").lower()))
            for d in devs:
                if d.props.path not in self._watched:
                    self._watched.add(d.props.path)
                    for p in ("connected", "battery-percentage", "alias"): d.connect(f"notify::{p}", lambda *_: GLib.idle_add(self.refresh))
                row = Adw.ActionRow(title=GLib.markup_escape_text(d.props.alias or d.props.name or d.props.address or "Device"))
                row.add_prefix(Gtk.Image(icon_name=(d.props.icon or "bluetooth") + "-symbolic" if not (d.props.icon or "").endswith("symbolic") else d.props.icon))
                sub = ["Connected" if d.props.connected else "Not connected"]
                try:
                    if d.props.battery_percentage > 0: sub.append(f"{d.props.battery_percentage:.0f}% battery")
                except Exception: pass
                row.set_subtitle(" · ".join(sub))
                b = Gtk.Button(label="Disconnect" if d.props.connected else "Connect", valign=Gtk.Align.CENTER,
                               css_classes=["flat"] if d.props.connected else ["suggested-action"])
                b.connect("clicked", lambda btn, d=d: self.toggle_device(btn, d)); row.add_suffix(b); group.add(row)
            view = scroller(group) if devs else status("bluetooth-active-symbolic", "No paired devices", "Use “Pair a new device…” below.")
        self.stack.add_named(view, "view"); self.stack.set_visible_child(view)
        return False

    def toggle_device(self, btn, d):
        btn.set_sensitive(False); btn.set_label("Connecting…" if not d.props.connected else "Disconnecting…")
        def done(c, res):
            try: c.connect_service_finish(res)
            except GLib.Error as e: self.win.toast(f"{d.props.alias}: {e.message}")
            self.refresh()
        self.client.connect_service(d.props.path, not d.props.connected, None, done)

# ───────────────────────── Clipboard history (cliphist, live) ─────────────────────────
class ClipboardPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        clear = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Clear history", css_classes=["flat", "circular"])
        clear.connect("clicked", self.clear_all)
        self.append(header("Clipboard", clear))
        self.search = Gtk.SearchEntry(placeholder_text="Search clipboard", margin_start=12, margin_end=12, margin_bottom=6)
        self.search.connect("search-changed", lambda *_: self.refresh())
        self.search.connect("activate", lambda *_: self.activate_first())
        self.search.connect("stop-search", lambda *_: win.hide_panel())
        self.append(self.search)
        self.list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.BROWSE)
        self.list.connect("row-activated", lambda _l, r: self.paste(r))
        self.empty = status("edit-paste-symbolic", "Nothing copied yet", "Things you copy appear here.")
        self.stack = Gtk.Stack(vexpand=True); self.stack.add_named(scroller(self.list), "list"); self.stack.add_named(self.empty, "empty")
        self.append(self.stack)
        self.append(Gtk.Label(label="Enter paste · Del remove · Esc close", css_classes=["dim-label", "hint"], margin_bottom=10))
        key = Gtk.EventControllerKey(); key.connect("key-pressed", self.on_key); self.add_controller(key)
        self.thumbs, self._loading = {}, {}
        import concurrent.futures
        self._thumb_pool = concurrent.futures.ThreadPoolExecutor(2)      # at most two decodes at once
        if CLIPDB.exists():
            self.mon = Gio.File.new_for_path(str(CLIPDB)).monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.mon.connect("changed", lambda *_: self.win.is_visible() and self.win.page == "clipboard" and self.refresh_soon())
        self._timer = 0

    def refresh_soon(self):
        if not self._timer: self._timer = GLib.timeout_add(300, lambda: (setattr(self, "_timer", 0), self.refresh())[1] or False)

    def on_show(self): self.search.set_text(""); self.refresh(); self.search.grab_focus()

    def entries(self):
        # cliphist cuts previews mid-character, so decode leniently (strict decoding hid the whole history)
        try: out = subprocess.run(["cliphist", "list"], capture_output=True, timeout=5).stdout.decode("utf-8", "replace")
        except Exception: return []
        return parse_cliphist(out.splitlines()[:300])

    def refresh(self):
        q = self.search.get_text().lower().strip()
        while (r := self.list.get_row_at_index(0)): self.list.remove(r)
        items = [e for e in self.entries() if not q or (not e[2] and q in e[1].lower())]
        for cid, prev, img in items[:150]:
            row = Gtk.ListBoxRow(); row.cid = cid
            box = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=10, margin_end=6)
            if img:
                pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, css_classes=["clip-thumb"], can_shrink=True)
                pic.set_size_request(-1, 90); pic.set_hexpand(True); self._thumb(cid, pic); box.append(pic)
                row.update_property([Gtk.AccessibleProperty.LABEL], ["Image"])
            else:
                lbl = Gtk.Label(label=prev.strip()[:400], xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, lines=3,
                                ellipsize=Pango.EllipsizeMode.END, hexpand=True, css_classes=["clip-text"])
                box.append(lbl)
            rm = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"], valign=Gtk.Align.START, tooltip_text="Remove")
            rm.connect("clicked", lambda _b, row=row: self.remove(row)); box.append(rm)
            row.set_child(box); self.list.append(row)
        self.stack.set_visible_child_name("list" if items else "empty")
        self.empty.set_title("No matches" if q else "Nothing copied yet")
        if (first := self.list.get_row_at_index(0)): self.list.select_row(first)

    THUMB_W, THUMB_CACHE = 760, 40     # decode at row size (2× for HiDPI): a 4K screenshot is ~1 MB here, not 32 MB

    def _thumb(self, cid, pic):
        if cid in self.thumbs:
            self.thumbs[cid] = self.thumbs.pop(cid); pic.set_paintable(self.thumbs[cid]); return   # LRU touch
        if cid in self._loading: self._loading[cid].append(pic); return
        self._loading[cid] = [pic]
        def load():
            tex = None
            try:
                data = subprocess.run(["cliphist", "decode", cid], input=b"", capture_output=True, timeout=5).stdout
                tex = thumb_texture(data, self.THUMB_W)
            except Exception: pass
            GLib.idle_add(done, tex)
        def done(tex):
            pics = self._loading.pop(cid, [])
            if tex:
                self.thumbs[cid] = tex
                while len(self.thumbs) > self.THUMB_CACHE: self.thumbs.pop(next(iter(self.thumbs)))
                for p in pics: p.set_paintable(tex)
            return False
        self._thumb_pool.submit(load)

    def _line(self, cid):
        return next((f"{c}\t{p}" for c, p, _ in self.entries() if c == cid), None)

    def paste(self, row):
        line = self._line(row.cid)
        if not line: self.refresh(); return
        data = subprocess.run(["cliphist", "decode"], input=line.encode(), capture_output=True).stdout
        subprocess.run(["wl-copy"], input=data)
        self.win.hide_panel()
        # focus returns to the previous window, then paste there (like Win+V)
        GLib.timeout_add(180, lambda: subprocess.Popen(["wtype", "-M", "ctrl", "v", "-m", "ctrl"]) and False)

    def activate_first(self):
        r = self.list.get_selected_row() or self.list.get_row_at_index(0)
        if r: self.paste(r)

    def remove(self, row):
        line = self._line(row.cid)
        if line: subprocess.run(["cliphist", "delete"], input=line.encode())
        self.refresh()

    def clear_all(self, *_):
        d = Adw.AlertDialog(heading="Clear clipboard history?", body="All saved clipboard items will be deleted.")
        d.add_response("cancel", "Cancel"); d.add_response("clear", "Clear")
        d.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "clear" and (subprocess.run(["cliphist", "wipe"]), self.refresh()))
        d.present(self.win)

    def on_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Delete and (r := self.list.get_selected_row()): self.remove(r); return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up) and self.search.has_focus():
            r = self.list.get_selected_row(); i = (r.get_index() if r else -1) + (1 if keyval == Gdk.KEY_Down else -1)
            if (n := self.list.get_row_at_index(max(i, 0))): self.list.select_row(n); n.grab_focus()
            return True
        return False

# ───────────────────────── calendar events (EDS/GOA) ─────────────────────────
def calendar_events(days=14, limit=25):
    """Upcoming events from the GNOME Online Accounts calendars via Evolution Data Server.
    Returns [(timestamp, summary, calendar_name, all_day)], soonest first. [] if EDS is unavailable.
    Each calendar is queried in parallel with a short wait so one slow source can't stall the panel."""
    try:
        import gi
        gi.require_version("EDataServer", "1.2"); gi.require_version("ECal", "2.0")
        from gi.repository import EDataServer, ECal
        import datetime, concurrent.futures
    except Exception:
        return []
    try:
        reg = EDataServer.SourceRegistry.new_sync(None)
    except Exception:
        return []
    now = datetime.datetime.now()
    start = int(datetime.datetime(now.year, now.month, now.day).timestamp())
    end = start + days * 86400

    def one(s):
        ev, name = [], s.get_display_name()
        def cb(comp, istart, iend, _c=None, _u=None):
            try:
                ev.append((istart.as_timet(), comp.get_summary() or "(no title)", name, istart.is_date()))
            except Exception:
                pass
            return True
        try:
            c = ECal.Client.connect_sync(s, ECal.ClientSourceType.EVENTS, 2, None)
            c.generate_instances_sync(start, end, None, cb, None)
        except Exception:
            pass
        return ev

    srcs = [s for s in reg.list_sources(EDataServer.SOURCE_EXTENSION_CALENDAR) if s.get_enabled()]
    out = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for ev in ex.map(one, srcs):
                out.extend(ev)
    except Exception:
        return []
    out.sort()
    return out[:limit]

# ───────────────────────── window / app ─────────────────────────
class CalendarPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=20, margin_end=20, margin_top=18, margin_bottom=4)
        self.big = Gtk.Label(xalign=0, css_classes=["cal-time"]); self.date = Gtk.Label(xalign=0, css_classes=["cal-date"])
        head.append(self.big); head.append(self.date); self.append(head)
        self.cal = Gtk.Calendar(margin_start=12, margin_end=12, margin_top=6, margin_bottom=6, hexpand=True)
        self.append(self.cal)
        self.up_title = Gtk.Label(label="Upcoming", xalign=0, css_classes=["cal-up"], margin_start=20, margin_top=4, visible=False)
        self.append(self.up_title)
        self.events_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_start=12, margin_end=12)
        esw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER); esw.set_child(self.events_box)
        self.append(esw)
        today = Gtk.Button(label="Today", css_classes=["flat"], margin_bottom=12, margin_top=4, halign=Gtk.Align.CENTER)
        today.connect("clicked", lambda *_: self._today()); self.append(today)
        self._events = []; self._loaded_at = 0
        self._tick()
        GLib.timeout_add_seconds(30, self._tick)

    def on_show(self):
        self._today(); self._tick()
        if time.time() - self._loaded_at > 60:   # cache for a minute
            threading.Thread(target=self._load_events, daemon=True).start()
        else:
            self._render_events()

    def _load_events(self):
        evs = calendar_events()
        GLib.idle_add(self._set_events, evs)

    def _set_events(self, evs):
        self._events = evs; self._loaded_at = time.time(); self._render_events(); return False

    def _render_events(self):
        import datetime
        child = self.events_box.get_first_child()
        while child:
            self.events_box.remove(child); child = self.events_box.get_first_child()
        # mark event days in the shown month
        try:
            self.cal.clear_marks()
            ym = (self.cal.get_date().get_year(), self.cal.get_date().get_month())
            for ts, *_ in self._events:
                d = datetime.date.fromtimestamp(ts)
                if (d.year, d.month) == ym:
                    self.cal.mark_day(d.day)
        except Exception:
            pass
        self.up_title.set_visible(bool(self._events))
        today = datetime.date.today()
        for ts, summ, cal, allday in self._events[:12]:
            d = datetime.datetime.fromtimestamp(ts)
            when = "All day" if allday else d.strftime("%-I:%M %p")
            day = "Today" if d.date() == today else ("Tomorrow" if (d.date() - today).days == 1 else d.strftime("%a %-d %b"))
            row = Gtk.Box(spacing=10, css_classes=["cal-ev"])
            w = Gtk.Label(label=f"{day}\n{when}", xalign=0, css_classes=["cal-ev-when"]); w.set_size_request(92, -1)
            row.append(w)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
            t.append(Gtk.Label(label=summ, xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["cal-ev-title"]))
            t.append(Gtk.Label(label=cal, xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["cal-ev-cal"]))
            row.append(t)
            self.events_box.append(row)

    def _today(self):
        import datetime
        n = datetime.date.today()
        self.cal.select_day(GLib.DateTime.new_local(n.year, n.month, n.day, 0, 0, 0))

    def _tick(self):
        import datetime
        now = datetime.datetime.now()
        self.big.set_text(now.strftime("%-I:%M %p"))
        self.date.set_text(now.strftime("%A, %-d %B %Y"))
        return True


# ───────────────────────── What needs me (secretary inbox) ─────────────────────────
def _secretary():
    import importlib.util
    for p in (Path.home() / ".local/share/local-ai/secretary.py", Path(__file__).resolve().parents[1] / "ai/secretary.py"):
        if p.exists():
            spec = importlib.util.spec_from_file_location("secretary", p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
            return m
    return None

def ago(t, now=None):
    m = int(((now or time.time()) - t) // 60)
    return "now" if m < 1 else (f"{m} min ago" if m < 60 else (f"{m // 60} h ago" if m < 24 * 60 else time.strftime("%a %-d %b", time.localtime(t))))

class InboxPage(Gtk.Box):
    """Everything that needs you in one place: agents waiting or finished, important messages, what's next, warnings."""
    SECTIONS = (("needs", "Needs you", "dialog-question-symbolic"), ("done", "Finished", "emblem-ok-symbolic"),
                ("messages", "Messages", "mail-unread-symbolic"), ("upcoming", "Coming up", "x-office-calendar-symbolic"),
                ("warnings", "Warnings", "dialog-warning-symbolic"))

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.sec, self._events, self._loaded_at = win, _secretary(), [], 0
        self.subtitle = Gtk.Label(xalign=0, css_classes=["dim-label"], margin_start=18, margin_bottom=4)
        self.append(header("What needs you")); self.append(self.subtitle)
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); self.stack.add_named(scroller(self.list), "list")
        self.stack.add_named(status("emblem-ok-symbolic", "All clear", "Nothing needs you right now."), "empty")
        self.append(self.stack)
        clear = Gtk.Button(label="Mark all as done", css_classes=["flat"], margin_bottom=8)
        clear.connect("clicked", lambda *_: (self.sec and self.sec.clear(), self.refresh(), subprocess.Popen(["pkill", "-RTMIN+13", "waybar"])))
        self.append(clear)

    def on_show(self):
        self.refresh()
        if time.time() - self._loaded_at > 120:
            threading.Thread(target=lambda: GLib.idle_add(self._set_events, calendar_events(days=2, limit=10)), daemon=True).start()
        if self.sec: self.sec.mark_seen()                 # opening the inbox = messages read
        subprocess.Popen(["pkill", "-RTMIN+13", "waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _set_events(self, evs):
        self._events, self._loaded_at = evs, time.time(); self.refresh(); return False

    def items(self, now=None):
        now = now or time.time()
        box = self.sec.inbox(now) if self.sec else {"needs": [], "done": [], "messages": [], "warnings": []}
        box["upcoming"] = [{"kind": "event", "title": t, "detail": cal, "t": ts} for ts, t, cal, allday in self._events
                           if not allday and now - 600 <= ts <= now + 36 * 3600][:3]
        return box

    def refresh(self):
        child = self.list.get_first_child()
        while child: self.list.remove(child); child = self.list.get_first_child()
        box, now = self.items(), time.time()
        n = len(box["needs"]) + len(box["done"]) + len(box["messages"])
        self.subtitle.set_text(f"{len(box['needs'])} waiting on you · {n} in total" if n else time.strftime("%A, %-d %B"))
        for key, title, icon in self.SECTIONS:
            if not box[key]: continue
            g = Adw.PreferencesGroup(title=title)
            for it in box[key][:8]:
                when = (time.strftime("%-I:%M %p", time.localtime(it["t"])) if key == "upcoming" else ago(it["t"], now))
                ws = f"\nworkspace {it['ws']}" if it.get("ws") else ""
                row = Adw.ActionRow(title=GLib.markup_escape_text(it["title"]), subtitle=GLib.markup_escape_text(f"{it['detail']}"[:120]),
                                    subtitle_lines=2, title_lines=1)
                row.add_prefix(Gtk.Image(icon_name=icon))
                row.add_suffix(Gtk.Label(label=when + ws, css_classes=["dim-label", "caption"], justify=Gtk.Justification.RIGHT, xalign=1))
                if it.get("address") or key == "upcoming":
                    row.set_activatable(True); row.connect("activated", self._open, it, key)
                g.add(row)
            self.list.append(g)
        self.stack.set_visible_child_name("list" if any(box[k] for k, *_ in self.SECTIONS) else "empty")

    def _open(self, _row, it, key):
        if key == "upcoming": self.win.show_page("calendar"); return
        self.win.hide_panel()
        subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{it['address']}"], capture_output=True)


# ───────────────────────── Remote devices (board) ─────────────────────────
def board_bin():
    import shutil
    return shutil.which("board") or (str(HOME / ".local/bin/board") if (HOME / ".local/bin/board").exists() else None)

def board_json(what, timeout=20):
    b = board_bin()
    if not b: return None
    try: return json.loads(subprocess.run([b, "json", what], capture_output=True, text=True, timeout=timeout).stdout or "null")
    except (subprocess.TimeoutExpired, ValueError, OSError): return None

def board_json_args(args, timeout=20):
    b = board_bin()
    if not b: return None
    try: return json.loads(subprocess.run([b, *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL).stdout or "null")
    except (subprocess.TimeoutExpired, ValueError, OSError): return None

def board_run(args, timeout=120, env=None):
    """(ok, last useful line) of a board command, colours stripped."""
    b = board_bin()
    if not b: return False, "board isn't installed"
    try: r = subprocess.run([b, *args], capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired: return False, "That took too long. Is the device powered and on the same network or cable?"
    import re
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", l).strip(" ✓✗") for l in (r.stdout + "\n" + r.stderr).splitlines()]
    lines = [l for l in lines if l.strip()]
    return r.returncode == 0, (lines[-1] if lines else "")

STATE_TEXT = {"online": ("●", "success", ""), "offline": ("●", "dim-label", "offline"), "unknown": ("●", "dim-label", "checking…"),
              "auth": ("●", "warning", "refused your key: board copy-id"), "hostkey": ("●", "warning", "host key changed: board forget"),
              "serial": ("◌", "dim-label", "serial only")}

def remote_rows(devs, stat, query=""):
    """[(name, dot, dot_class, title_line, detail_line, online)] online first, filtered by query (name, host, tags, model)."""
    q, out = query.lower().strip(), []
    for name, d in (devs or {}).items():
        hay = " ".join([name, d.get("host", ""), d.get("model", ""), d.get("kind", ""), " ".join(d.get("tags", []))]).lower()
        if q and q not in hay: continue
        st = (stat or {}).get(name) or {"state": "unknown"}
        dot, cls, why = STATE_TEXT.get(st.get("state"), STATE_TEXT["unknown"])
        what = d.get("model") or d.get("kind") or "device"
        if st.get("state") == "online":
            line = f"{what} · {st.get('via') or 'connected'}" + (f" · {st['ms']} ms" if st.get("ms") is not None else "")
            bits = []
            if st.get("temp_c"): bits.append(f"{st['temp_c']:.0f} °C")
            if st.get("load") is not None: bits.append(f"load {st['load']:.1f}")
            if st.get("disk_free_kb"): bits.append(f"{st['disk_free_kb'] / 1048576:.0f} GB free")
            if st.get("throttled") and st["throttled"] != ["ok"] and isinstance(st["throttled"], list): bits.append("⚠ " + ", ".join(st["throttled"])[:40])
            detail = " · ".join(bits)
        elif st.get("state") == "serial":
            line, detail = f"{what} · serial only", ("adapter plugged in" if st.get("serial_present") else "adapter not plugged in")
        else:
            line, detail = f"{what} · {d.get('host') or name + '.local'}", why
        out.append((name, dot, cls, line, detail, st.get("state") == "online"))
    return sorted(out, key=lambda r: (not r[5], r[0].lower()))

def suggest_device(h):
    """Prefill for the add form from a `board json net` host: (name, host, user)."""
    import re
    raw = (h.get("name") or "").split(".")[0]
    name = re.sub(r"[^A-Za-z0-9_-]", "-", raw).strip("-") or f"dev-{h['ip'].split('.')[-1]}"
    if name in ("_gateway", "gateway"): name = "router"
    host = h["name"] if (h.get("name") or "").endswith(".local") else h["ip"]
    user = "pi" if "raspberry" in (h.get("vendor") or "").lower() else os.environ.get("USER", "")
    return name[:40], host, user

def terminal_cmd(title, *argv):
    import shutil
    if shutil.which("ptyxis"): return ["ptyxis", "--new-window", "-T", title, "--", *argv]
    if shutil.which("kitty"): return ["kitty", "--title", title, "--", *argv]
    return ["x-terminal-emulator", "-e", *argv]

def make_ssh_key(passphrase):
    """Create ~/.ssh/id_ed25519 by answering ssh-keygen's prompts on a pty (the passphrase never touches argv)."""
    import pty, socket
    k = HOME / ".ssh/id_ed25519"
    if k.exists(): return True, "You already have a key."
    (HOME / ".ssh").mkdir(mode=0o700, exist_ok=True)
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("ssh-keygen", ["ssh-keygen", "-q", "-t", "ed25519", "-a", "64", "-f", str(k),
                                 "-C", f"{os.environ.get('USER', 'me')}@{socket.gethostname()}"])
    try:
        while True:
            try: data = os.read(fd, 1024)
            except OSError: break
            if not data: break
            if b"passphrase" in data.lower(): os.write(fd, passphrase.encode() + b"\n")
    finally:
        _, st = os.waitpid(pid, 0); os.close(fd)
    ok = os.waitstatus_to_exitcode(st) == 0 and k.exists()
    return ok, "Key created." if ok else "ssh-keygen failed."

def askpass_env(password):
    """Env that makes ssh / ssh-copy-id read the device password from us once (never written to disk)."""
    helper = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "myos-askpass"
    if not helper.exists():
        helper.write_text('#!/bin/sh\nprintf "%s\\n" "$MYOS_ASKPASS"\n'); helper.chmod(0o700)
    return dict(os.environ, SSH_ASKPASS=str(helper), SSH_ASKPASS_REQUIRE="force", MYOS_ASKPASS=password,
                DISPLAY=os.environ.get("DISPLAY", ":0"))

class RemotePage(Gtk.Box):
    """Your SSH devices (from `board`) with guided setup: key, finding devices, cables, hotspot, adding. No terminal needed."""
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.devs, self.stat, self.links, self._timer, self._busy = win, {}, {}, {}, None, False
        self.back = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat", "circular"], tooltip_text="Back", visible=False)
        self.back.connect("clicked", lambda *_: self.step_back())
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Check again")
        self.refresh_btn.connect("clicked", lambda *_: self.reload())
        hb = Gtk.Box(spacing=8, margin_start=10, margin_end=14, margin_top=14, margin_bottom=6)
        hb.append(self.back)
        self.title = Gtk.Label(label="Remote", css_classes=["panel-title"], hexpand=True, xalign=0, margin_start=8)
        hb.append(self.title); hb.append(self.refresh_btn); self.append(hb)
        self.subtitle = Gtk.Label(xalign=0, css_classes=["dim-label"], margin_start=18, margin_bottom=6, wrap=True)
        self.append(self.subtitle)
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=160)
        self.append(self.stack)
        self._build_list(); self._build_nearby(); self._build_add(); self._build_setup(); self._build_detail(); self._build_edit()
        self.stack.add_named(status("dialog-information-symbolic", "board isn't installed", "Run: bash scripts/install-remote.sh"), "missing")
        self.foot = Gtk.Box(halign=Gtk.Align.CENTER, spacing=4, margin_bottom=8)
        b = Gtk.Button(label="Find or connect a device", css_classes=["flat"]); b.connect("clicked", lambda *_: self.go("nearby"))
        self.foot.append(b)
        self.append(self.foot)

    # ── views ──
    def _build_list(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search = Gtk.SearchEntry(placeholder_text="Search devices…", margin_start=12, margin_end=12, margin_bottom=8)
        self.search.connect("search-changed", lambda *_: self.render())
        self.search.connect("activate", lambda *_: self._first("ssh"))
        box.append(self.search)
        self.list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", lambda _l, row: self.open_detail(row.name))
        keys = Gtk.EventControllerKey(); keys.connect("key-pressed", self._key); self.list.add_controller(keys)
        box.append(scroller(self.list))
        self.stack.add_named(box, "list")
        empty = status("network-server-symbolic", "No devices yet", "Find a Pi, board or server on your network or a cable, and add it in a few clicks.")
        b = Gtk.Button(label="Find devices", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self.go("nearby")); empty.set_child(b)
        self.stack.add_named(empty, "empty")

    def _build_nearby(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.links_group = Adw.PreferencesGroup(title="Connect a device", description="No router? Use a cable or the laptop's hotspot.")
        self.eth_row = Adw.ExpanderRow(title="Ethernet cable", subtitle="Pi 3/4/5, Jetson, any board with a network port")
        self.eth_sw = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Share this laptop's network on the Ethernet port")
        self.eth_sw.connect("notify::active", lambda sw, _p: self._toggle("link", sw))
        self.eth_row.add_suffix(self.eth_sw)
        self.eth_row.add_row(self._steps("1. Plug the cable into the laptop and the device.\n2. Turn this on: the device gets a 10.42.0.x "
                                         "address and your internet.\n3. Power the device. In about 30 s it shows up below."))
        self.hot_row = Adw.ExpanderRow(title="Laptop hotspot", subtitle="Several devices, no cables")
        self.hot_sw = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Start a Wi-Fi hotspot for devices")
        self.hot_sw.connect("notify::active", lambda sw, _p: self._toggle("hotspot", sw))
        self.hot_row.add_suffix(self.hot_sw)
        self.hot_steps = self._steps("")
        self.hot_row.add_row(self.hot_steps)
        self.usb_row = Adw.ExpanderRow(title="USB cable", subtitle="Pi Zero 2 W, Pi 4, Pi 5 (the USB-C power port)")
        self.usb_row.add_row(self._steps("One time per Pi, while it's on Wi-Fi: add it here, then run `board usb enable NAME` "
                                         "(or flash the card with `board flash`, which turns it on).\nAfter that, one USB cable "
                                         "powers the Pi and connects it. It appears here as \"via USB cable\"."))
        for r in (self.eth_row, self.hot_row, self.usb_row): self.links_group.add(r)
        box.append(self.links_group)
        self.found_group = Adw.PreferencesGroup(title="On your network")
        self.scan_btn = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Scan again", valign=Gtk.Align.CENTER)
        self.scan_btn.connect("clicked", lambda *_: self.scan())
        self.found_group.set_header_suffix(self.scan_btn)
        self.found_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        self.found_group.add(self.found_list)
        box.append(self.found_group)
        manual = Gtk.Button(label="Add by name or IP…", css_classes=["flat"], halign=Gtk.Align.CENTER)
        manual.connect("clicked", lambda *_: self.open_add({"ip": "", "name": ""}))
        box.append(manual)
        self.stack.add_named(scroller(box), "nearby")

    def _steps(self, text):
        return Gtk.Label(label=text, wrap=True, xalign=0, css_classes=["caption"], margin_start=14, margin_end=14, margin_top=8, margin_bottom=10, selectable=True)

    def _build_add(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        g = Adw.PreferencesGroup(description="Your SSH key is copied to the device once. The password is only used for that and isn't saved.")
        self.f_name, self.f_host, self.f_user = Adw.EntryRow(title="Name"), Adw.EntryRow(title="Address (name.local or IP)"), Adw.EntryRow(title="User on the device")
        self.f_pw = Adw.PasswordEntryRow(title="Device password")
        for r in (self.f_name, self.f_host, self.f_user, self.f_pw): g.add(r)
        self.f_pw.connect("entry-activated", lambda *_: self.do_add())
        box.append(g)
        self.add_status = Gtk.Label(wrap=True, xalign=0, css_classes=["caption"], margin_start=6, margin_end=6)
        self.add_spin = Gtk.Spinner(visible=False)
        self.add_btn = Gtk.Button(label="Add device", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        self.add_btn.connect("clicked", lambda *_: self.do_add())
        row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER); row.append(self.add_spin); row.append(self.add_btn)
        box.append(row); box.append(self.add_status)
        self.stack.add_named(scroller(box), "add")

    def _build_setup(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        g = Adw.PreferencesGroup(title="First, your SSH key",
                                 description="One key lets you into every device without passwords. Pick a passphrase; you type it "
                                             "once per login and the keyring remembers it. Leave it empty for no passphrase.")
        self.k1, self.k2 = Adw.PasswordEntryRow(title="Passphrase"), Adw.PasswordEntryRow(title="Repeat passphrase")
        g.add(self.k1); g.add(self.k2); self.k2.connect("entry-activated", lambda *_: self.do_key())
        box.append(g)
        self.key_btn = Gtk.Button(label="Create key", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        self.key_btn.connect("clicked", lambda *_: self.do_key()); box.append(self.key_btn)
        self.key_status = Gtk.Label(wrap=True, xalign=0, css_classes=["caption"], margin_start=6)
        box.append(self.key_status)
        self.tools_group = Adw.PreferencesGroup(title="Optional tools")
        self.tools_label = self._steps(""); self.tools_group.add(self.tools_label)
        copy = Gtk.Button(label="Copy the install command", css_classes=["flat"], halign=Gtk.Align.START)
        copy.connect("clicked", lambda *_: (Gdk.Display.get_default().get_clipboard().set("bash ~/KadaOS/scripts/phase12-embedded.sh"),
                                            self.win.toast("Copied. Paste it in a terminal (it asks for your password).")))
        self.tools_group.add(copy)
        box.append(self.tools_group)
        self.stack.add_named(scroller(box), "setup")

    # ── navigation ──
    TITLES = {"list": ("Remote", None), "empty": ("Remote", None), "nearby": ("Find devices", None), "add": ("Add a device", None),
              "setup": ("Set up", None), "missing": ("Remote", None), "detail": ("Device", None), "edit": ("Edit device", None)}

    def go(self, view):
        if view == "list" and not self.devs: view = "empty"
        if view in ("nearby", "add") and not self.links.get("key", True): view = "setup"
        self.stack.set_visible_child_name(view)
        self.title.set_label(self.TITLES[view][0])
        self.back.set_visible(view not in ("list", "empty", "missing"))
        self.foot.set_visible(view in ("list", "empty"))
        if view == "nearby": self.scan(); self._load_links()
        if view == "setup": self._fill_setup()
        if view == "list": self.search.grab_focus()
        if view in ("list", "empty"): self._subtitle()
        self.subtitle.set_visible(view in ("list", "empty"))

    def _subtitle(self):
        on = sum((self.stat.get(n) or {}).get("state") == "online" for n in self.devs)
        self.subtitle.set_text(f"{len(self.devs)} devices · {on} online" if self.devs else "SSH devices, boards and servers")

    # ── data ──
    def on_show(self):
        self.search.set_text("")
        if not board_bin(): self.stack.set_visible_child_name("missing"); self.subtitle.set_text(""); return
        self.devs = board_json("devices", 5) or {}
        self.go("list"); self.render(); self.reload()
        v = os.environ.get("MYOS_REMOTE_VIEW", "")                                        # off-screen audit opens one view
        if v.startswith("detail") or v.startswith("edit"):
            GLib.timeout_add(1200, lambda: (self.open_detail("pi5") if v == "detail" else self.open_edit("pi5"), False)[1])
        elif v: self.go(v)
        if not self._timer: self._timer = GLib.timeout_add_seconds(10, self._tick)

    def _tick(self):
        if not self.win.is_visible() or self.win.page != "remote": self._timer = None; return False
        if self.stack.get_visible_child_name() == "list": self.reload()
        return True

    def reload(self):
        if self.stack.get_visible_child_name() == "nearby": self.scan(); self._load_links(); return
        self._load_links()
        if self.devs and not self._busy:
            self._busy = True
            threading.Thread(target=lambda: GLib.idle_add(self._set_stat, board_json("status", 25)), daemon=True).start()

    def _set_stat(self, st):
        self._busy = False
        if isinstance(st, dict): self.stat = st
        self.render(); return False

    def _load_links(self):
        threading.Thread(target=lambda: GLib.idle_add(self._set_links, board_json("links", 15)), daemon=True).start()

    def _set_links(self, lk):
        if not isinstance(lk, dict): return False
        self.links = lk
        self._quiet = True
        e, h, u = lk["eth"], lk["hotspot"], lk["usb"]
        self.eth_sw.set_active(e["on"])
        self.eth_row.set_subtitle(("On · " if e["on"] else "") + (f"cable plugged into {e['iface']}" if e["cable"] else
                                  (f"no cable in {e['iface']}" if e["iface"] else "no Ethernet port (a USB adapter works)")))
        self.hot_sw.set_active(h["on"])
        self.hot_row.set_subtitle(f"On · {h['ssid']}" if h["on"] else "Several devices, no cables (your Wi-Fi drops while on)")
        self.hot_steps.set_label(f"Network: {h['ssid']}\nPassword: {h['password'] or 'made when you first turn it on'}\n"
                                 "Boards flashed with `board flash` join it by themselves. Others: connect them to this network once.")
        self.usb_row.set_subtitle(f"Pi connected on {', '.join(u['connected'])}" if u["connected"] else
                                  ("Ready: plug in a prepared Pi" if u["ready"] else "Pi Zero 2 W, Pi 4, Pi 5 (USB-C power port)"))
        self._quiet = False
        if self.stack.get_visible_child_name() == "setup": self._fill_setup()
        return False

    def _toggle(self, what, sw):
        if getattr(self, "_quiet", False) or not self.links: return
        on = sw.get_active()
        args = [what, "on" if on else "off"] + (["-y"] if what == "hotspot" and on else [])
        sw.set_sensitive(False)
        def work():
            ok, msg = board_run(args, timeout=45)
            GLib.idle_add(done, ok, msg)
        def done(ok, msg):
            sw.set_sensitive(True); self.win.toast(msg if msg else ("Done" if ok else "That didn't work"))
            self._load_links()
            if ok and on: GLib.timeout_add_seconds(3, lambda: (self.scan(), False)[1])
            return False
        threading.Thread(target=work, daemon=True).start()

    # ── list ──
    def render(self):
        sel = self.list.get_selected_row(); keep = getattr(sel, "name", None)
        child = self.list.get_first_child()
        while child: self.list.remove(child); child = self.list.get_first_child()
        for name, dot, cls, line, detail, online in remote_rows(self.devs, self.stat, self.search.get_text()):
            self.list.append(self._row(name, dot, cls, line, detail, (self.stat.get(name) or {}).get("state")))
            if name == keep: self.list.select_row(self.list.get_last_child())
        if self.stack.get_visible_child_name() in ("list", "empty"):
            self.stack.set_visible_child_name("list" if self.devs else "empty"); self._subtitle()

    def _row(self, name, dot, cls, line, detail, state=None):
        row = Gtk.ListBoxRow(); row.name = name
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=10, margin_bottom=10, margin_start=12, margin_end=10)
        top = Gtk.Box(spacing=8)
        top.append(Gtk.Label(label=dot, css_classes=[cls]))
        top.append(Gtk.Label(label=name, css_classes=["heading"], xalign=0))
        top.append(Gtk.Label(label=line, css_classes=["dim-label", "caption"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
        box.append(top)
        if detail: box.append(Gtk.Label(label=detail, css_classes=["caption"] + (["warning"] if cls == "warning" else []),
                                        xalign=0, margin_start=20, ellipsize=Pango.EllipsizeMode.END))
        acts = Gtk.Box(spacing=4, margin_start=16)
        for icon, tip, act in (("utilities-terminal-symbolic", "Terminal (Enter)", "ssh"), ("text-editor-symbolic", "VS Code (C)", "code"),
                               ("folder-symbolic", "Files (F)", "files"), ("network-wired-symbolic", "Serial console (S)", "serial")):
            if state == "serial" and act != "serial": continue        # a bare board: only its console makes sense
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["flat", "circular"])
            b.update_property([Gtk.AccessibleProperty.LABEL], [f"{tip.split(' (')[0]}: {name}"])
            b.connect("clicked", lambda _b, a=act: self.act(name, a)); acts.append(b)
        box.append(acts); row.set_child(box)
        return row

    # ── nearby ──
    def scan(self):
        if getattr(self, "_scanning", False): return
        self._scanning = True
        self.found_group.set_description("Looking for devices… (about 5 s)")
        self.scan_btn.set_sensitive(False)
        threading.Thread(target=lambda: GLib.idle_add(self._set_found, board_json("net", 60)), daemon=True).start()

    def _set_found(self, hosts):
        self._scanning = False; self.scan_btn.set_sensitive(True)
        child = self.found_list.get_first_child()
        while child: self.found_list.remove(child); child = self.found_list.get_first_child()
        hosts = [h for h in (hosts or []) if h.get("role") != "this laptop"]
        hosts.sort(key=lambda h: (22 not in h.get("ports", []), bool(h.get("role")), h["ip"]))
        ssh = sum(22 in h.get("ports", []) for h in hosts)
        if not hosts:
            self.found_group.set_description("Nothing found yet. Plug in a cable or turn on the hotspot above, then scan again.")
        elif all(h.get("role") for h in hosts):
            self.found_group.set_description("Only the router answered. Office and guest Wi-Fi hide devices from each other: "
                                             "use the Ethernet cable or hotspot above.")
        else:
            self.found_group.set_description(f"{len(hosts)} devices · {ssh} accept SSH")
        for h in hosts:
            v = h.get("vendor") or ""
            title = ("Router" if h.get("role") == "router" else
                     h.get("name") or ("Phone or laptop (private address)" if v.startswith("random") else v) or "Unknown device")
            sub = " · ".join(x for x in (h["ip"], "" if v.startswith("random") or title == v else v,
                                         h.get("name") if h.get("role") == "router" and h.get("name", "").strip("_") != "gateway" else "") if x)
            row = Adw.ActionRow(title=GLib.markup_escape_text(title[:40]), subtitle=GLib.markup_escape_text(sub[:60]))
            if h.get("known"):
                row.add_suffix(Gtk.Label(label=f"✓ {h['known']}", css_classes=["success", "caption"]))
            elif 22 in h.get("ports", []):
                b = Gtk.Button(label="Add", css_classes=["suggested-action"], valign=Gtk.Align.CENTER)
                b.connect("clicked", lambda _b, hh=h: self.open_add(hh)); row.add_suffix(b)
            else:
                row.add_suffix(Gtk.Label(label="no SSH", css_classes=["dim-label", "caption"]))
            self.found_list.append(row)
        return False

    # ── add ──
    def open_add(self, h):
        self.add_mode = "add"
        for r in (self.f_name, self.f_host, self.f_user): r.set_editable(True)
        self.add_btn.set_label("Add device")
        name, host, user = suggest_device(h) if h.get("ip") else ("", "", "pi")
        self.f_name.set_text(name); self.f_host.set_text(host); self.f_user.set_text(user); self.f_pw.set_text("")
        self.add_status.set_text(""); self.add_btn.set_sensitive(True)
        self.go("add"); (self.f_pw if name else self.f_name).grab_focus()

    def do_add(self):
        name, host, user, pw = (self.f_name.get_text().strip(), self.f_host.get_text().strip(),
                                self.f_user.get_text().strip(), self.f_pw.get_text())
        if not name or not host: self.add_status.set_text("Give it a name and an address."); return
        self.add_btn.set_sensitive(False); self.add_spin.set_visible(True); self.add_spin.start()
        self.add_status.set_text(f"Connecting to {host}…")
        key_mode = getattr(self, "add_mode", "add") == "key"
        def work():
            args = ["copy-id", name] if key_mode else ["add", name, host, "-u", user, "--update", "-y"]
            ok, msg = board_run(args, timeout=90, env=askpass_env(pw))
            GLib.idle_add(done, ok, msg)
        def done(ok, msg):
            self.add_spin.stop(); self.add_spin.set_visible(False); self.add_btn.set_sensitive(True); self.f_pw.set_text("")
            if ok and key_mode:
                self.win.toast(f"Key sent. {name} won't ask for a password again.")
                self.stat.pop(name, None); self.reload(); self.open_detail(name)
            elif ok:
                self.win.toast(f"{name} added.")
                self.devs = board_json("devices", 5) or {}; self.render(); self.reload(); self.open_detail(name)
            else:
                hint = " Check the password and user." if "refused" in msg.lower() or "denied" in msg.lower() else ""
                self.add_status.set_text((msg or "Couldn't add it.") + hint)
            return False
        threading.Thread(target=work, daemon=True).start()

    # ── setup ──
    def _fill_setup(self):
        lk = self.links or {}
        miss = lk.get("missing", [])
        lines = []
        if miss: lines.append("Not installed yet: " + ", ".join(miss) + ". Needed for serial consoles, mounting and GUI apps.")
        if lk and not lk.get("dialout"): lines.append("Serial ports need the dialout group (the same command adds it; log out once after).")
        self.tools_label.set_label("\n".join(lines) or "Everything is installed.")
        self.tools_group.set_visible(bool(lines))
        self.key_status.set_text("")

    def do_key(self):
        a, b = self.k1.get_text(), self.k2.get_text()
        if a != b: self.key_status.set_text("The two passphrases don't match."); return
        self.key_btn.set_sensitive(False); self.key_status.set_text("Creating your key…")
        def work():
            ok, msg = make_ssh_key(a)
            if ok: board_run(["gen"], timeout=30)
            GLib.idle_add(done, ok, msg)
        def done(ok, msg):
            self.key_btn.set_sensitive(True); self.k1.set_text(""); self.k2.set_text("")
            if ok: self.links["key"] = True; self.win.toast("SSH key ready."); self.go("nearby")
            else: self.key_status.set_text(msg)
            return False
        threading.Thread(target=work, daemon=True).start()


    # ── device page ──
    def step_back(self):
        v = self.stack.get_visible_child_name()
        if v == "edit": self.open_detail(self.cur)
        elif v == "add" and getattr(self, "add_mode", "add") == "key": self.open_detail(self.cur)
        elif v == "add": self.go("nearby")
        else: self.go("list")

    def _build_detail(self):
        self.detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.stack.add_named(scroller(self.detail_box), "detail")

    def _group(self, title, desc=None):
        g = Adw.PreferencesGroup(title=title, description=desc); self.detail_box.append(g); return g

    def _info(self, g, title, value, icon=None, cls=None):
        r = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(str(value)), subtitle_selectable=True)
        r.add_css_class("property")
        if icon: r.add_prefix(Gtk.Image(icon_name=icon))
        if cls: r.add_css_class(cls)
        g.add(r); return r

    def _action(self, g, title, sub, icon, fn, suffix=None, destructive=False):
        r = Adw.ActionRow(title=title, subtitle=sub, activatable=True)
        r.add_prefix(Gtk.Image(icon_name=icon))
        r.add_suffix(suffix or Gtk.Image(icon_name="go-next-symbolic", css_classes=["dim-label"]))
        if destructive: r.add_css_class("error")
        r.connect("activated", lambda *_: fn()); g.add(r); return r

    def open_detail(self, name):
        if name not in self.devs: self.go("list"); return
        self.cur = name
        d, st = self.devs[name], self.stat.get(name) or {"state": "unknown"}
        child = self.detail_box.get_first_child()
        while child: self.detail_box.remove(child); child = self.detail_box.get_first_child()
        state = st.get("state")
        # what's wrong, in one sentence, with the fix
        fix = {"auth": (f"{name} refused your key (new device or password reset).", "Send key", lambda: self.open_key(name)),
               "hostkey": (f"{name} has a new host key. Expected after reflashing.", "Check and trust", lambda: self.trust(name)),
               "offline": (f"{name} isn't answering. Is it powered and on this network or a cable?", "Find it", lambda: self.go("nearby"))}.get(state)
        if fix:
            ban = Adw.Banner(title=fix[0], button_label=fix[1], revealed=True)
            ban.connect("button-clicked", lambda *_: fix[2]()); self.detail_box.append(ban)
        dot, cls, _ = STATE_TEXT.get(state, STATE_TEXT["unknown"])
        head = Gtk.Box(spacing=10, margin_start=6)
        head.append(Gtk.Label(label=dot, css_classes=[cls, "title-3"]))
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tb.append(Gtk.Label(label=d.get("model") or (d.get("kind") or "device").capitalize(), css_classes=["heading"], xalign=0,
                            ellipsize=Pango.EllipsizeMode.END))
        tb.append(Gtk.Label(label={"online": "Online", "offline": "Offline", "auth": "Needs your key", "hostkey": "New host key",
                                   "serial": "Serial only"}.get(state, "Checking…"), css_classes=["dim-label", "caption"], xalign=0))
        head.append(tb); self.detail_box.append(head)
        self.title.set_label(name)
        serial_only = state == "serial"
        online = state == "online"
        # facts
        g = self._group("Status")
        if online:
            self._info(g, "Connected", f"via {st.get('via') or '?'} · {st.get('ms', '?')} ms", "network-transmit-receive-symbolic")
            health = [f"{st['temp_c']:.0f} °C" if st.get("temp_c") else "", f"load {st['load']:.1f}" if st.get("load") is not None else "",
                      f"up {int(st['uptime_s'] // 3600)} h" if st.get("uptime_s") else ""]
            self._info(g, "Health", " · ".join(h for h in health if h) or "?", "power-profile-performance-symbolic")
            thr = st.get("throttled")
            if isinstance(thr, list) and thr and thr != ["ok"]:
                self._info(g, "Power", ", ".join(thr).capitalize() + ". Use a better power supply or cable.", "battery-caution-symbolic", "warning")
            if st.get("mem_total_kb"):
                self._info(g, "Memory", f"{(st.get('mem_avail_kb') or 0) / 1048576:.1f} GB free of {st['mem_total_kb'] / 1048576:.1f} GB", "drive-multidisk-symbolic")
            if st.get("disk_total_kb"):
                self._info(g, "Storage", f"{st['disk_free_kb'] / 1048576:.0f} GB free of {st['disk_total_kb'] / 1048576:.0f} GB", "drive-harddisk-symbolic")
            if st.get("os"): self._info(g, "System", f"{st['os']} · {st.get('arch', '')}", "computer-symbolic")
        elif not serial_only:
            self._info(g, "Status", {"offline": "Not answering", "auth": "Refused your key", "hostkey": "Host key changed"}.get(state, "Checking…"), "dialog-information-symbolic")
        if not serial_only: self._info(g, "Address", f"{d.get('user', '?')}@{d.get('host') or name + '.local'}" + (f":{d['port']}" if d.get("port") else ""), "network-server-symbolic")
        if d.get("project"): self._info(g, "Project folder", d["project"], "folder-symbolic")
        if d.get("serial"): self._info(g, "Serial port", f"{d['serial'].split('/')[-1]} · {d.get('baud', 115200)} baud", "network-wired-symbolic")
        if d.get("notes"): self._info(g, "Notes", d["notes"], "accessories-text-editor-symbolic")
        # open
        g = self._group("Open")
        if not serial_only:
            self._action(g, "Terminal", "Inside tmux on the device: survives Wi-Fi drops", "utilities-terminal-symbolic", lambda: self.act(name, "ssh"))
            self._action(g, "VS Code", "Edit and run code on the device", "text-editor-symbolic", lambda: self.act(name, "code"))
            self._action(g, "Files", "Browse the device in Files", "folder-symbolic", lambda: self.act(name, "files"))
        self._action(g, "Serial console", "Boot messages and a login without the network", "network-wired-symbolic", lambda: self.act(name, "serial"))
        if not serial_only:
            self._action(g, "Logs", "Follow the system journal live", "text-x-generic-symbolic", lambda: self.in_term(name, ["logs", name]))
            self._action(g, "Processes", "What's running and using CPU / memory", "view-list-symbolic", lambda: self.in_term(name, ["top", name]))
            # files and ports
            g = self._group("Files and ports")
            mp = str(HOME / "Remote" / name)
            sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=os.path.ismount(mp))
            sw.connect("notify::active", lambda w, _p: self.quick(["mount" if w.get_active() else "umount", name],
                                                                 f"Mounted at ~/Remote/{name}" if w.get_active() else "Unmounted"))
            self._action(g, "Mount as a folder", f"~/Remote/{name}: use it from any app", "folder-remote-symbolic", lambda: sw.set_active(not sw.get_active()), sw)
            self._action(g, "Send a file…", f"Copies into {d.get('project') or 'the home folder'}", "document-send-symbolic", lambda: self.send_file(name))
            port = Adw.EntryRow(title="Open a device port here (e.g. 8080)", show_apply_button=True)
            port.add_prefix(Gtk.Image(icon_name="network-workgroup-symbolic"))
            port.connect("apply", lambda r: self.open_port(name, r))
            g.add(port)
            if d.get("local"):
                self._action(g, "Sync project", f"{d['local']} → device on every save", "view-refresh-symbolic",
                             lambda: self.in_term(name, ["sync", name]))
            # device
            g = self._group("Device")
            self._action(g, "Edit details", "Name, address, user, project folder, tags", "document-edit-symbolic", lambda: self.open_edit(name))
            self._action(g, "Set up common tools", "tmux, updates, key-only login (asks for sudo on the device)", "system-software-install-symbolic",
                         lambda: self.in_term(name, ["bootstrap", name]))
            self._action(g, "Reboot", "Restarts it and tells you when it's back", "system-reboot-symbolic",
                         lambda: self.confirm(f"Reboot {name}?", "Anything running on it stops.", "Reboot", lambda: self.in_term(name, ["reboot", name, "-y"])))
            self._action(g, "Power off", "Safe shutdown before you unplug it", "system-shutdown-symbolic",
                         lambda: self.confirm(f"Power off {name}?", "You'll need to unplug and replug it to start it again.", "Power off",
                                              lambda: self.in_term(name, ["poweroff", name, "-y"])))
            if d.get("mac"): self._action(g, "Wake up", "Wake-on-LAN", "media-playback-start-symbolic", lambda: self.quick(["wake", name], f"Sent wake-up to {name}"))
            self._action(g, "Back up the SD card", "A compressed image in ~/Embedded/backups", "media-floppy-symbolic", lambda: self.in_term(name, ["backup", name]))
        # fix and remove
        g = self._group("Fix or remove")
        if not serial_only:
            self._action(g, "Send my key again", "After reinstalling or resetting the device", "dialog-password-symbolic", lambda: self.open_key(name))
            self._action(g, "Trust a new host key", "After reflashing (shows the key first)", "security-high-symbolic", lambda: self.trust(name))
        self._action(g, "Remove", "From this laptop only. Nothing on the device changes.", "user-trash-symbolic",
                     lambda: self.confirm(f"Remove {name}?", "It's removed from your list, SSH config and Files sidebar. The device isn't touched.",
                                          "Remove", lambda: self.quick(["rm", name, "-y", "--forget"], f"{name} removed", self._after_rm)), destructive=True)
        self.stack.set_visible_child_name("detail"); self.back.set_visible(True); self.foot.set_visible(False); self.subtitle.set_visible(False)

    def _after_rm(self):
        self.devs = board_json("devices", 5) or {}; self.render(); self.go("list")

    # helpers for device actions
    def quick(self, args, ok_text, after=None):
        def work():
            ok, msg = board_run(args, timeout=60)
            GLib.idle_add(done, ok, msg)
        def done(ok, msg):
            self.win.toast(ok_text if ok else (msg or "That didn't work"))
            if ok and after: after()
            elif getattr(self, "cur", None) in self.devs and self.stack.get_visible_child_name() == "detail": self.open_detail(self.cur)
            return False
        threading.Thread(target=work, daemon=True).start()

    def in_term(self, name, args):
        b = board_bin()
        if not b: return
        self.win.hide_panel()
        cmd = " ".join([b] + [GLib.shell_quote(x) for x in args])
        subprocess.Popen(terminal_cmd(f"{name} · {args[0]}", "sh", "-c", f"{cmd}; echo; read -r -p 'Enter to close ' _"),
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def confirm(self, heading, body, label, fn):
        dlg = Adw.AlertDialog(heading=heading, body=body)
        dlg.add_response("cancel", "Cancel"); dlg.add_response("ok", label)
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel"); dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, r: r == "ok" and fn())
        dlg.present(self.win)

    def send_file(self, name):
        self.win.keep_open = True
        dlg = Gtk.FileDialog(title=f"Send to {name}")
        def done(d, res):
            self.win.keep_open = False
            try: f = d.open_finish(res)
            except GLib.Error: return
            if f and f.get_path(): self.quick(["push", name, f.get_path()], f"Sent {Path(f.get_path()).name} to {name}")
        dlg.open(self.win, None, done)

    def open_port(self, name, row):
        spec = row.get_text().strip()
        if not spec.replace(":", "").isdigit(): self.win.toast("Type a port number, like 8080 (or 8080:80)."); return
        row.set_text("")
        local = spec.split(":")[0]
        self.quick(["ports", name, spec], f"Open: http://localhost:{local} (stays open while the panel's connection does)")

    def trust(self, name):
        def work():
            info = board_json_args(["trust", name, "--check"], 20)
            GLib.idle_add(show, info)
        def show(info):
            fps = (info or {}).get("fingerprints") or []
            if not fps: self.win.toast(f"{name} didn't answer. Is it on?"); return False
            when = (info or {}).get("flashed_at")
            body = ("New key: " + "\n".join(fps) + "\n\n" + (f"Expected: you flashed it on {when}." if when else
                    "Expected if you reflashed or reinstalled it. If you didn't, someone may be intercepting the connection."))
            self.confirm(f"Trust {name}'s new key?", body, "Trust", lambda: self.quick(["trust", name, "-y"], f"{name}'s new key is trusted"))
            return False
        threading.Thread(target=work, daemon=True).start()

    def open_key(self, name):
        d = self.devs.get(name, {})
        self.add_mode = "key"; self.cur = name
        self.f_name.set_text(name); self.f_host.set_text(d.get("host", "")); self.f_user.set_text(d.get("user", "")); self.f_pw.set_text("")
        for r in (self.f_name, self.f_host, self.f_user): r.set_editable(False)
        self.add_btn.set_label("Send key"); self.add_status.set_text("")
        self.go("add"); self.title.set_label(f"Send key to {name}"); self.f_pw.grab_focus()

    # ── edit ──
    EDIT_FIELDS = (("name", "Name"), ("host", "Address (name.local or IP)"), ("user", "User"), ("port", "SSH port (empty = 22)"),
                   ("project", "Project folder on the device (e.g. ~/robot)"), ("local", "Project folder on this laptop"),
                   ("tags", "Tags, comma separated (lab, robot)"), ("notes", "Notes"))

    def _build_edit(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        g = Adw.PreferencesGroup()
        self.e = {}
        for k, t in self.EDIT_FIELDS:
            self.e[k] = Adw.EntryRow(title=t); g.add(self.e[k])
        box.append(g)
        self.edit_status = Gtk.Label(wrap=True, xalign=0, css_classes=["caption"], margin_start=6)
        save = Gtk.Button(label="Save", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        save.connect("clicked", lambda *_: self.save_edit())
        box.append(save); box.append(self.edit_status)
        self.stack.add_named(scroller(box), "edit")

    def open_edit(self, name):
        d = self.devs.get(name, {}); self.cur = name
        for k, _ in self.EDIT_FIELDS:
            v = name if k == "name" else d.get(k, "")
            self.e[k].set_text(", ".join(v) if isinstance(v, list) else str(v or ""))
        self.edit_status.set_text("")
        self.go("edit"); self.title.set_label(f"Edit {name}")

    def save_edit(self):
        old = self.cur
        new = self.e["name"].get_text().strip()
        pairs = [f"{k}={self.e[k].get_text().strip()}" for k, _ in self.EDIT_FIELDS if k != "name"]
        port = self.e["port"].get_text().strip()
        if port and not port.isdigit(): self.edit_status.set_text("The port must be a number."); return
        def work():
            if new and new != old:
                ok, msg = board_run(["mv", old, new], timeout=20)
                if not ok: GLib.idle_add(fail, msg); return
            ok, msg = board_run(["set", new or old, *pairs], timeout=20)
            if ok: board_run(["gen"], timeout=30)
            GLib.idle_add(done if ok else fail, msg)
        def fail(msg): self.edit_status.set_text(msg or "Couldn't save."); return False
        def done(_msg):
            self.win.toast("Saved"); self.devs = board_json("devices", 5) or {}
            if new != old and old in self.stat: self.stat[new] = self.stat.pop(old)
            self.render(); self.open_detail(new or old); return False
        threading.Thread(target=work, daemon=True).start()

    # ── actions ──
    def act(self, name, action):
        b = board_bin()
        if not b: return
        self.win.hide_panel()
        if action in ("ssh", "serial"):
            argv = terminal_cmd(name, "sh", "-c", f"{b} {action} {name} || {{ echo; read -r -p 'Enter to close ' _; }}")
        else:
            argv = [b, action, name]
        subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _first(self, action):
        row = self.list.get_selected_row() or self.list.get_row_at_index(0)
        if row: self.act(row.name, action)

    def _key(self, _c, keyval, _code, state):
        act = {Gdk.KEY_c: "code", Gdk.KEY_f: "files", Gdk.KEY_s: "serial"}.get(keyval)
        row = self.list.get_selected_row()
        if act and row and not state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            self.act(row.name, act); return True
        return False


# ───────────────────────── Phone (the `phone` tool: KDE Connect + USB cable + ntfy) ─────────────────────────
def phone_bin():
    import shutil
    return shutil.which("phone") or (str(HOME / ".local/bin/phone") if (HOME / ".local/bin/phone").exists() else None)

def phone_call(args, timeout=60):
    """(ok, last useful line) of a phone command, colours stripped."""
    b = phone_bin()
    if not b: return False, "The phone tool isn't installed."
    import re
    try: r = subprocess.run([b, *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired: return False, "That took too long."
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", l).strip(" ✓✗") for l in (r.stdout + "\n" + r.stderr).splitlines() if l.strip()]
    return r.returncode == 0, (lines[-1] if lines else "")

def phone_summary(st):
    """(title, subtitle, state) for the phone card: state = on | away | none | missing."""
    if not st: return "Phone", "The phone tool isn't installed.", "missing"
    ph = st.get("phone")
    if not st.get("kdeconnect"): return "Phone", "KDE Connect isn't installed yet.", "missing"
    if not ph: return "No phone paired", "Plug the phone in and set it up once.", "none"
    if ph.get("reachable"):
        bits = ["Connected over Wi-Fi"]
        if st.get("battery") is not None: bits.append(f"{st['battery']}%" + (" · charging" if st.get("charging") else ""))
        return ph["name"], " · ".join(bits), "on"
    when = time.strftime("%H:%M", time.localtime(st["seen"])) if st.get("seen") else "not yet today"
    return ph["name"], f"Not reachable · last seen {when}", "away"

PUSH_RULES = [("away", "When the laptop is locked"), ("always", "Always"), ("off", "Never")]
PUSH_DETAIL = [("short", "Short title"), ("private", "Just “new alert”"), ("full", "Title and details")]

class PhonePage(Gtk.Box):
    """Your phone in one place: status, send files / clipboard, find it, mirror it, alerts. Drop files to send them."""
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.st, self._timer, self._busy, self._quiet = win, None, None, False, False
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Reconnect")
        self.refresh_btn.update_property([Gtk.AccessibleProperty.LABEL], ["Reconnect"])
        self.refresh_btn.connect("clicked", lambda *_: self.reconnect())
        self.append(header("Phone", self.refresh_btn))
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE); self.append(self.stack)

        setup = status("phone-symbolic", "Set up your phone", "Plug it in with a USB cable. Setup takes about 5 minutes and you only tap on the phone.")
        b = Gtk.Button(label="Set up", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self.run_in_terminal("Phone setup", "setup")); setup.set_child(b)
        self.setup_page = setup; self.stack.add_named(setup, "setup")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card = Adw.PreferencesGroup()
        self.card = Adw.ActionRow(css_classes=["phone-card"])
        self.card_icon = Gtk.Image(icon_name="phone-symbolic", pixel_size=36, css_classes=["phone-icon"])
        self.card.add_prefix(self.card_icon); card.add(self.card)
        self.help = Adw.ActionRow(title="Open KDE Connect on the phone", subtitle_lines=4, visible=False)
        self.help.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic"))
        card.add(self.help); box.append(card)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        self.btn = {}
        for i, (key, icon, label, fn) in enumerate([
                ("send", "document-send-symbolic", "Send files", self.pick_files),
                ("clip", "edit-paste-symbolic", "Send clipboard", lambda *_: self.act(["clip"], "Clipboard sent")),
                ("find", "audio-volume-high-symbolic", "Find phone", lambda *_: self.act(["find"], "Ringing")),
                ("mirror", "video-display-symbolic", "Mirror screen", lambda *_: self.mirror())]):
            bt = Gtk.Button(css_classes=["phone-action"])
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=12, margin_bottom=10)
            inner.append(Gtk.Image(icon_name=icon, pixel_size=22)); inner.append(Gtk.Label(label=label))
            bt.set_child(inner); bt.update_property([Gtk.AccessibleProperty.LABEL], [label]); bt.connect("clicked", fn)
            grid.attach(bt, i % 2, i // 2, 1, 1); self.btn[key] = bt
        box.append(grid)
        self.drop_hint = Gtk.Label(label="Drop files here to send them to the phone", css_classes=["dim-label", "hint"])
        box.append(self.drop_hint)

        files = Adw.PreferencesGroup(title="From the phone", description="On the phone: Share → KDE Connect → this laptop.")
        r = Adw.ActionRow(title="Received files", subtitle="~/Downloads", activatable=True)
        r.add_suffix(Gtk.Image(icon_name="folder-open-symbolic")); r.connect("activated", lambda *_: self.open_path(HOME / "Downloads"))
        files.add(r)
        self.get_row = Adw.ActionRow(title="Copy the phone's latest download", subtitle="Over the USB cable", activatable=True, visible=False)
        self.get_row.add_suffix(Gtk.Image(icon_name="folder-download-symbolic"))
        self.get_row.connect("activated", lambda *_: self.act(["get", "1"], "Copied to ~/Downloads/Phone", timeout=600))
        files.add(self.get_row); box.append(files)

        alerts = Adw.PreferencesGroup(title="Alerts on the phone", description="Laptop problems, finished jobs and Pi alerts, through ntfy. Works anywhere.")
        self.rule = Adw.ComboRow(title="Send alerts", model=Gtk.StringList.new([l for _, l in PUSH_RULES]))
        self.rule.connect("notify::selected", lambda *_: self.set_opt("push", PUSH_RULES, self.rule))
        self.detail = Adw.ComboRow(title="What the alert says", subtitle="ntfy topics are public: keep it short",
                                   model=Gtk.StringList.new([l for _, l in PUSH_DETAIL]))
        self.detail.connect("notify::selected", lambda *_: self.set_opt("detail", PUSH_DETAIL, self.detail))
        test = Adw.ActionRow(title="Send a test alert", activatable=True)
        test.add_suffix(Gtk.Image(icon_name="mail-send-symbolic"))
        test.connect("activated", lambda *_: self.act(["push", "KadaOS: test alert from the laptop"], "Test alert sent"))
        for w in (self.rule, self.detail, test): alerts.add(w)
        self.alerts = alerts; box.append(alerts)
        self.stack.add_named(scroller(box), "main")
        self.append(footer_button("Something wrong? Check the link", terminal_cmd("Phone doctor", "sh", "-c", "phone doctor; echo; read -p 'Enter to close' x"), win))

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._dropped); self.add_controller(drop)

    # ── data ──
    def on_show(self):
        self.reload()
        if not self._timer: self._timer = GLib.timeout_add_seconds(8, self._tick)

    def _tick(self):
        if not self.win.is_visible() or self.win.page != "phone": self._timer = None; return False
        self.reload(); return True

    def reload(self):
        if self._busy: return
        self._busy = True
        def work():
            st = None
            b = phone_bin()
            if b:
                try: st = json.loads(subprocess.run([b, "status", "--json"], capture_output=True, text=True, timeout=25, stdin=subprocess.DEVNULL).stdout or "null")
                except (subprocess.TimeoutExpired, ValueError, OSError): st = None
            GLib.idle_add(self.render, st)
        threading.Thread(target=work, daemon=True).start()

    def render(self, st):
        self._busy = False; self.st = st
        title, sub, state = phone_summary(st)
        if state in ("missing", "none"):
            self.setup_page.set_title("Set up your phone" if state == "none" or st else "Phone")
            self.setup_page.set_description(sub + ("" if state == "none" else " Run: bash scripts/phase13-phone.sh"))
            self.stack.set_visible_child_name("setup"); return False
        self.card.set_title(GLib.markup_escape_text(title)); self.card.set_subtitle(sub)
        for c in ("on", "away"): self.card_icon.remove_css_class(c)
        self.card_icon.add_css_class(state)
        on, cable = state == "on", bool(st.get("cable"))
        self.help.set_visible(not on)
        if not on:
            self.help.set_subtitle("Same Wi-Fi as the laptop? Office and campus Wi-Fi often hide devices from each other: in KDE Connect "
                                   f"on the phone, ⋮ → Add devices by IP → {st.get('laptop_ip') or 'this laptop’s address'}. Or plug in the USB cable.")
        self.btn["send"].set_sensitive(on or cable); self.btn["clip"].set_sensitive(on); self.btn["find"].set_sensitive(on)
        self.btn["mirror"].set_sensitive(cable)
        self.btn["mirror"].set_tooltip_text("" if cable else "Needs the USB cable")
        self.get_row.set_visible(cable)
        a = st.get("alerts") or {}
        self.alerts.set_visible(bool(a.get("topic")))
        self._quiet = True
        self.rule.set_selected(next((i for i, (k, _) in enumerate(PUSH_RULES) if k == a.get("rule")), 0))
        self.detail.set_selected(next((i for i, (k, _) in enumerate(PUSH_DETAIL) if k == a.get("detail")), 0))
        self._quiet = False
        if a.get("topic"): self.alerts.set_description(f"Through ntfy, topic {a['topic']}. Works anywhere."
                                                       + (f" {a['queued']} waiting for internet." if a.get("queued") else ""))
        self.stack.set_visible_child_name("main")
        return False

    # ── actions ──
    def act(self, args, done_msg, timeout=120):
        def work():
            ok, line = phone_call(args, timeout)
            GLib.idle_add(lambda: (self.win.toast(done_msg if ok else (line or "That didn't work")), self.reload(), False)[2])
        threading.Thread(target=work, daemon=True).start()

    def reconnect(self):
        self.card.set_subtitle("Reconnecting…")
        self.act(["_tick"], "Checked the link")

    def set_opt(self, key, options, row):
        if self._quiet: return
        self.act(["set", key, options[row.get_selected()][0]], "Saved")

    def send_paths(self, paths):
        if not paths: return
        names = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} files"
        self.win.toast(f"Sending {names}…")
        self.act(["send", *paths], f"Sent {names} to the phone", timeout=900)

    def pick_files(self, *_):
        self.win.keep_open = True
        dlg = Gtk.FileDialog(title="Send to phone")
        def done(d, res):
            self.win.keep_open = False
            try: files = d.open_multiple_finish(res)
            except GLib.Error: return
            self.send_paths([f.get_path() for f in files if f.get_path()])
        dlg.open_multiple(self.win, None, done)

    def _dropped(self, _t, value, _x, _y):
        self.send_paths([f.get_path() for f in value.get_files() if f.get_path()]); return True

    def mirror(self):
        self.win.hide_panel()
        b = phone_bin()
        if b: subprocess.Popen([b, "mirror"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_path(self, path):
        self.win.hide_panel(); subprocess.Popen(["xdg-open", str(path)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_in_terminal(self, title, *args):
        self.win.hide_panel()
        subprocess.Popen(terminal_cmd(title, "sh", "-c", "phone " + " ".join(args) + "; echo; read -p 'Enter to close' x"),
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ───────────────────────── Storage (the `disk` tool) ─────────────────────────
def disk_bin():
    import shutil
    return shutil.which("disk") or (str(HOME / ".local/bin/disk") if (HOME / ".local/bin/disk").exists() else None)

def disk_json(args, timeout=180):
    b = disk_bin()
    if not b: return None
    try: return json.loads(subprocess.run([b, *args, "--json"], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL).stdout or "null")
    except (subprocess.TimeoutExpired, ValueError, OSError): return None

def human_bytes(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or u == "TB": return f"{n:.0f} {u}" if u in ("B", "KB", "MB") else f"{n:.1f} {u}"
        n /= 1000

class StoragePage(Gtk.Box):
    """Disk space at a glance and freeing it safely: caches and build leftovers in one click, your files only to the Trash."""
    SKIP_IN_ALL = ("trash", "chrome-cache")       # "Free up" never empties the Trash or needs Chrome closed

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.data, self._busy = win, None, False
        rb = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Check again")
        rb.connect("clicked", lambda *_: self.reload()); self.append(header("Storage", rb))
        self.stack = Gtk.Stack(vexpand=True); self.append(self.stack)
        self.stack.add_named(status("drive-harddisk-symbolic", "Checking the disk…", ""), "loading")
        self.stack.add_named(status("dialog-information-symbolic", "The disk tool isn't installed", "Run: bash scripts/install-panels.sh"), "missing")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=4, margin_end=4)
        self.free_lbl = Gtk.Label(xalign=0, css_classes=["storage-free"]); top.append(self.free_lbl)
        self.bar = Gtk.ProgressBar(css_classes=["disk-bar"]); top.append(self.bar)      # colour = how full it is (CSS)
        self.free_btn = Gtk.Button(css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER, margin_top=6)
        self.free_btn.connect("clicked", lambda *_: self.free_all()); top.append(self.free_btn)
        box.append(top)
        self.safe = Adw.PreferencesGroup(title="Safe to free", description="Caches and leftovers that come back by themselves when needed.")
        self.root = Adw.PreferencesGroup(title="Needs your password", description="Run these in a terminal.")
        self.files = Adw.PreferencesGroup(title="Your files", description="Only ever moved to the Trash.")
        self.big_row = Adw.ActionRow(title="Big files in Downloads", subtitle="200 MB or more", activatable=True)
        self.big_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic")); self.big_row.connect("activated", lambda *_: self.load_big())
        self.dup_row = Adw.ActionRow(title="Find duplicate files", subtitle="Downloads, Documents, Pictures, Desktop, Videos", activatable=True)
        self.dup_row.add_suffix(Gtk.Image(icon_name="edit-find-symbolic")); self.dup_row.connect("activated", lambda *_: self.load_dupes())
        self.files.add(self.big_row); self.files.add(self.dup_row)
        self.found = Adw.PreferencesGroup(visible=False)
        for g in (self.safe, self.root, self.files, self.found): box.append(g)
        self.stack.add_named(scroller(box), "main")
        self._rows = []

    def on_show(self):
        if not disk_bin(): self.stack.set_visible_child_name("missing"); return
        if self.data is None: self.stack.set_visible_child_name("loading")
        self.reload()

    def reload(self):
        if self._busy: return
        self._busy = True
        threading.Thread(target=lambda: GLib.idle_add(self.render, disk_json([])), daemon=True).start()

    def render(self, data):
        self._busy = False
        if not data: self.stack.set_visible_child_name("missing"); return False
        self.data = data; d = data["disk"]
        self.free_lbl.set_markup(f"<b>{human_bytes(d['free'])} free</b>  <span alpha='60%'>of {human_bytes(d['total'])}</span>")
        self.bar.set_fraction(d["used_pct"] / 100)
        for c in ("ok", "warn", "crit"): self.bar.remove_css_class(c)
        self.bar.add_css_class("crit" if d["used_pct"] >= 90 else "warn" if d["used_pct"] >= 80 else "ok")
        total = sum(i["size"] for i in data["items"] if not i["root"] and i["id"] not in self.SKIP_IN_ALL)
        self.free_btn.set_label(f"Free up {human_bytes(total)}"); self.free_btn.set_visible(total > 50e6)
        for g, r in self._rows: g.remove(r)
        self._rows = []
        for i in data["items"]:
            row = Adw.ActionRow(title=GLib.markup_escape_text(i["title"]), subtitle=GLib.markup_escape_text(i.get("why") or ""), subtitle_lines=2)
            if i["size"]: row.add_suffix(Gtk.Label(label=human_bytes(i["size"]), css_classes=["dim-label", "numeric"]))
            if i["root"]:
                b = Gtk.Button(icon_name="edit-copy-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Copy the command")
                b.connect("clicked", lambda _b, c=i["cmd"]: (self.get_clipboard().set(c), self.win.toast("Command copied: paste it in a terminal")))
                group = self.root
            else:
                b = Gtk.Button(label="Free", css_classes=["flat"], valign=Gtk.Align.CENTER)
                b.connect("clicked", lambda _b, it=i: self.ask([it]))
                group = self.safe
            row.add_suffix(b); group.add(row); self._rows.append((group, row))
        self.stack.set_visible_child_name("main"); return False

    def ask(self, its):
        size = sum(i["size"] for i in its)
        body = "\n".join(f"• {i['title']}" + (f" ({human_bytes(i['size'])})" if i["size"] else "") for i in its)
        dlg = Adw.AlertDialog(heading=f"Free {human_bytes(size)}?" if size else "Clean up?", body=body + "\n\nThese come back by themselves when needed.")
        dlg.add_response("cancel", "Cancel"); dlg.add_response("ok", "Free")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED); dlg.set_default_response("ok"); dlg.set_close_response("cancel")
        self.win.keep_open = True
        def done(_d, r):
            self.win.keep_open = False
            if r == "ok": self.clean([i["id"] for i in its])
        dlg.connect("response", done); dlg.present(self.win)

    def free_all(self):
        if self.data: self.ask([i for i in self.data["items"] if not i["root"] and i["id"] not in self.SKIP_IN_ALL])

    def clean(self, ids):
        self.free_btn.set_sensitive(False); self.free_btn.set_label("Freeing…")
        def work():
            res = disk_json(["clean", *ids], timeout=1800) or []
            GLib.idle_add(done, res)
        def done(res):
            self.free_btn.set_sensitive(True)
            failed = [m for _i, ok, m in res if not ok]
            self.win.toast(failed[0] if failed else "Done: space freed"); self.reload(); return False
        threading.Thread(target=work, daemon=True).start()

    def _show_found(self, title, rows):
        for r in getattr(self, "_found_rows", []): self.found.remove(r)
        self._found_rows = rows
        self.found.set_title(title); self.found.set_visible(True)
        for r in rows: self.found.add(r)

    def load_big(self):
        self.big_row.set_subtitle("Looking…")
        def work(): GLib.idle_add(show, disk_json(["big"]) or [])
        def show(fs):
            self.big_row.set_subtitle("200 MB or more")
            rows = []
            for f in fs[:20]:
                r = Adw.ActionRow(title=GLib.markup_escape_text(Path(f["path"]).name), subtitle=f"{human_bytes(f['size'])} · " + time.strftime("%d %b %Y", time.localtime(f["mtime"])))
                b = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Move to the Trash")
                b.connect("clicked", lambda _b, p=f["path"], row=r: self.to_trash([p], row)); r.add_suffix(b); rows.append(r)
            self._show_found("Big files in Downloads" if rows else "No big files in Downloads", rows); return False
        threading.Thread(target=work, daemon=True).start()

    def load_dupes(self):
        self.dup_row.set_subtitle("Comparing files… (can take a minute)")
        def work(): GLib.idle_add(show, disk_json(["dupes"], timeout=900) or [])
        def show(gs):
            self.dup_row.set_subtitle("Downloads, Documents, Pictures, Desktop, Videos")
            rows = []
            for g in gs[:20]:
                keep, extra = g["paths"][0], g["paths"][1:]
                r = Adw.ActionRow(title=GLib.markup_escape_text(Path(keep).name), subtitle_lines=3,
                                  subtitle=GLib.markup_escape_text(f"{human_bytes(g['size'])} × {len(g['paths'])} · keeps {keep.replace(str(HOME), '~')}"))
                b = Gtk.Button(label=f"Trash {len(extra)}", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Move the extra copies to the Trash")
                b.connect("clicked", lambda _b, ps=extra, row=r: self.to_trash(ps, row)); r.add_suffix(b); rows.append(r)
            self._show_found("Duplicates" if rows else "No duplicates found", rows); return False
        threading.Thread(target=work, daemon=True).start()

    def to_trash(self, paths, row):
        row.set_sensitive(False)
        def work():
            b = disk_bin()
            ok = bool(b) and subprocess.run([b, "trash", *paths], capture_output=True, timeout=300).returncode == 0
            GLib.idle_add(done, ok)
        def done(ok):
            row.set_sensitive(not ok); row.set_subtitle("Moved to the Trash" if ok else row.get_subtitle())
            self.win.toast("Moved to the Trash (restore it from Files → Trash)" if ok else "Couldn't move it to the Trash")
            if ok: self.reload()
            return False
        threading.Thread(target=work, daemon=True).start()


# ───────────────────────── Security checkup (the `security` tool, read-only) ─────────────────────────
def security_bin():
    import shutil
    return shutil.which("security-check") or (str(HOME / ".local/bin/security-check") if (HOME / ".local/bin/security-check").exists() else None)

SEC_ICON = {"ok": ("object-select-symbolic", "success"), "warn": ("dialog-warning-symbolic", "warning"),
            "bad": ("dialog-error-symbolic", "error"), "info": ("dialog-information-symbolic", "dim-label")}

def security_headline(summary):
    """(title, css class) for the top of the Security page."""
    b, w = summary.get("bad", 0), summary.get("warn", 0)
    if b: return f"{b} thing{'s' if b > 1 else ''} to fix soon", "error"
    if w: return f"{w} thing{'s' if w > 1 else ''} worth fixing", "warning"
    return "Looking good", "success"

class SecurityPage(Gtk.Box):
    """This laptop's security checkup in plain words, worst first. Read-only; fixes are buttons (safe ones) or copied commands."""
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self._busy, self._rows = win, False, []
        rb = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Check again")
        rb.connect("clicked", lambda *_: self.reload()); self.append(header("Security", rb))
        self.stack = Gtk.Stack(vexpand=True); self.append(self.stack)
        self.stack.add_named(status("security-high-symbolic", "Checking…", "Firewall, network, disk, updates, keys, logins"), "loading")
        self.stack.add_named(status("dialog-information-symbolic", "The checkup isn't installed", "Run: bash scripts/install-panels.sh"), "missing")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        top = Gtk.Box(spacing=12, margin_start=6)
        self.shield = Gtk.Image(icon_name="security-high-symbolic", pixel_size=40); top.append(self.shield)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.headline = Gtk.Label(xalign=0, css_classes=["sec-headline"]); self.counts = Gtk.Label(xalign=0, css_classes=["dim-label"])
        tb.append(self.headline); tb.append(self.counts); top.append(tb); box.append(top)
        self.todo = Adw.PreferencesGroup(title="To look at"); self.good = Adw.PreferencesGroup(title="Looking good")
        box.append(self.todo); box.append(self.good)
        self.stack.add_named(scroller(box), "main")
        self.loaded = False

    def on_show(self):
        if not security_bin(): self.stack.set_visible_child_name("missing"); return
        if not self.loaded: self.stack.set_visible_child_name("loading")
        self.reload()

    def reload(self):
        if self._busy: return
        self._busy = True
        def work():
            data = None
            try: data = json.loads(subprocess.run([security_bin(), "--json"], capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL).stdout or "null")
            except (subprocess.TimeoutExpired, ValueError, OSError, TypeError): pass
            GLib.idle_add(self.render, data)
        threading.Thread(target=work, daemon=True).start()

    def render(self, data):
        self._busy = False
        if not data: self.stack.set_visible_child_name("missing"); return False
        self.loaded = True
        title, cls = security_headline(data["summary"])
        self.headline.set_label(title)
        for c in ("success", "warning", "error"): self.shield.remove_css_class(c)
        self.shield.add_css_class(cls)
        self.shield.set_from_icon_name({"success": "security-high-symbolic", "warning": "security-medium-symbolic"}.get(cls, "security-low-symbolic"))
        s = data["summary"]; self.counts.set_label(f"{s['good']} good · {s['warn']} worth fixing · {s['bad']} fix soon")
        for g, r in self._rows: g.remove(r)
        self._rows = []
        for c in data["checks"]:
            icon, icls = SEC_ICON.get(c["state"], SEC_ICON["info"])
            if c["state"] in ("warn", "bad"):
                row = Adw.ExpanderRow(title=GLib.markup_escape_text(c["title"]), subtitle=GLib.markup_escape_text(c["detail"]), subtitle_lines=3)
                if c.get("why"):
                    why = Gtk.Label(label=c["why"], wrap=True, xalign=0, css_classes=["dim-label"], margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
                    row.add_row(why)
                fix = c.get("fix") or {}
                if fix.get("cmd"):
                    b = Gtk.Button(label=("Copy command: " if fix["root"] else "") + fix["label"], halign=Gtk.Align.START,
                                   css_classes=["pill"] + ([] if fix["root"] else ["suggested-action"]), margin_start=12, margin_bottom=10)
                    b.connect("clicked", lambda _b, f=fix: self.do_fix(f)); row.add_row(b)
                group = self.todo
            else:
                row = Adw.ActionRow(title=GLib.markup_escape_text(c["title"]), subtitle=GLib.markup_escape_text(c["detail"]), subtitle_lines=2)
                group = self.good
            img = Gtk.Image(icon_name=icon, css_classes=[icls]); row.add_prefix(img)
            group.add(row); self._rows.append((group, row))
        self.todo.set_visible(any(g is self.todo for g, _ in self._rows))
        self.stack.set_visible_child_name("main"); return False

    def do_fix(self, fix):
        if fix["root"]:
            self.get_clipboard().set(fix["cmd"]); self.win.toast("Copied: paste it in a terminal (it asks for your password)")
            return
        self.win.hide_panel()
        subprocess.Popen(terminal_cmd(fix["label"], "sh", "-c", fix["cmd"] + "; echo; read -p 'Enter to close' x"),
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ───────────────────────── Battery health (the `battery-health` tool) ─────────────────────────
def battery_bin():
    import shutil
    return shutil.which("battery-health") or (str(HOME / ".local/bin/battery-health") if (HOME / ".local/bin/battery-health").exists() else None)

def health_points(history, width, height, lo=75.0, hi=100.0):
    """(x, y) pixel points for the health chart: oldest left, 100 % at the top, `lo` % at the bottom."""
    if not history: return []
    n = len(history)
    return [((i / (n - 1) if n > 1 else 1.0) * width, (1 - (min(hi, max(lo, h["health"])) - lo) / (hi - lo)) * height)
            for i, h in enumerate(history)]

class BatteryPage(Gtk.Box):
    """How the battery is aging: health vs new, cycles, the trend over time, and what's happening right now."""
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.data = win, None
        self.append(header("Battery"))
        self.stack = Gtk.Stack(vexpand=True); self.append(self.stack)
        self.stack.add_named(status("battery-missing-symbolic", "No battery found", ""), "none")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=6)
        self.big = Gtk.Label(xalign=0, css_classes=["bat-big"]); self.verdict = Gtk.Label(xalign=0, css_classes=["dim-label"])
        top.append(self.big); top.append(self.verdict); box.append(top)
        self.chart = Gtk.DrawingArea(content_height=110, css_classes=["bat-chart"]); self.chart.set_draw_func(self._draw)
        box.append(self.chart)
        self.chart_note = Gtk.Label(xalign=0, css_classes=["dim-label", "hint"], margin_start=6); box.append(self.chart_note)
        self.facts = Adw.PreferencesGroup(); box.append(self.facts); self._rows = []
        tips = Adw.PreferencesGroup(title="Make it last")
        for t, sub in (("Don't keep it at 100 % all day", "If it's plugged in most of the time, look for HP's battery care / "
                        "Adaptive Battery Optimizer option in the BIOS (it limits the charge to about 80 %)."),
                       ("Heat ages it fastest", "Gaming or AI work on battery gets it hot; plug in for heavy work (profile: AI work)."),
                       ("Deep drains add wear", "Charging from 20–30 % is gentler than running it down to 0 %.")):
            tips.add(Adw.ActionRow(title=t, subtitle=sub, subtitle_lines=3))
        box.append(tips)
        self.stack.add_named(scroller(box), "main")

    def on_show(self):
        b = battery_bin()
        if not b: self.stack.set_visible_child_name("none"); return
        def work():
            try: d = json.loads(subprocess.run([b, "--json"], capture_output=True, text=True, timeout=10).stdout or "null")
            except (subprocess.TimeoutExpired, ValueError, OSError): d = None
            GLib.idle_add(self.render, d)
        threading.Thread(target=work, daemon=True).start()

    def render(self, d):
        if not d: self.stack.set_visible_child_name("none"); return False
        self.data = d
        self.big.set_markup(f"<b>{d['health']:.0f}%</b> <span size='small' alpha='60%'>health</span>")
        self.verdict.set_label(f"{d['verdict']} · holds {d['full_wh']:.1f} of {d['design_wh']:.1f} Wh it had when new")
        t = d.get("trend")
        self.chart_note.set_label("History builds up with one reading a day." if not t else
                                  f"Last {t['days']} days: " + (f"−{t['per_year']}% a year" if t["per_year"] else "no measurable loss")
                                  + (f" · about {d['years_to_worn']} years until 80 %" if d.get("years_to_worn") else ""))
        for r in self._rows: self.facts.remove(r)
        self._rows = []
        now = f"{d['percent']}% · {d['status'].lower()}" + (f" · {d['power_w']:.1f} W" if d.get("power_w") else "") \
              + (f" · about {d['hours_left']} h left" if d.get("hours_left") else "")
        for title, sub in (("Right now", now), ("Charge cycles", str(d["cycles"]) if d.get("cycles") is not None else "not reported"),
                           ("Battery", f"{d.get('maker') or ''} {d.get('tech') or ''} · {d['design_wh']:.0f} Wh".strip())):
            row = Adw.ActionRow(title=title, subtitle=sub); self.facts.add(row); self._rows.append(row)
        self.chart.queue_draw(); self.stack.set_visible_child_name("main"); return False

    def _draw(self, area, cr, w, h):
        rgba = area.get_color(); cr.set_line_width(1); cr.set_font_size(9)
        plot_w = w - 62                                             # room for the % labels on the right ("80% worn")
        for pct in (100, 90, 80):                                   # guide lines; 80 % = worn
            y = (1 - (pct - 75) / 25) * (h - 8) + 4
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.12); cr.move_to(0, y); cr.line_to(plot_w, y); cr.stroke()
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.55); cr.move_to(plot_w + 6, y + 3)
            cr.show_text(f"{pct}%" + (" worn" if pct == 80 else ""))
        pts = health_points((self.data or {}).get("history") or [], plot_w, h - 8)
        if not pts: return
        cr.set_source_rgba(0.42, 0.70, 1.0, 1); cr.set_line_width(2.5)
        cr.move_to(pts[0][0], pts[0][1] + 4)
        for x, y in pts[1:]: cr.line_to(x, y + 4)
        if len(pts) == 1: cr.arc(pts[0][0] - 4, pts[0][1] + 4, 3, 0, 6.3); cr.fill()
        else: cr.stroke()


# ───────────────────────── Projects (the `projects` tool: git + GitHub) ─────────────────────────
def projects_bin():
    import shutil
    return shutil.which("projects") or (str(HOME / ".local/bin/projects") if (HOME / ".local/bin/projects").exists() else None)

def projects_json(gh=False, timeout=60):
    b = projects_bin()
    if not b: return None
    try: return json.loads(subprocess.run([b, "--json"] + (["--gh"] if gh else []), capture_output=True, text=True,
                                          timeout=timeout, stdin=subprocess.DEVNULL).stdout or "null")
    except (subprocess.TimeoutExpired, ValueError, OSError): return None

def project_attention(i):
    """True when a repo has something to do: uncommitted work, commits to push/pull, failing CI or open PRs."""
    return bool(i.get("changed") or i.get("ahead") or i.get("behind") or i.get("ci") == "fail" or i.get("prs"))

class ProjectsPage(Gtk.Box):
    """Every repo at a glance: branch, uncommitted work, push/pull, CI and PRs. Click one = VS Code + terminal there."""
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self._rows, self._gen = win, [], 0
        rb = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Check again")
        rb.connect("clicked", lambda *_: self.reload()); self.append(header("Projects", rb))
        self.stack = Gtk.Stack(vexpand=True); self.append(self.stack)
        self.stack.add_named(status("folder-symbolic", "Looking at your repos…", ""), "loading")
        self.stack.add_named(status("dialog-information-symbolic", "No projects found", "Repos in ~/Projects show up here (projects --help)"), "missing")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.note = Gtk.Label(xalign=0, css_classes=["dim-label"], margin_start=6); box.append(self.note)
        self.todo = Adw.PreferencesGroup(title="Needs attention"); self.rest = Adw.PreferencesGroup(title="Up to date")
        box.append(self.todo); box.append(self.rest)
        self.stack.add_named(scroller(box), "main")
        self.loaded = False

    def on_show(self):
        if not projects_bin(): self.stack.set_visible_child_name("missing"); return
        if not self.loaded: self.stack.set_visible_child_name("loading")
        self.reload()

    def reload(self):
        self._gen += 1; gen = self._gen
        def work():
            GLib.idle_add(self.render, projects_json(), gen, False)          # git only: instant
            GLib.idle_add(self.render, projects_json(gh=True), gen, True)    # then CI + PRs from GitHub
        threading.Thread(target=work, daemon=True).start()

    def render(self, items, gen, gh):
        if gen != self._gen or (gh and items is None): return False
        if not items: self.stack.set_visible_child_name("missing"); return False
        self.loaded = True
        for g, r in self._rows: g.remove(r)
        self._rows = []
        for i in items:
            row = Adw.ActionRow(title=GLib.markup_escape_text(i["name"]), subtitle=GLib.markup_escape_text(i.get("summary", i["branch"])),
                                activatable=True, tooltip_text=i["path"])
            icon, cls = (("dialog-error-symbolic", "error") if i.get("ci") == "fail" else
                         ("document-edit-symbolic", "warning") if project_attention(i) else ("object-select-symbolic", "success"))
            row.add_prefix(Gtk.Image(icon_name=icon, css_classes=[cls]))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _r, p=i["path"]: self.open(p))
            g = self.todo if project_attention(i) else self.rest
            g.add(row); self._rows.append((g, row))
        n = sum(project_attention(i) for i in items)
        self.note.set_label(f"{len(items)} repos · {n} need attention" + ("" if gh else " · checking GitHub…"))
        self.todo.set_visible(n > 0); self.rest.set_visible(n < len(items))
        self.stack.set_visible_child_name("main"); return False

    def open(self, path):
        self.win.hide_panel()
        subprocess.Popen([projects_bin(), "open", path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ───────────────────────── Services (the `services` tool: ports + Docker) ─────────────────────────
def services_bin():
    import shutil
    return shutil.which("services") or (str(HOME / ".local/bin/services") if (HOME / ".local/bin/services").exists() else None)

def stack_state(items):
    """'running' / 'partial' / 'stopped' and a short label for a compose project."""
    up = sum(c["state"] == "running" for c in items)
    if up == len(items): return "running", f"all {up} running" if up > 1 else "running"
    return ("partial", f"{up} of {len(items)} running") if up else ("stopped", "stopped")

class ServicesPage(Gtk.Box):
    """Dev servers and ports your programs listen on, and Docker containers by compose project: stop, start, logs."""
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self._busy, self._rows = win, False, []
        rb = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Check again")
        rb.connect("clicked", lambda *_: self.reload()); self.append(header("Services", rb))
        self.stack = Gtk.Stack(vexpand=True); self.append(self.stack)
        self.stack.add_named(status("network-server-symbolic", "Looking…", ""), "loading")
        self.stack.add_named(status("dialog-information-symbolic", "The services tool isn't installed", "Run: bash scripts/install-panels.sh"), "missing")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.ports = Adw.PreferencesGroup(title="Listening", description="Ports your programs have open")
        self.docker = Adw.PreferencesGroup(title="Docker")
        box.append(self.ports); box.append(self.docker)
        self.stack.add_named(scroller(box), "main")
        self.loaded = False

    def on_show(self):
        if not services_bin(): self.stack.set_visible_child_name("missing"); return
        if not self.loaded: self.stack.set_visible_child_name("loading")
        self.reload()

    def reload(self):
        if self._busy: return
        self._busy = True
        def work():
            try: d = json.loads(subprocess.run([services_bin(), "--json"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL).stdout or "null")
            except (subprocess.TimeoutExpired, ValueError, OSError, TypeError): d = None
            GLib.idle_add(self.render, d)
        threading.Thread(target=work, daemon=True).start()

    def _btn(self, icon, tip, fn, destructive=False):
        b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER, css_classes=["flat", "circular"] + (["destructive-action"] if destructive else []))
        b.connect("clicked", lambda *_: fn()); return b

    def _add(self, group, row):
        group.add(row); self._rows.append((group, row))

    def render(self, d):
        self._busy = False
        if not d: self.stack.set_visible_child_name("missing"); return False
        self.loaded = True
        for g, r in self._rows: g.remove(r)
        self._rows = []
        for p in d["ports"]:
            sub = " · ".join(x for x in (p.get("what") or p.get("cmd"), p.get("cwd") if not p.get("what") else "",
                                         "local only" if p["local"] else "open to the network") if x)
            row = Adw.ActionRow(title=GLib.markup_escape_text(f":{p['port']}  {p['name']}"), subtitle=GLib.markup_escape_text(sub), subtitle_lines=2)
            row.add_prefix(Gtk.Image(icon_name="network-transmit-receive-symbolic" if p["local"] else "network-wireless-symbolic",
                                     css_classes=["dim-label" if p["local"] else "warning"]))
            if not p.get("what"):
                row.add_suffix(self._btn("web-browser-symbolic", f"Open http://localhost:{p['port']}",
                                         lambda u=f"http://localhost:{p['port']}": self.launch(["xdg-open", u])))
            if not p.get("protected"):
                row.add_suffix(self._btn("process-stop-symbolic", f"Stop {p['name']}", lambda port=p["port"]: self.act(["stop-port", str(port)]), True))
            self._add(self.ports, row)
        if not d["ports"]: self._add(self.ports, Adw.ActionRow(title="Nothing listening", subtitle="Start a dev server and it shows up here"))
        cs = d.get("containers")
        if cs is None: self._add(self.docker, Adw.ActionRow(title="Docker isn't available", subtitle="Not installed, or not running"))
        elif not cs: self._add(self.docker, Adw.ActionRow(title="No containers"))
        for proj, items in (d.get("stacks") or {}).items():
            if proj:
                state, label = stack_state(items)
                exp = Adw.ExpanderRow(title=GLib.markup_escape_text(proj), subtitle=GLib.markup_escape_text(f"{label} · {items[0].get('folder') or 'compose'}"))
                exp.add_prefix(Gtk.Image(icon_name="media-playback-start-symbolic" if state != "stopped" else "media-playback-stop-symbolic",
                                         css_classes=["success" if state == "running" else "warning" if state == "partial" else "dim-label"]))
                exp.add_suffix(self._btn("media-playback-stop-symbolic" if state != "stopped" else "media-playback-start-symbolic",
                                         ("Stop" if state != "stopped" else "Start") + " the whole project",
                                         lambda pr=proj, a=("stop" if state != "stopped" else "start"): self.act(["compose", a, pr])))
                for c in items: exp.add_row(self._container_row(c))
                self._add(self.docker, exp)
            else:
                for c in items: self._add(self.docker, self._container_row(c))
        self.stack.set_visible_child_name("main"); return False

    def _container_row(self, c):
        up = c["state"] == "running"
        sub = " · ".join(x for x in (c["image"], c["status"], c.get("ports")) if x)
        row = Adw.ActionRow(title=GLib.markup_escape_text(c.get("service") or c["name"]), subtitle=GLib.markup_escape_text(sub), subtitle_lines=2)
        row.add_suffix(self._btn("utilities-terminal-symbolic", "Logs", lambda n=c["name"]: self.launch(terminal_cmd(f"logs {n}", services_bin(), "logs", n))))
        row.add_suffix(self._btn("media-playback-stop-symbolic" if up else "media-playback-start-symbolic", "Stop" if up else "Start",
                                 lambda n=c["name"], a=("stop" if up else "start"): self.act(["docker", a, n])))
        return row

    def launch(self, argv):
        self.win.hide_panel(); subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def act(self, args):
        def work():
            r = subprocess.run([services_bin(), *args], capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
            GLib.idle_add(lambda: (self.win.toast((r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else "Done"), self.reload(), False)[2])
        self.win.toast("Working…"); threading.Thread(target=work, daemon=True).start()


# ───────────────────────── Agent tasks (the `tasks` tool) ─────────────────────────
def tasks_bin():
    import shutil
    return shutil.which("tasks") or (str(HOME / ".local/bin/tasks") if (HOME / ".local/bin/tasks").exists() else None)

TASK_LOOK = {"queued": ("content-loading-symbolic", "dim-label", "Queued"), "running": ("emblem-synchronizing-symbolic", "accent", "Working"),
             "review": ("emblem-default-symbolic", "success", "Ready to review"), "failed": ("dialog-error-symbolic", "error", "Failed"),
             "merged": ("object-select-symbolic", "dim-label", "Merged"), "discarded": ("user-trash-symbolic", "dim-label", "Discarded")}

class TasksPage(Gtk.Box):
    """Hand a coding task to Claude or Codex: it works on its own branch; you review the diff, then merge or discard."""
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self._rows, self._repos, self._busy = win, [], [], False
        rb = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat", "circular"], tooltip_text="Refresh")
        rb.connect("clicked", lambda *_: self.reload()); self.append(header("Agent tasks", rb))
        self.stack = Gtk.Stack(vexpand=True); self.append(self.stack)
        self.stack.add_named(status("dialog-information-symbolic", "The task board isn't installed", "Run: bash scripts/install-panels.sh"), "missing")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        new = Adw.PreferencesGroup(title="New task", description="Runs on its own branch; your checkout isn't touched.")
        self.repo = Adw.ComboRow(title="Project"); self.agent = Adw.ComboRow(title="Agent", model=Gtk.StringList.new(["claude", "codex"]))
        self.prompt = Adw.EntryRow(title="What should it do?")
        self.prompt.connect("entry-activated", lambda *_: self.add())
        go = Gtk.Button(label="Start", css_classes=["pill", "suggested-action"], halign=Gtk.Align.END, margin_top=8)
        go.connect("clicked", lambda *_: self.add())
        for w in (self.repo, self.agent, self.prompt): new.add(w)
        box.append(new); box.append(go)
        self.active = Adw.PreferencesGroup(title="Tasks"); self.old = Adw.PreferencesGroup(title="Done")
        box.append(self.active); box.append(self.old)
        self.stack.add_named(scroller(box), "main")

    def on_show(self):
        if not tasks_bin(): self.stack.set_visible_child_name("missing"); return
        self.stack.set_visible_child_name("main"); self.reload()

    def reload(self):
        def work():
            try: ts = json.loads(subprocess.run([tasks_bin(), "ls", "--json"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL).stdout or "[]")
            except (subprocess.TimeoutExpired, ValueError, OSError): ts = []
            repos = (projects_json() or []) if not self._repos else None
            GLib.idle_add(self.render, ts, repos)
        threading.Thread(target=work, daemon=True).start()

    def render(self, ts, repos):
        if repos is not None:
            self._repos = [r["path"] for r in repos]
            self.repo.set_model(Gtk.StringList.new([r["name"] for r in repos] or ["(no repos in ~/Projects)"]))
        for g, r in self._rows: g.remove(r)
        self._rows = []
        for t in ts:
            icon, cls, label = TASK_LOOK.get(t["state"], TASK_LOOK["failed"])
            sub = " · ".join(x for x in (label, t["agent"], t["name"], t.get("stat") or t.get("error")) if x)
            row = Adw.ActionRow(title=GLib.markup_escape_text(t["task"][:80]), subtitle=GLib.markup_escape_text(sub), subtitle_lines=2,
                                tooltip_text=t.get("branch", ""))
            row.add_prefix(Gtk.Image(icon_name=icon, css_classes=[cls]))
            acts = {"running": [("utilities-terminal-symbolic", "Watch the agent's output", ["log", "-f"], True)],
                    "review": [("document-properties-symbolic", "See the changes", ["diff"], True),
                               ("system-search-symbolic", "Second opinion: another agent reviews it", ["review"], True),
                               ("object-select-symbolic", "Merge into " + t.get("base", "the branch"), ["merge"], False),
                               ("user-trash-symbolic", "Discard the branch", ["discard"], False)],
                    "failed": [("utilities-terminal-symbolic", "What happened", ["log"], True),
                               ("view-refresh-symbolic", "Try again", ["start"], False),
                               ("user-trash-symbolic", "Discard", ["discard"], False)],
                    "queued": [("media-playback-start-symbolic", "Start", ["start"], False),
                               ("user-trash-symbolic", "Discard", ["discard"], False)]}.get(t["state"], [])
            for ic, tip, args, term in acts:
                b = Gtk.Button(icon_name=ic, tooltip_text=tip, valign=Gtk.Align.CENTER, css_classes=["flat", "circular"])
                b.connect("clicked", lambda _b, a=args, i=t["id"], tm=term: self.act(a, i, tm)); row.add_suffix(b)
            g = self.old if t["state"] in ("merged", "discarded") else self.active
            g.add(row); self._rows.append((g, row))
        self.active.set_visible(any(g is self.active for g, _ in self._rows))
        self.old.set_visible(any(g is self.old for g, _ in self._rows))
        return False

    def add(self):
        text = self.prompt.get_text().strip(); i = self.repo.get_selected()
        if not text or i >= len(self._repos): self.win.toast("Pick a project and say what to do"); return
        agent = ["claude", "codex"][self.agent.get_selected()]
        self.prompt.set_text("")
        self.run([tasks_bin(), "add", self._repos[i], text, "--agent", agent, "--start"])

    def act(self, args, tid, term):
        if term:
            self.win.hide_panel()
            cmd = [tasks_bin(), args[0], tid, *args[1:]]
            line = " ".join(shlex.quote(c) for c in cmd) + ("" if "-f" in args else " | less -R")
            subprocess.Popen(terminal_cmd(f"task {tid}", "sh", "-c", line),
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else: self.run([tasks_bin(), args[0], tid])

    def run(self, argv):
        def work():
            r = subprocess.run(argv, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
            msg = (r.stdout or r.stderr).strip().splitlines()
            GLib.idle_add(lambda: (self.win.toast(msg[-1] if msg else "Done"), self.reload(), False)[2])
        threading.Thread(target=work, daemon=True).start()


class Panel(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Quick Settings", default_width=W, default_height=H, resizable=False,
                         css_classes=["panel"])
        self.page = None; self.shown_at = 0
        self.toasts = Adw.ToastOverlay(); self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        # each page is built the first time it's opened (then kept for instant reopen): no NM / BlueZ / clipboard work
        # for pages you never use
        self.pages, self.page_types = {}, {"wifi": WifiPage, "bluetooth": BluetoothPage, "clipboard": ClipboardPage,
                                           "calendar": CalendarPage, "inbox": InboxPage, "remote": RemotePage,
                                           "phone": PhonePage, "storage": StoragePage,
                                           "security": SecurityPage, "battery": BatteryPage,
                                           "projects": ProjectsPage, "services": ServicesPage, "tasks": TasksPage}
        self.toasts.set_child(self.stack); self.set_content(self.toasts)
        key = Gtk.EventControllerKey(); key.connect("key-pressed", lambda _c, k, *_: k == Gdk.KEY_Escape and (self.escape() or True))
        self.add_controller(key)
        self.connect("notify::is-active", self._focus)
        self.connect("close-request", lambda *_: (self.hide_panel(), True)[1])

    def _focus(self, *_):
        if os.environ.get("MYOS_PANEL_NOHIDE") or getattr(self, "keep_open", False):
            return
        if not self.is_active() and self.is_visible() and time.time() - self.shown_at > 0.4 and not self.get_visible_dialog():
            self.hide_panel()

    def show_page(self, name):
        if self.is_visible() and self.page == name: self.hide_panel(); return
        if name not in self.pages:
            self.pages[name] = self.page_types[name](self); self.stack.add_named(self.pages[name], name)
        self.page = name; self.stack.set_visible_child_name(name); self.shown_at = time.time()
        self.set_default_size(W, 640 if name in ("calendar", "inbox", "remote", "phone", "storage", "security", "battery", "projects", "services", "tasks") else H)
        self.present(); self.pages[name].on_show()
        GLib.timeout_add(60, self._place)

    def _place(self):
        try:
            mon = next(m for m in json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True).stdout) if m["focused"])
            x, y = panel_origin(mon, W)
            subprocess.run(["hyprctl", "dispatch", "movewindowpixel", f"exact {x} {y},class:^(org\\.myos\\.Panel)$"], capture_output=True)
        except Exception: pass
        return False

    def escape(self):
        rp = self.pages.get("remote")       # inside Remote's sub-views (find / add / setup) Esc steps back first
        if self.page == "remote" and rp and rp.back.get_visible(): rp.step_back()
        else: self.hide_panel()

    def hide_panel(self): self.set_visible(False)
    def toast(self, msg): self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(msg), timeout=4))

PAGES = ("wifi", "bluetooth", "clipboard", "calendar", "inbox", "remote", "phone", "storage", "security", "battery", "projects", "services", "tasks")

class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.myos.Panel", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None
        # "show" action: the myos-panel wrapper calls it over D-Bus, so reopening skips Python startup entirely
        act = Gio.SimpleAction.new("show", GLib.VariantType.new("s"))
        act.connect("activate", lambda _a, v: self.open(v.get_string())); self.add_action(act)
    def do_command_line(self, cmd):
        args = cmd.get_arguments()[1:]; page = args[0] if args else "wifi"
        if page not in PAGES: cmd.printerr_literal(f"unknown page: {page}\n"); return 2
        self.open(page); return 0
    def open(self, page):
        if page not in PAGES: return
        if not self.win:
            prov = Gtk.CssProvider(); prov.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            self.win = Panel(self); self.hold()   # stay resident for instant reopen
        self.win.show_page(page)

if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
