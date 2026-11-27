"""Pure hydration policy: no desktop access, wall-clock duration accounting or AI."""
import copy
import math
from datetime import datetime, timedelta

DEFAULTS = dict(interval=45, start="09:00", end="22:00", idle=180,
                fullscreen=True, calls=True)


def settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown settings")
    result = DEFAULTS | value
    for key, low, high in (("interval", 15, 180), ("idle", 30, 900)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    for key in ("start", "end"):
        try:
            t = datetime.strptime(result[key], "%H:%M")
            if t.strftime("%H:%M") != result[key]:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Hours must use HH:MM") from None
    if result["start"] == result["end"]:
        raise ValueError("Start and end must differ")
    if any(type(result[k]) is not bool for k in ("fullscreen", "calls")):
        raise ValueError("Context switches must be boolean")
    return result


def in_hours(now, cfg):
    t = now.strftime("%H:%M")
    a, b = cfg["start"], cfg["end"]
    return a <= t < b if a < b else t >= a or t < b


def next_start(now, cfg):
    # "Pause today" at 01:00 with 09:00 start resumes at 09:00 today, not tomorrow.
    day = now.date() if now.strftime("%H:%M") < cfg["start"] else now.date() + timedelta(days=1)
    return f"{day.isoformat()}T{cfg['start']}:00"


class Engine:
    def __init__(self, cfg=None, state=None):
        self.cfg = settings(cfg or {})
        self.s = dict(remaining=self.cfg["interval"] * 60, mode="accumulating",
                      paused_until=None, history=[], attempts=0, generation=0,
                      due_wait=0, grace=120, day="", identity="", notice=False)
        if state is not None:
            if not isinstance(state, dict):
                raise ValueError("Invalid state")
            for key in self.s:
                if key in state:
                    self.s[key] = state[key]
            for key in ("remaining", "due_wait", "grace", "attempts", "generation"):
                n = self.s[key]
                if type(n) not in (int, float) or not math.isfinite(n) or n < 0:
                    raise ValueError("Invalid state counters")
            if (not isinstance(self.s["history"], list)
                    or any(type(x) not in (float, int) or not math.isfinite(x)
                           for x in self.s["history"])):
                raise ValueError("Invalid drink history")
            if self.s["paused_until"] is not None:
                datetime.fromisoformat(self.s["paused_until"])
            if any(not isinstance(self.s[k], str) for k in ("day", "identity", "mode")):
                raise ValueError("Invalid session state")
        self.previous = None
        self.away_reset = False
        self.reason = "Starting activity observer"
        self.undo = None

    def reset(self):
        self.s.update(remaining=self.cfg["interval"] * 60, attempts=0,
                      due_wait=0, grace=120, mode="accumulating", notice=False)
        self.s["generation"] += 1

    def tick(self, dt, now, ctx, identity):
        """Return True exactly once per delivery; dt is monotonic active sampling time."""
        day = now.date().isoformat()
        if self.s["day"] != day or self.s["identity"] != identity:
            self.undo = None
            self.reset()
            self.s.update(day=day, identity=identity)
        self.s["history"] = [t for t in self.s["history"]
                             if t >= now.timestamp() - 30 * 86400]
        if self.s["paused_until"] and now.replace(tzinfo=None) >= datetime.fromisoformat(self.s["paused_until"]):
            self.s["paused_until"] = None
            self.reset()
        reason = ""
        if self.s["paused_until"]:
            reason = "Paused until " + self.s["paused_until"].replace("T", " ")[:16]
        elif not in_hours(now, self.cfg):
            reason = "Outside reminder hours"
        elif ctx.get("error"):
            reason = "Waiting: " + ctx["error"]
        elif not ctx.get("active_session", False) or ctx.get("locked", True):
            reason = "Screen locked or session inactive"
        elif ctx.get("dnd", True):
            reason = "Do Not Disturb is on"
        elif self.cfg["calls"] and ctx.get("call", False):
            reason = "Possible call: microphone in use"
        elif self.cfg["fullscreen"] and ctx.get("fullscreen", False):
            reason = "Fullscreen app is open"
        elif ctx.get("idle", True):
            reason = "Paused while you are away"
        if ctx.get("away") and not self.away_reset:
            self.reset()
        self.away_reset = bool(ctx.get("away"))
        if dt > 20 or dt < 0:
            dt = 0
            self.s["grace"] = 120
        prev = self.previous
        self.previous = (bool(reason), bool(ctx.get("idle", True)))
        self.reason = reason
        # Context suppresses interruptions, not active-time accumulation.
        can_count = (not self.s["paused_until"] and in_hours(now, self.cfg)
                     and not ctx.get("error") and ctx.get("active_session", False)
                     and not ctx.get("locked", True) and not ctx.get("idle", True))
        if can_count and prev is not None:
            self.s["remaining"] = max(0, self.s["remaining"] - dt)
        if reason:
            self.s["notice"] = False
            return False
        if prev is None or prev[0]:
            self.s["grace"] = 120
            if prev is not None and not self.s["remaining"]:
                self.s["due_wait"] = 300
            dt = 0
        self.s["grace"] = max(0, self.s["grace"] - dt)
        if self.s["remaining"] or self.s["grace"]:
            return False
        # Fresh due alerts wait for a natural return, or at most five active minutes.
        if self.s["mode"] == "accumulating":
            self.s["due_wait"] += dt
            if self.s["due_wait"] < 300:
                return False
        self.s["attempts"] += 1
        self.s["generation"] += 1
        self.s["notice"] = True
        self.s["remaining"] = (15 if self.s["attempts"] == 1 else 60) * 60
        self.s["mode"] = "backoff"
        return True

    def action(self, action, now, token=None):
        if token is not None and (token != self.s["generation"] or not self.s["notice"]):
            return False
        if action not in ("drank", "undo"):
            self.undo = None
        if action == "drank":
            self.undo = copy.deepcopy(self.s)
            self.s["history"].append(now.timestamp())
            self.reset()
        elif action == "undo":
            if self.undo is not None:
                generation = self.s["generation"] + 1
                self.s = self.undo
                self.s.update(generation=generation, notice=False, grace=120)
                self.undo = None
        elif action == "snooze":
            self.s.update(remaining=600, mode="snoozed", due_wait=0, notice=False, attempts=0)
            self.s["generation"] += 1
        elif action == "pause":
            self.s["paused_until"] = next_start(now, self.cfg)
            self.reset()
        elif action == "resume":
            self.s["paused_until"] = None
            self.reset()
        elif action == "clear":
            self.s["history"] = []
            self.undo = None
        else:
            raise ValueError("Unknown action")
        return True

    def status(self, now):
        history = self.s["history"]
        today = sum(datetime.fromtimestamp(t).date() == now.date() for t in history)
        mode = {"accumulating": "Running", "snoozed": "Snoozed",
                "backoff": "Waiting for your next break"}.get(self.s["mode"], "Running")
        return dict(title="Paused" if self.reason else mode,
                    reason=self.reason or ("Waiting for a quiet moment" if not self.s["remaining"]
                                           else f"About {math.ceil(self.s['remaining'] / 60)} active minutes until the next reminder"),
                    today=today, last=history[-1] if history else None,
                    paused=bool(self.s["paused_until"]), undo=self.undo is not None,
                    settings=self.cfg)
