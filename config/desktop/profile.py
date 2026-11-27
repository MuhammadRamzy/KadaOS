#!/usr/bin/env python3
"""profile: one switch for how the laptop should behave right now.

  profile                 show the current profile
  profile ai              AI work: performance power, fast screen, the local model loaded and kept warm
  profile battery         Battery: power saver, 60 Hz, the local model unloaded (frees ~6 GB of GPU/RAM)
  profile present         Presenting: Do Not Disturb on, no dimming / locking / sleeping
  profile auto            Back to automatic (power follows the charger, as usual)
  profile menu            pick one (Super+Ctrl+P)

A profile sticks until you choose another one: system-adapt doesn't override it when you plug in or unplug.
Everything it changes is put back by `profile auto` (it only undoes what it did, e.g. it won't turn off a
Do Not Disturb you turned on yourself).
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get("PROFILE_STATE") or HOME / ".local/state/myos/profile.json")
CONFIG = HOME / ".config/local-ai/config.json"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
PROFILES = {
    "ai":      {"label": "AI work", "icon": "applications-science-symbolic", "power": "performance", "hz": "ac", "model": "warm",
                "desc": "performance power · model kept loaded · full refresh rate"},
    "battery": {"label": "Battery", "icon": "battery-good-symbolic", "power": "power-saver", "hz": "battery", "model": "unload",
                "desc": "power saver · 60 Hz · local model unloaded"},
    "present": {"label": "Presenting", "icon": "video-display-symbolic", "dnd": True, "inhibit": True,
                "desc": "Do Not Disturb · no dimming, lock or sleep"},
    "auto":    {"label": "Automatic", "icon": "emblem-synchronizing-symbolic", "desc": "power follows the charger (default)"},
}
OK, FAIL, USAGE = 0, 1, 2


def run(*a, timeout=15):
    try: return subprocess.run(a, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return subprocess.CompletedProcess(a, 124, "", str(e))


def load():
    try: return json.loads(STATE.read_text())
    except (OSError, ValueError): return {"name": "auto"}


def save(st):
    STATE.parent.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st))


def model():
    try: return json.loads(CONFIG.read_text()).get("model", "")
    except (OSError, ValueError): return ""


def ollama(keep_alive):
    """Load (keep_alive -1 = stay loaded), unload (0) or reset ('5m') the configured model. Silent if Ollama isn't running."""
    m = model()
    if not m: return False
    body = json.dumps({"model": m, "keep_alive": keep_alive, "prompt": ""}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/generate", data=body, headers={"Content-Type": "application/json"}), timeout=120).read()
        return True
    except OSError: return False


def adapt_cfg():
    try: c = json.loads(CONFIG.read_text()).get("adapt", {})
    except (OSError, ValueError): c = {}
    return {"ac_profile": c.get("ac_profile", "balanced"), "battery_profile": c.get("battery_profile", "power-saver"),
            "ac_hz": c.get("ac_hz", 165), "battery_hz": c.get("battery_hz", 60)}


def on_ac():
    for p in Path("/sys/class/power_supply").glob("*"):
        try:
            if (p / "type").read_text().strip() == "Mains" and (p / "online").read_text().strip() == "1": return True
        except OSError: pass
    return False


def set_hz(hz):
    try: mon = next(m for m in json.loads(run("hyprctl", "monitors", "-j").stdout) if m["name"].startswith("eDP"))
    except (StopIteration, ValueError): return
    if round(mon["refreshRate"]) != hz:
        run("hyprctl", "keyword", "monitor", f"{mon['name']},{mon['width']}x{mon['height']}@{hz},{mon['x']}x{mon['y']},{mon['scale']}")


def dnd_on(): return run("swaync-client", "-D").stdout.strip() == "true"


def plan(name, st, ac):
    """What switching to `name` does, as a list of (step, args) — pure, so it can be tested. st = current state."""
    p, cfg, steps = PROFILES[name], adapt_cfg(), []
    if st.get("inhibit_pid"): steps.append(("release_inhibit", st["inhibit_pid"]))
    if st.get("set_dnd") and not p.get("dnd"): steps.append(("dnd", False))
    if st.get("model") == "warm" and p.get("model") != "warm": steps.append(("model", "5m"))   # back to Ollama's normal idle unload
    if name == "auto":
        steps += [("power", cfg["ac_profile"] if ac else cfg["battery_profile"]), ("hz", cfg["ac_hz"] if ac else cfg["battery_hz"])]
        return steps
    if p.get("power"): steps.append(("power", p["power"]))
    if p.get("hz"): steps.append(("hz", cfg["ac_hz"] if p["hz"] == "ac" else cfg["battery_hz"]))
    if p.get("model") == "warm": steps.append(("model", -1))
    if p.get("model") == "unload": steps.append(("model", 0))
    if p.get("dnd"): steps.append(("dnd", True))
    if p.get("inhibit"): steps.append(("inhibit", None))
    return steps


def apply(name):
    if name not in PROFILES: raise ValueError(f"profiles: {', '.join(PROFILES)}")
    st = load(); new = {"name": name, "since": time.time()}
    for step, arg in plan(name, st, on_ac()):
        if step == "power": run("powerprofilesctl", "set", arg)
        elif step == "hz": set_hz(arg)
        elif step == "model":
            loaded = ollama(arg)                          # loading can take ~10 s; fine for a deliberate switch
            if arg == -1 and loaded: new["model"] = "warm"
        elif step == "dnd":
            if arg and not dnd_on(): run("swaync-client", "-dn"); new["set_dnd"] = True
            elif not arg: run("swaync-client", "-df")
        elif step == "inhibit":
            p = subprocess.Popen(["systemd-inhibit", "--what=idle:sleep", "--who=profile", "--why=Presenting", "sleep", "infinity"],
                                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            new["inhibit_pid"] = p.pid
        elif step == "release_inhibit":
            try: os.kill(int(arg), 15)
            except (OSError, ValueError): pass
    save(new)
    run("pkill", "-RTMIN+9", "waybar")                    # the bar's power item shows the profile
    return new


def current():
    st = load(); return st.get("name", "auto")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"], ["help"]): print(__doc__.strip()); return OK
    if not argv:
        n = current(); print(f"{PROFILES[n]['label']}: {PROFILES[n]['desc']}"); return OK
    if argv[0] == "--json":
        n = current(); print(json.dumps({"name": n, **{k: PROFILES[n][k] for k in ("label", "desc")}})); return OK
    if argv[0] == "menu":
        lines = "\n".join(f"{p['label']}\t{p['icon']}\t{p['desc']}" for p in PROFILES.values())
        r = subprocess.run([str(HOME / ".config/hypr/scripts/menu.sh"), f"Profile (now: {PROFILES[current()]['label']})"],
                           input=lines, capture_output=True, text=True)
        pick = next((k for k, p in PROFILES.items() if r.stdout.strip().startswith(p["label"])), None)
        if not pick: return OK
        argv = [pick]
    name = {"present": "present", "presenting": "present", "presentation": "present", "ai": "ai", "battery": "battery",
            "auto": "auto", "off": "auto", "normal": "auto"}.get(argv[0])
    if not name: print(f"profiles: {', '.join(PROFILES)}", file=sys.stderr); return USAGE
    apply(name)
    run("notify-send", "-a", "KadaOS", "-i", PROFILES[name]["icon"], "-t", "2500", f"Profile: {PROFILES[name]['label']}", PROFILES[name]["desc"])
    print(f"✓ {PROFILES[name]['label']}: {PROFILES[name]['desc']}")
    return OK


if __name__ == "__main__":
    sys.exit(main())
