#!/usr/bin/env python3
"""GNOME app grid and clipboard shortcuts, preserving prior settings for rollback."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

HOME = Path.home()
UUID = "clipboard-indicator@tudmotu.com"
EXTENSION = HOME / ".local/share/gnome-shell/extensions" / UUID
BACKUP = HOME / ".config/setup-snapshots/gnome-workflow-before.json"
CUSTOM = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/terminal/"
KEYS = [
    ("org.gnome.desktop.wm.keybindings", "switch-input-source"),
    ("org.gnome.desktop.wm.keybindings", "switch-input-source-backward"),
    ("org.gnome.shell.keybindings", "toggle-application-view"),
    ("org.gnome.shell.keybindings", "toggle-message-tray"),
    ("org.gnome.shell.keybindings", "show-screenshot-ui"),
    ("org.gnome.shell", "enabled-extensions"),
    ("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"),
]


def gget(schema, key, schema_dir=None):
    cmd = ["gsettings"]
    if schema_dir:
        cmd += ["--schemadir", str(schema_dir)]
    return subprocess.check_output(cmd + ["get", schema, key], text=True).strip()


def gset(schema, key, value, schema_dir=None):
    cmd = ["gsettings"]
    if schema_dir:
        cmd += ["--schemadir", str(schema_dir)]
    subprocess.run(cmd + ["set", schema, key, value], check=True)


def values(schema, key):
    raw = gget(schema, key)
    if raw.startswith("@as []"):
        return []
    return ast.literal_eval(raw)


def update_list(schema, key, add=(), remove=()):
    old = values(schema, key)
    new = [item for item in old if item not in remove]
    for item in add:
        if item not in new:
            new.append(item)
    if new != old:
        gset(schema, key, str(new))
    return new


def install_clipboard_extension():
    if EXTENSION.exists():
        print("Clipboard extension already installed; preserved")
        return
    info_url = "https://extensions.gnome.org/extension-info/?uuid=clipboard-indicator%40tudmotu.com&shell_version=50"
    with urllib.request.urlopen(info_url, timeout=20) as response:
        data = json.load(response)
    url = urllib.parse.urljoin("https://extensions.gnome.org", data["download_url"])
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = response.read()
    import io
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("Unsafe extension archive paths")
        metadata = json.loads(archive.read("metadata.json"))
        if metadata["uuid"] != UUID or "50" not in metadata["shell-version"]:
            raise ValueError("Extension is not compatible with GNOME 50")
    cache = HOME / ".cache/setup-downloads"
    cache.mkdir(parents=True, exist_ok=True)
    bundle = cache / f"clipboard-indicator-v{data['version']}-gnome50.zip"
    bundle.write_bytes(payload)
    subprocess.run(["gnome-extensions", "install", str(bundle)], check=True)
    print(f"Installed Clipboard Indicator v{data['version']} for GNOME 50")


def main():
    if not BACKUP.exists():
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        BACKUP.write_text(json.dumps({f"{schema}:{key}": gget(schema, key) for schema, key in KEYS}, indent=2) + "\n")
        os.chmod(BACKUP, 0o600)
    install_clipboard_extension()
    update_list("org.gnome.desktop.wm.keybindings", "switch-input-source", remove=["<Super>space"])
    update_list("org.gnome.desktop.wm.keybindings", "switch-input-source-backward", remove=["<Shift><Super>space"])
    update_list("org.gnome.shell.keybindings", "toggle-application-view", add=["<Super>space"])
    update_list("org.gnome.shell.keybindings", "toggle-message-tray", remove=["<Super>v"])
    update_list("org.gnome.shell.keybindings", "show-screenshot-ui", add=["<Shift><Super>s"])
    update_list("org.gnome.shell", "enabled-extensions", add=[UUID])

    custom_schema = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:" + CUSTOM
    if CUSTOM not in values("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"):
        gset(custom_schema, "name", "Terminal")
        gset(custom_schema, "command", "ptyxis --new-window")
        gset(custom_schema, "binding", "<Super>Return")
        update_list("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings", add=[CUSTOM])

    schema_dir = EXTENSION / "schemas"
    if not schema_dir.is_dir():
        raise RuntimeError("Clipboard extension schema directory is missing")
    schema = "org.gnome.shell.extensions.clipboard-indicator"
    gset(schema, "toggle-menu", "['<Control>F9', '<Super>v']", schema_dir)
    gset(schema, "history-size", "30", schema_dir)
    gset(schema, "cache-only-favorites", "true", schema_dir)
    gset(schema, "cache-images", "false", schema_dir)
    gset(schema, "clear-on-boot", "true", schema_dir)
    print("GNOME shortcuts: Super+Space apps, Super+V clipboard, Super+Enter terminal, Super+Shift+S screenshot")
    print("Log out and back in once to load the new extension")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"GNOME workflow setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
