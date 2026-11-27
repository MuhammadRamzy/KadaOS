"""Native Hydration controls, using KadaOS's existing libadwaita/Graphite theme."""
from datetime import datetime
import subprocess
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from hydration import request


class Panel(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Hydration", default_width=430, default_height=680)
        self.set_size_request(360, 420)
        self.dirty = False
        self.connected = False
        self.loaded = False
        self.toast = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.set_content(self.toast)
        self.toast.set_child(view)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        view.set_content(scroll)
        clamp = Adw.Clamp(maximum_size=500)
        scroll.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                       margin_start=24, margin_end=24, margin_top=12, margin_bottom=28)
        clamp.set_child(body)
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        intro.append(Gtk.Image(icon_name="weather-showers-symbolic", pixel_size=40,
                               halign=Gtk.Align.START))
        self.heading = Gtk.Label(label="Connecting…", xalign=0, css_classes=["title-1"], wrap=True)
        self.reason = Gtk.Label(xalign=0, wrap=True)
        self.recover = Gtk.Button(label="Start reminders", halign=Gtk.Align.START)
        self.recover.connect("clicked", self.start_service)
        intro.append(self.heading)
        intro.append(self.reason)
        intro.append(self.recover)
        body.append(intro)

        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.log = Gtk.Button(label="Drank water", css_classes=["suggested-action", "pill"])
        self.log.connect("clicked", lambda *_: self.act("drank", "Water break recorded"))
        actions.append(self.log)
        secondary = Gtk.Box(spacing=8, homogeneous=True)
        self.snooze = Gtk.Button(label="Snooze 10 min")
        self.snooze.connect("clicked", lambda *_: self.act("snooze", "Snoozed for 10 active minutes"))
        self.pause = Gtk.Button(label="Pause today")
        self.pause.connect("clicked", lambda *_: self.act("resume" if self.paused else "pause"))
        secondary.append(self.snooze)
        secondary.append(self.pause)
        actions.append(secondary)
        body.append(actions)

        history = Adw.PreferencesGroup(title="Your water breaks", description="Only breaks you confirm are recorded.")
        self.today = Adw.ActionRow(title="Confirmed today")
        self.last = Adw.ActionRow(title="Last confirmed break")
        self.undo = Gtk.Button(label="Undo", valign=Gtk.Align.CENTER)
        self.undo.connect("clicked", lambda *_: self.act("undo", "Last entry undone"))
        self.last.add_suffix(self.undo)
        history.add(self.today)
        history.add(self.last)
        body.append(history)

        group = Adw.PreferencesGroup()
        expand = Adw.ExpanderRow(title="Reminder settings", subtitle="Active time, hours, and interruptions")
        group.add(expand)
        self.interval = Adw.SpinRow.new_with_range(15, 180, 5)
        self.interval.set_title("Active minutes between breaks")
        self.idle = Adw.SpinRow.new_with_range(30, 900, 30)
        self.idle.set_title("Pause after idle seconds")
        expand.add_row(self.interval)
        expand.add_row(self.idle)
        self.start = Adw.EntryRow(title="Start time · 24-hour HH:MM")
        self.end = Adw.EntryRow(title="End time · 24-hour HH:MM")
        expand.add_row(self.start)
        expand.add_row(self.end)
        self.fullscreen = Adw.SwitchRow(title="Wait during fullscreen apps")
        self.calls = Adw.SwitchRow(title="Wait while microphone is in use")
        expand.add_row(self.fullscreen)
        expand.add_row(self.calls)
        for obj, prop in ((self.interval, "value"), (self.idle, "value"),
                          (self.start, "text"), (self.end, "text"),
                          (self.fullscreen, "active"), (self.calls, "active")):
            obj.connect("notify::" + prop, self.changed)
        row = Adw.ActionRow(title="Apply changes")
        self.apply = Gtk.Button(label="Save settings", valign=Gtk.Align.CENTER)
        self.apply.connect("clicked", self.save)
        row.add_suffix(self.apply)
        expand.add_row(row)
        startup_row = Adw.ActionRow(title="Start after login")
        self.startup = Gtk.Switch(valign=Gtk.Align.CENTER)
        startup_row.add_suffix(self.startup)
        startup_row.set_activatable_widget(self.startup)
        self.startup.set_active(subprocess.run(["systemctl", "--user", "is-enabled", "--quiet",
            "myos-hydration.service"], check=False).returncode == 0)
        self.startup.connect("state-set", self.set_startup)
        expand.add_row(startup_row)
        clear_row = Adw.ActionRow(title="Local history", subtitle="Automatically removed after 30 days")
        clear = Gtk.Button(label="Clear…", valign=Gtk.Align.CENTER)
        clear.connect("clicked", self.clear_history)
        clear_row.add_suffix(clear)
        expand.add_row(clear_row)
        body.append(group)
        self.warning = Gtk.Label(xalign=0, wrap=True, css_classes=["caption"])
        body.append(self.warning)
        body.append(Gtk.Label(label="Quiet reminders. Local data. Your pace.", wrap=True,
                              css_classes=["caption"]))
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self.key)
        self.add_controller(key)
        self.paused = False
        self.refresh()
        self.timer = GLib.timeout_add_seconds(5, self.refresh)
        self.connect("close-request", self.closed)

    def key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def closed(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        return False

    def changed(self, *_):
        if self.loaded:
            self.dirty = True
            self.apply.set_sensitive(self.connected)

    def message(self, text):
        self.toast.add_toast(Adw.Toast(title=text))

    def start_service(self, *_):
        try:
            subprocess.run(["systemctl", "--user", "start", "myos-hydration.service"],
                           check=True, capture_output=True, timeout=8)
        except (OSError, subprocess.SubprocessError):
            self.message("Could not start reminders. Check the Hydration guide for recovery steps.")
        self.refresh()

    def act(self, action, message=None):
        try:
            request({"action": action})
            if message:
                self.message(message)
        except Exception as error:
            self.message(str(error))
        self.refresh()

    def clear_history(self, *_):
        # AlertDialog, not the deprecated MessageDialog: that one left Tab stuck in the panel after closing.
        dialog = Adw.AlertDialog(heading="Clear water-break history?",
            body="This removes confirmed entries from this laptop.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear history")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda d, response: self.act("clear") if response == "clear" else None)
        dialog.present(self)

    def set_startup(self, switch, state):
        try:
            result = request({"action": "startup", "enabled": state})
            switch.set_state(result["autostart"])
        except Exception as error:
            switch.set_state(not state)
            switch.set_active(not state)
            self.message(str(error))
        return True

    def save(self, *_):
        try:
            request({"action": "settings", "settings": dict(interval=int(self.interval.get_value()),
                idle=int(self.idle.get_value()), start=self.start.get_text().strip(), end=self.end.get_text().strip(),
                fullscreen=self.fullscreen.get_active(), calls=self.calls.get_active())})
            self.dirty = False
            self.message("Settings saved. A fresh interval starts now.")
        except Exception as error:
            self.message(str(error))
        self.refresh()

    def refresh(self):
        try:
            status = request({"action": "status"})
            self.connected = True
            self.heading.set_label(status["title"])
            self.reason.set_label(status["reason"])
            self.today.set_subtitle(str(status["today"]))
            self.last.set_subtitle(datetime.fromtimestamp(status["last"]).strftime("%I:%M %p · %d %b").lstrip("0")
                                   if status["last"] else "No breaks recorded yet")
            self.undo.set_sensitive(status["undo"])
            self.paused = status["paused"]
            self.pause.set_label("Resume reminders" if self.paused else "Pause today")
            self.warning.set_label(status.get("warning", ""))
            if not self.loaded:
                cfg = status["settings"]
                self.interval.set_value(cfg["interval"])
                self.idle.set_value(cfg["idle"])
                self.start.set_text(cfg["start"])
                self.end.set_text(cfg["end"])
                self.fullscreen.set_active(cfg["fullscreen"])
                self.calls.set_active(cfg["calls"])
                self.loaded = True
        except Exception:
            self.connected = False
            self.heading.set_label("Reminder service is offline")
            self.reason.set_label("Your history is saved. Start reminders to continue.")
            self.undo.set_sensitive(False)
        for widget in (self.log, self.snooze, self.pause, self.startup):
            widget.set_sensitive(self.connected)
        self.apply.set_sensitive(self.connected and self.dirty)
        self.recover.set_visible(not self.connected)
        return True


def run():
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
    app = Adw.Application(application_id="org.myos.Hydration.Panel", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
    def activate(app):
        window = app.get_active_window()
        if not window:
            window = Panel(app)
        window.present()
    app.connect("activate", activate)
    app.run([])
