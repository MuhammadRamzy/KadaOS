#!/usr/bin/env python3
"""Off-screen UI/UX, theme and notification-popup test for Hydration.

Run through tests/hydration_suite.sh (private D-Bus + GTK broadway + stubbed systemctl).
Every panel widget, the Clear dialog, toasts, the notification popup and the CLI are driven
through GTK's own activation/focus code, never real input. Nothing reaches the live desktop.
Screenshots go to $HYDRATION_SHOTS.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = str(ROOT / "tests/hydration_session.py")
assert os.environ.get("DBUS_SESSION_BUS_ADDRESS", "").startswith("unix:"), "Use dbus-run-session"
assert os.environ.get("GDK_BACKEND") == "broadway", "Off-screen only: GDK_BACKEND=broadway"
# Cut every route to the live session: no Wayland/X socket, no Hyprland IPC, no portals.
for var in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_CURRENT_DESKTOP"):
    os.environ.pop(var, None)
os.environ["GDK_DEBUG"] = "no-portals"
os.environ["GTK_USE_PORTAL"] = "0"
SHOTS = Path(os.environ.get("HYDRATION_SHOTS", tempfile.mkdtemp(prefix="hydration-shots-")))
SHOTS.mkdir(parents=True, exist_ok=True)

# Sandbox HOME (keep the real GTK theme files so the render matches the desktop).
REAL_HOME = Path.home()
HOME = Path(tempfile.mkdtemp(prefix="hydration-ui-"))
(HOME / ".config").mkdir()
for name in ("gtk-4.0", "gtk-3.0", "dconf"):  # dconf: real accent colour/fonts (read only)
    if (REAL_HOME / ".config" / name).exists():
        (HOME / ".config" / name).symlink_to(REAL_HOME / ".config" / name)

# systemctl stub: the panel's startup switch / Start button must never touch the real user manager.
STUB = HOME / "stub"
STUB.mkdir()
(STUB / "systemctl").write_text(f"""#!/bin/sh
echo "$*" >> "{STUB}/calls"
case "$*" in
  *is-enabled*) [ -f "{STUB}/enabled" ] ;;
  *disable*) rm -f "{STUB}/enabled" ;;
  *" enable "*) touch "{STUB}/enabled" ;;
esac
""")
(STUB / "systemctl").chmod(0o755)
os.environ.update(HOME=str(HOME), MYOS_HYDRATION_TEST="1", PATH=f"{STUB}:{os.environ['PATH']}")
assert shutil.which("systemctl") == str(STUB / "systemctl"), "systemctl stub not first on PATH"

sys.path.insert(0, str(ROOT / "config/desktop"))
import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402
import hydration  # noqa: E402
import hydration_panel  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'} {name}{'' if ok else '  -> ' + str(detail)}", flush=True)


def section(title):
    print(f"\n{title}", flush=True)


def pump(seconds=0.25):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


def wait(fn, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = fn()
            if value:
                return value
        except Exception:
            pass
        pump(0.1)
    return None


def press(button):
    # Wait like a person would: rows inside the expander appear after its reveal animation.
    assert wait(lambda: button.get_mapped() and button.get_sensitive(), 3), f"{button.get_label()} not clickable"
    button.emit("clicked")  # the same handler a mouse click or Enter runs
    pump(0.3)


def status():
    return hydration.request({"action": "status"})


def snapshot(widget, name):
    node = None
    for _ in range(50):
        pump(0.1)
        w, h = widget.get_width(), widget.get_height()
        if w and h:
            snap = Gtk.Snapshot()
            Gtk.WidgetPaintable.new(widget).snapshot(snap, w, h)
            node = snap.to_node()
            if node:
                break
    assert node, f"{name}: widget never rendered"
    texture = widget.get_native().get_renderer().render_texture(node, None)
    path = SHOTS / f"{name}.png"
    texture.save_to_png(str(path))
    return texture, path


def pixel(texture, x, y):
    data = texture.save_to_png_bytes().get_data()
    from PIL import Image
    import io
    return Image.open(io.BytesIO(data)).convert("RGB").getpixel((x, y))


def center_of(widget, window):
    ok, point = widget.compute_point(window, Graphene.Point().init(widget.get_width() / 2, widget.get_height() / 2))
    return int(point.x), int(point.y)


gi.require_version("Graphene", "1.0")
from gi.repository import Graphene  # noqa: E402


def luminance(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


def notification():
    return json.loads((HOME / "notification.json").read_text())


def fake_call(method, args):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                  "org.freedesktop.Notifications", method, args, None, Gio.DBusCallFlags.NONE, 3000, None)


def cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "config/desktop/hydration.py"), *args],
                          capture_output=True, text=True, timeout=15)


notifier = subprocess.Popen([sys.executable, FIXTURE, "notifications"])
service = None
try:
    time.sleep(0.4)

    # ── Offline first: the panel opened before the service exists ──
    app = Adw.Application(application_id="org.myos.Hydration.UITest", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
    toasts = []
    original_message = hydration_panel.Panel.message
    hydration_panel.Panel.message = lambda self, text: (toasts.append(text), original_message(self, text))
    win = hydration_panel.Panel(app)
    win.present()
    pump(0.6)

    section("Offline state (service not running)")
    check("heading says the service is offline", win.heading.get_label() == "Reminder service is offline", win.heading.get_label())
    check("reason reassures history is saved", "history is saved" in win.reason.get_label(), win.reason.get_label())
    check("Start reminders button visible", win.recover.get_visible())
    for w, label in ((win.log, "Drank water"), (win.snooze, "Snooze"), (win.pause, "Pause"), (win.startup, "Start after login")):
        check(f"{label} disabled while offline", not w.get_sensitive())
    check("Undo disabled while offline", not win.undo.get_sensitive())
    check("Save settings disabled while offline", not win.apply.get_sensitive())
    snapshot(win, "01-offline")
    toasts.clear()
    press(win.recover)
    calls = (STUB / "calls").read_text() if (STUB / "calls").exists() else ""
    check("Start reminders runs systemctl --user start (stubbed)", "--user start myos-hydration.service" in calls, calls)
    r = cli("status")
    check("CLI reports offline with exit 1", r.returncode == 1 and "Hydration unavailable" in r.stderr, (r.returncode, r.stderr))

    # ── Bring the service up; the panel's own 5 s timer should reconnect ──
    service = subprocess.Popen([sys.executable, FIXTURE, "service"])
    check("service fixture answers", wait(status))
    win.refresh()
    pump()

    section("Main page (connected)")
    check("heading shows Running", win.heading.get_label() == "Running", win.heading.get_label())
    check("reason shows active minutes", re.fullmatch(r"About \d+ active minutes until the next reminder", win.reason.get_label()), win.reason.get_label())
    check("Start reminders hidden once connected", not win.recover.get_visible())
    for w, label in ((win.log, "Drank water"), (win.snooze, "Snooze 10 min"), (win.pause, "Pause today")):
        check(f"button '{label}' present and enabled", w.get_label() == label and w.get_sensitive(), (w.get_label(), w.get_sensitive()))
    check("primary action styled as accent pill", {"suggested-action", "pill"} <= set(win.log.get_css_classes()))
    check("empty history: Confirmed today = 0", win.today.get_subtitle() == "0", win.today.get_subtitle())
    check("empty history: no breaks message", win.last.get_subtitle() == "No breaks recorded yet", win.last.get_subtitle())
    check("Undo disabled with nothing to undo", not win.undo.get_sensitive())
    check("Save settings disabled until something changes", not win.apply.get_sensitive())
    check("footer caption present", any(isinstance(w, Gtk.Label) and w.get_label() == "Quiet reminders. Local data. Your pace." for w in walk(win)))
    check("header bar present with window title", any(isinstance(w, Adw.HeaderBar) for w in walk(win)) and win.get_title() == "Hydration")
    check("warning line empty when all detection works", win.warning.get_label() == "")
    snapshot(win, "02-main")

    section("Buttons change real state")
    toasts.clear()
    press(win.log)
    check("Drank water → Confirmed today = 1", win.today.get_subtitle() == "1", win.today.get_subtitle())
    check("Drank water → toast 'Water break recorded'", "Water break recorded" in toasts, toasts)
    check("Drank water → service history = 1", status()["today"] == 1)
    check("last break uses 12-hour time", re.fullmatch(r"\d{1,2}:\d{2} (AM|PM) · \d{2} \w{3}", win.last.get_subtitle()), win.last.get_subtitle())
    check("Undo enabled after logging", win.undo.get_sensitive())
    snapshot(win, "03-after-drank")
    press(win.undo)
    check("Undo → Confirmed today = 0", win.today.get_subtitle() == "0")
    check("Undo → toast 'Last entry undone'", "Last entry undone" in toasts, toasts)
    check("Undo → disabled again", not win.undo.get_sensitive())
    press(win.snooze)
    check("Snooze → heading Snoozed", win.heading.get_label() == "Snoozed", win.heading.get_label())
    check("Snooze → toast", "Snoozed for 10 active minutes" in toasts, toasts)
    check("Snooze → about 10 active minutes", "About 10 active minutes" in win.reason.get_label(), win.reason.get_label())
    press(win.pause)
    check("Pause today → heading Paused", win.heading.get_label() == "Paused", win.heading.get_label())
    check("Pause today → reason shows resume time", win.reason.get_label().startswith("Paused until "), win.reason.get_label())
    check("Pause today → button becomes Resume reminders", win.pause.get_label() == "Resume reminders")
    snapshot(win, "04-paused")
    press(win.pause)
    check("Resume reminders → Running again", win.heading.get_label() == "Running", win.heading.get_label())
    check("Resume reminders → button back to Pause today", win.pause.get_label() == "Pause today")

    section("Settings expander")
    expander = next(w for w in walk(win) if isinstance(w, Adw.ExpanderRow))
    check("settings expander titled", expander.get_title() == "Reminder settings")
    expander.set_expanded(True)
    check("settings rows appear when expanded", wait(lambda: win.startup.get_mapped() and win.start.get_mapped(), 3))
    pump(0.6)  # finish the reveal animation before the screenshot
    titles = {w.get_title() for w in walk(win) if isinstance(w, Adw.PreferencesRow)}
    for t in ("Active minutes between breaks", "Pause after idle seconds", "Start time · 24-hour HH:MM",
              "End time · 24-hour HH:MM", "Wait during fullscreen apps", "Wait while microphone is in use",
              "Apply changes", "Start after login", "Local history"):
        check(f"settings row '{t}'", t in titles)
    cfg = status()["settings"]
    check("fields loaded from the service", (win.interval.get_value(), win.idle.get_value(), win.start.get_text(),
          win.end.get_text(), win.fullscreen.get_active(), win.calls.get_active()) ==
          (cfg["interval"], cfg["idle"], cfg["start"], cfg["end"], cfg["fullscreen"], cfg["calls"]))
    check("interval range 15–180 step 5", (win.interval.get_adjustment().get_lower(), win.interval.get_adjustment().get_upper(),
          win.interval.get_adjustment().get_step_increment()) == (15, 180, 5))
    check("idle range 30–900 step 30", (win.idle.get_adjustment().get_lower(), win.idle.get_adjustment().get_upper(),
          win.idle.get_adjustment().get_step_increment()) == (30, 900, 30))
    win.set_default_size(430, 1100)  # tall enough to show every settings row
    pump(0.5)
    snapshot(win, "05-settings")
    win.set_default_size(430, 680)
    win.interval.set_value(60)
    pump()
    check("editing enables Save settings", win.apply.get_sensitive())
    toasts.clear()
    press(win.apply)
    check("Save → toast 'Settings saved…'", any(t.startswith("Settings saved") for t in toasts),
          (toasts, win.apply.get_realized(), win.apply.get_mapped(), win.apply.get_sensitive()))
    check("Save → service interval 60", status()["settings"]["interval"] == 60)
    check("Save → button disabled again", not win.apply.get_sensitive())
    saved = status()["settings"]
    for field, value, expect in ((win.start, "9am", "HH:MM"), (win.end, "25:00", "HH:MM")):
        good = field.get_text()
        field.set_text(value)
        toasts.clear()
        press(win.apply)
        check(f"invalid time '{value}' rejected with message", any(expect in t for t in toasts), toasts)
        check(f"invalid time '{value}' not saved", (status()["settings"]["start"], status()["settings"]["end"]) == (saved["start"], saved["end"]))
        check(f"invalid time '{value}' keeps Save enabled to retry", win.apply.get_sensitive())
        field.set_text(good)
    win.end.set_text(win.start.get_text())
    toasts.clear()
    press(win.apply)
    check("start == end rejected", any("differ" in t for t in toasts), toasts)
    win.end.set_text(saved["end"])
    for switch, key in ((win.fullscreen, "fullscreen"), (win.calls, "calls")):
        switch.set_active(not switch.get_active())
        press(win.apply)
        check(f"switch '{key}' saved", status()["settings"][key] == switch.get_active())
        switch.set_active(not switch.get_active())
        press(win.apply)
    win.idle.set_value(300)
    press(win.apply)
    check("idle seconds saved", status()["settings"]["idle"] == 300)

    section("Start after login switch (systemctl stubbed)")
    (STUB / "calls").write_text("")
    win.startup.set_active(True)
    pump(0.5)
    check("switch on → systemctl enable", "--user enable myos-hydration.service" in (STUB / "calls").read_text())
    check("switch on → state on", win.startup.get_state() and win.startup.get_active())
    win.startup.set_active(False)
    pump(0.5)
    check("switch off → systemctl disable", "--user disable myos-hydration.service" in (STUB / "calls").read_text())
    check("switch off → state off", not win.startup.get_state() and not win.startup.get_active())

    section("Clear history dialog")
    press(win.log)
    clear_button = next(w for w in walk(win) if isinstance(w, Gtk.Button) and w.get_label() == "Clear…")
    def open_dialog():
        press(clear_button)
        return wait(lambda: win.get_visible_dialog())
    def dialog_button(dialog, label):
        return next(w for w in walk(dialog) if isinstance(w, Gtk.Button) and w.get_label() == label)
    def tab_escapes_history():  # regression: the old MessageDialog trapped Tab on "Confirmed today"
        win.set_focus(None)
        titles = []
        for _ in range(8):
            win.emit("move-focus", Gtk.DirectionType.TAB_FORWARD)
            pump(0.03)
            f = win.get_focus()
            titles.append(f.get_title() if isinstance(f, Adw.PreferencesRow) else None)
        return "Last confirmed break" in titles
    dialog = open_dialog()
    check("Clear… opens a dialog", isinstance(dialog, Adw.AlertDialog), dialog)
    if dialog:
        check("dialog heading", dialog.get_heading() == "Clear water-break history?")
        check("dialog body explains effect", dialog.get_body() == "This removes confirmed entries from this laptop.")
        check("dialog buttons Cancel + Clear history", dialog.get_response_label("cancel") == "Cancel" and dialog.get_response_label("clear") == "Clear history")
        check("Clear history styled destructive", dialog.get_response_appearance("clear") == Adw.ResponseAppearance.DESTRUCTIVE
              and "destructive-action" in dialog_button(dialog, "Clear history").get_css_classes())
        check("default and Esc response is Cancel", dialog.get_default_response() == "cancel" and dialog.get_close_response() == "cancel")
        check("dialog is modal over the panel", win.get_visible_dialog() is dialog)
        pump(1.2)  # let the open animation finish
        tex, _ = snapshot(dialog, "06-clear-dialog")
        b = dialog_button(dialog, "Clear history")
        bx, by = center_of(b, dialog)
        red = pixel(tex, bx - b.get_width() // 3, by)
        check("destructive button renders with a red tint", red[0] > red[1] + 10 and red[0] > red[2] + 10, red)
        press(dialog_button(dialog, "Cancel"))
        check("Cancel closes the dialog", wait(lambda: win.get_visible_dialog() is None))
        check("Cancel keeps history", status()["today"] == 1)
        check("Tab still moves through the panel after the dialog", tab_escapes_history())
        dialog = open_dialog()
        dialog.close()  # Esc → close-response
        check("Esc closes the dialog", wait(lambda: win.get_visible_dialog() is None))
        check("Esc keeps history", status()["today"] == 1)
        dialog = open_dialog()
        press(dialog_button(dialog, "Clear history"))
        check("Clear history closes the dialog", wait(lambda: win.get_visible_dialog() is None))
        check("Clear history removes entries", wait(lambda: status()["today"] == 0) and win.today.get_subtitle() == "0")
        check("Tab still moves through the panel after clearing", tab_escapes_history())

    section("Warning line")
    hydration.request({"action": "test-warning", "text": "Call detection unavailable"})
    win.refresh()
    pump()
    check("call-detection warning shown", win.warning.get_label() == "Call detection unavailable", win.warning.get_label())
    hydration.request({"action": "test-warning", "text": ""})
    win.refresh()

    section("Keyboard + accessibility")
    expander.set_expanded(True)
    wait(lambda: win.startup.get_mapped() and win.start.get_mapped(), 3)
    win.set_focus(None)
    seen = []
    for _ in range(200):
        win.emit("move-focus", Gtk.DirectionType.TAB_FORWARD)  # exactly what the Tab key binding emits
        focus = win.get_focus()
        if focus is None or focus in seen:
            break
        seen.append(focus)
    def reachable(target):
        return any(f is target or f.is_ancestor(target) for f in seen)
    for w, label in ((win.log, "Drank water"), (win.snooze, "Snooze"), (win.pause, "Pause"), (win.undo, "Undo") if win.undo.get_sensitive() else (win.log, "Drank water")):
        check(f"Tab reaches {label}", reachable(w))
    check("Tab reaches the time entries", reachable(win.start) and reachable(win.end),
          [f"{type(f).__name__}:{getattr(f, 'get_label', lambda: '')() or ''}" for f in seen])
    check("Tab reaches Start after login", reachable(win.startup))
    def in_window_controls(w):  # minimise/maximise/close: GTK names these itself
        return w.get_ancestor(Gtk.WindowControls) is not None
    unlabeled = [w for w in walk(win) if isinstance(w, Gtk.Button) and w.get_mapped() and not in_window_controls(w)
                 and not (w.get_label() or w.get_tooltip_text() or w.get_icon_name()
                          or w.get_accessible_role() == Gtk.AccessibleRole.SPIN_BUTTON)]
    check("every visible button has a label/name", not unlabeled, [(type(w.get_parent()).__name__, w.get_css_classes()) for w in unlabeled])
    untitled = [w for w in walk(win) if isinstance(w, Adw.PreferencesRow) and w.get_visible() and not w.get_title()]
    check("every settings row has a title", not untitled)
    check("startup switch is the row's activatable widget", any(isinstance(w, Adw.ActionRow) and w.get_title() == "Start after login"
          and w.get_activatable_widget() is win.startup for w in walk(win)))

    section("Theme (Graphite)")
    expander.set_expanded(False)
    win.refresh()
    pump(4)  # let toasts time out so they don't cover the sample points
    tex, path = snapshot(win, "07-theme")
    check("dark color scheme active", Adw.StyleManager.get_default().get_dark())
    bg = pixel(tex, 12, win.get_height() - 12)
    check("graphite dark surface", luminance(bg) < 70 and max(bg) - min(bg) < 20, bg)
    x, y = center_of(win.log, win)
    btn = pixel(tex, x - win.log.get_width() // 3, y)
    check("primary button uses the Graphite blue accent", btn[2] > 150 and btn[2] > btn[0] + 60, btn)
    check("desktop accent setting is blue (Graphite)", Adw.StyleManager.get_default().get_accent_color() == Adw.AccentColor.BLUE,
          Adw.StyleManager.get_default().get_accent_color())
    check("heading text is large title style", "title-1" in win.heading.get_css_classes())
    fg = win.heading.get_color()
    check("light text on the dark surface", min(fg.red, fg.green, fg.blue) > 0.7, (fg.red, fg.green, fg.blue))
    check("icon resolves in theme", Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).has_icon("weather-showers-symbolic"))

    section("Layout")
    check("minimum window size 360×420", win.get_size_request() == (360, 420), win.get_size_request())
    minimum = win.get_content().measure(Gtk.Orientation.HORIZONTAL, -1)[0]
    check("content fits a 360 px window (no clipping)", minimum <= 360, minimum)
    scroll = next(w for w in walk(win) if isinstance(w, Gtk.ScrolledWindow))
    check("no horizontal scrolling", scroll.get_policy()[0] == Gtk.PolicyType.NEVER)
    check("long status text wraps", win.heading.get_wrap() and win.reason.get_wrap() and win.warning.get_wrap())
    win.set_default_size(360, 520)
    pump(0.5)
    snapshot(win, "08-narrow")

    section("Notification popup")
    nid = hydration.request({"action": "test-due"})["id"]
    n = notification()["arguments"]
    app_name, _, icon, summary, body, actions, hints, timeout = n
    check("title 'Time for a water break'", summary == "Time for a water break", summary)
    check("first body mentions the interval", re.search(r"About \d+ minutes of active screen time", body), body)
    check("three buttons: Drank water · Snooze 10 min · Pause today",
          actions == ["drank", "Drank water", "snooze", "Snooze 10 min", "pause", "Pause today"], actions)
    check("silent (suppress-sound)", hints.get("suppress-sound") is True)
    check("transient, normal urgency, linked to the app", hints.get("transient") is True and hints.get("urgency") == 1
          and hints.get("desktop-entry") == "org.myos.Hydration", hints)
    check("icon + app name", icon == "weather-showers-symbolic" and app_name == "Hydration")
    check("auto-hides (timeout 20 s)", timeout == 20000)
    before = status()["today"]
    fake_call("Dismiss", GLib.Variant("(u)", (nid,)))
    pump(0.5)
    check("dismissing the popup does not log a drink", status()["today"] == before)
    fake_call("Invoke", GLib.Variant("(us)", (nid, "drank")))
    pump(0.5)
    check("button on a dismissed popup is ignored", status()["today"] == before)
    nid = hydration.request({"action": "test-due"})["id"]
    nid = hydration.request({"action": "test-due"})["id"]
    check("unanswered retry uses the gentle follow-up body", "left unconfirmed" in notification()["arguments"][4], notification()["arguments"][4])
    fake_call("Invoke", GLib.Variant("(us)", (nid, "drank")))
    check("popup Drank water logs once", wait(lambda: status()["today"] == before + 1))
    win.refresh()
    pump()
    check("panel reflects popup action", win.today.get_subtitle() == str(before + 1))

    section("CLI commands (Super+Space actions and desktop actions use these)")
    for command, test in (("status", lambda d: "title" in d), ("drank", lambda d: d["today"] == before + 2),
                          ("undo", lambda d: d["today"] == before + 1), ("snooze", lambda d: d["title"] == "Snoozed"),
                          ("pause", lambda d: d["paused"]), ("resume", lambda d: not d["paused"]),
                          ("clear", lambda d: d["today"] == 0)):
        r = cli(command)
        try:
            ok = r.returncode == 0 and test(json.loads(r.stdout))
        except ValueError:
            ok = False
        check(f"myos-hydration {command}", ok, r.stderr or r.stdout)

    section("Escape closes the panel")
    handled = win.key(None, Gdk.KEY_Escape, 0, 0)
    pump()
    check("Esc handled and window closed", handled and not win.get_visible())
    check("refresh timer stopped on close", win.timer is None)
finally:
    for child in (service, notifier):
        if child is not None:
            child.terminate()
            child.wait(timeout=5)
    shutil.rmtree(HOME, ignore_errors=True)

failed = [n for n, ok in RESULTS if not ok]
print(f"\nUI suite: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed. Screenshots: {SHOTS}")
sys.exit(1 if failed else 0)
