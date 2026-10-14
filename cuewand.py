#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuewand: run your slides from your phone.

Start it on the computer that shows the slides, scan the code with your phone,
and the phone becomes the remote: next/back, speaker notes, a preview of the
next slide, a talk timer with alerts, and a laser pointer you aim by touching
the slide picture.

  PowerPoint (Windows)  full control through PowerPoint itself
  anything else         Next/Back press the arrow keys on this computer

Run:  python cuewand.py             (or double-click "Start Cuewand.bat")
      python cuewand.py --demo      (fake deck, no PowerPoint needed)
      python cuewand.py --selftest  (prove, on this computer and the open deck,
                                     that every press lands exactly once)
"""
from __future__ import annotations

import argparse
import atexit
import collections
import ctypes
import hashlib
import importlib
import itertools
import json
import logging
import math
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = "Cuewand"
VERSION = "2.4"
HERE = os.path.dirname(os.path.abspath(__file__))
IS_WIN = sys.platform == "win32"
BOOT = secrets.token_hex(4)     # changes every time Cuewand starts
# The internet-link program: one known release, checked after download.
CLOUDFLARED_VERSION = "2026.10.0"
CLOUDFLARED_URL = ("https://github.com/cloudflare/cloudflared/releases/download/"
                   f"{CLOUDFLARED_VERSION}/cloudflared-windows-amd64.exe")
CLOUDFLARED_SHA256 = "86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c"

log = logging.getLogger("cuewand")


_HERE_WRITABLE = []     # found out once: is the Cuewand folder writable?


def data_dir() -> str:
    """Folder for the log and the internet-link helper: next to the script if
    we can write there, otherwise the per-user app data folder."""
    forced = os.environ.get("CUEWAND_DATA")
    if forced and os.path.isdir(forced):
        return forced
    if not _HERE_WRITABLE:
        try:
            probe = os.path.join(HERE, ".cuewand_write_test")
            with open(probe, "w") as f:
                f.write("")
            os.remove(probe)
            _HERE_WRITABLE.append(True)
        except OSError:
            _HERE_WRITABLE.append(False)
    if _HERE_WRITABLE[0]:
        return HERE
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = os.path.join(base, APP)
    os.makedirs(path, exist_ok=True)
    return path


_LOCK = []      # the open lock file, held for as long as Cuewand runs


def hold_lock() -> bool:
    """One Cuewand per data folder. A second copy, even one that would have
    moved to another port, finds the lock taken. The operating system lets go
    of it when the process ends, however it ends."""
    if _LOCK:
        return True
    try:
        f = open(os.path.join(data_dir(), "cuewand.lock"), "a+")
    except OSError:
        return True     # no lock file possible: do not stop Cuewand for that
    try:
        if IS_WIN:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _LOCK.append(f)
    return True


def release_lock():
    while _LOCK:
        try:
            _LOCK.pop().close()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Shared state
# --------------------------------------------------------------------------

class TalkTimer:
    def __init__(self):
        self.dur = 15 * 60          # talk length, seconds
        self.marks = [300, 60]      # alert when this many seconds remain
        self.auto = True            # start on the first advance of the slide show
        self.running = False
        self.acc = 0.0
        self.t0 = 0.0

    def elapsed(self) -> float:
        return self.acc + ((time.monotonic() - self.t0) if self.running else 0.0)

    def started(self) -> bool:
        return self.running or self.acc > 0

    def start(self):
        if not self.running:
            self.t0 = time.monotonic()
            self.running = True

    def pause(self):
        if self.running:
            self.acc = self.elapsed()
            self.running = False

    def reset(self):
        self.running = False
        self.acc = 0.0

    def view(self) -> dict:
        return {"dur": self.dur, "marks": self.marks, "auto": self.auto,
                "running": self.running, "elapsed": round(self.elapsed(), 2)}

    # kept on disk so that restarting Cuewand does not lose the talk clock
    def dump(self) -> dict:
        return {"dur": self.dur, "marks": self.marks, "auto": self.auto,
                "running": self.running, "acc": round(self.elapsed(), 2),
                "wall": time.time()}

    def load(self, d: dict):
        try:
            self.dur = max(30, min(int(d["dur"]), 12 * 3600))
            self.marks = sorted({int(m) for m in d.get("marks", []) if 0 < int(m) < 12 * 3600},
                                reverse=True)
            self.auto = bool(d.get("auto", True))
            acc = float(d.get("acc", 0.0))
            gap = max(0.0, time.time() - float(d.get("wall", time.time())))
            # Closed for a moment mid-talk: the clock kept running. Closed for
            # longer than any restart takes: it waits where it was.
            carry_on = bool(d.get("running")) and gap <= RESTART_GAP
            if carry_on:
                acc += gap
            if 0 <= acc < 12 * 3600:
                self.acc = acc
                if carry_on:
                    self.start()
        except (KeyError, TypeError, ValueError, OverflowError):
            pass


EMPTY_SHOW = {
    "mode": "keys",      # "powerpoint" | "keys" | "demo"
    "show": "none",      # "running" | "ended" | "idle" | "none"
    "deck": "", "deckId": "", "slide": 0, "total": 0, "next": None,
    "click": 0, "clicks": 0, "clicksOk": False, "black": False, "notes": "",
    "aspect": 16 / 9,
    "link": "ok",        # "off": no PowerPoint connection on this computer.
                         # "blocked": PowerPoint is running but will not answer.
    "pic": False, "nextPic": False,   # is a picture of this / the next slide ready?
    "pics": [0, 0, 0],                # pictures ready, slides in the deck, given up on
    "auto": 0,           # seconds after which PowerPoint moves this slide on by itself
    "title": "",         # the slide's title, for the picture's description
    "nextCue": "",       # first line of the next slide's notes
    "sec": "",           # name of the PowerPoint section this slide is in
    "backup": False,     # a hidden slide, or one after the last shown slide (reached by a jump)
}

CLICK_MARK = re.compile(r"\[\s*click\s*\]", re.I)    # "[click]" in notes: what to say at each step


def first_line(text: str, limit: int = 140) -> str:
    line = (text or "").strip().split("\n", 1)[0].strip()
    line = CLICK_MARK.sub("", line).strip()
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "\u2026"


def is_backup(visible, n) -> bool:
    return bool(visible) and (n not in visible or n > max(visible))


def section_of(sections, n) -> str:
    for s in sections or ():
        if s["first"] <= n <= s["last"]:
            return s["name"]
    return ""


def clean_name(name) -> str:
    """A phone's name as its owner typed it: short, printable, one line."""
    text = "".join(ch for ch in str(name or "") if ch.isprintable())
    return " ".join(text.split())[:32]

PRESS_TIMEOUT = 4.0      # s. How long a phone waits for PowerPoint to take one press
PHONE_GONE = 8.0         # s. A phone not heard from for this long counts as gone
UNDO_FOR = 15.0          # s. How long a reset clock or rehearsal start can be undone
YOUNG = 2.0              # s. A slide this new may still be appearing (transition, animation)
SETTLE_MAX = 2.0         # s. The longest a press is held back for a slide to finish appearing
RESTART_GAP = 15 * 60    # s. A clock that was running carries on across a restart this short
RESUME_WITHIN = 10.0     # s. A slide show back this soon after ending only blinked


class PressPending(Exception):
    """The press has reached PowerPoint and is still being carried out."""


class BadRequest(Exception):
    """The phone (or someone else) sent something that makes no sense."""


class _KeepLast(Exception):
    """One odd answer from PowerPoint: keep showing the last known state."""


class Hub:
    """Latest slide-show snapshot plus the timer, with a version number that
    phones long-poll against."""

    def __init__(self):
        self.cond = threading.Condition()
        self.version = 1
        self.show = dict(EMPTY_SHOW)
        self.timer = TalkTimer()
        self.clients: dict[str, float] = {}
        self.last_press = None  # {"id", "result"} of the press that finished last
        self.recent = collections.deque(maxlen=12)   # and of the few before it (several phones)
        self.on_change = None   # (old, new), called with the lock held
        self.extra = None       # (outgoing snapshot), called with the lock held
        self.on_press = None    # (press id, result): a press result corrected later

    def publish(self, snap: dict):
        with self.cond:
            if snap != self.show:
                if self.on_change:
                    self.on_change(self.show, snap)
                self.show = snap
                self.version += 1
                self.cond.notify_all()

    def bump(self):
        with self.cond:
            self.version += 1
            self.cond.notify_all()

    def note_press(self, pid: str, result: str):
        """A press the phone was already told about turned out otherwise: PowerPoint
        took it, but used it to finish what was on the screen and did not move."""
        if not pid:
            return
        with self.cond:
            for p in self.recent:
                if p.get("id") == pid:
                    p["result"] = result
            if self.on_press:
                self.on_press(pid, result)
            self.version += 1
            self.cond.notify_all()

    def _snapshot(self) -> dict:
        d = dict(self.show)
        d["v"] = self.version
        d["boot"] = BOOT
        d["timer"] = self.timer.view()
        d["lastPress"] = self.last_press
        d["presses"] = list(self.recent)
        if self.extra:
            self.extra(d)
        return d

    def snapshot(self) -> dict:
        with self.cond:
            return self._snapshot()

    def wait(self, since: int, timeout: float) -> dict:
        with self.cond:
            self.cond.wait_for(lambda: self.version != since, timeout)
            return self._snapshot()

    def seen(self, cid: str, name: str = "") -> bool:
        """Note that this phone is alive (and what its owner calls it). True the
        first time we hear from it."""
        if not cid:
            return False
        cid = cid[:16]
        old = self.clients.get(cid)
        new = old is None or old["t"] <= 0
        name = clean_name(name) or (old or {}).get("name", "")
        self.clients[cid] = {"t": time.monotonic(), "name": name}  # back again: no longer 'left'
        if old is not None and old.get("name") != name:
            with self.cond:
                self.version += 1
                self.cond.notify_all()
        return new

    def gone(self, cid: str):
        """The phone closed its page."""
        c = self.clients.get(cid[:16])
        if c:
            c["t"], c["left"] = 0.0, time.monotonic()
            with self.cond:
                self.version += 1
                self.cond.notify_all()

    def here(self, cid: str) -> bool:
        c = self.clients.get(cid)
        return bool(c) and time.monotonic() - c["t"] < PHONE_GONE

    def phones(self) -> list:
        """Phones seen in the last ten minutes, those still here first. A phone
        not heard from, or that closed its page, ten minutes ago is forgotten."""
        now = time.monotonic()
        old = lambda c: (0 < c["t"] < now - 600) or (c["t"] <= 0 and c.get("left", now) < now - 600)
        items = list(self.clients.items())      # phones check in from other threads
        for k, c in items:
            if old(c):
                self.clients.pop(k, None)
        rows = [{"cid": k, "name": c["name"], "here": now - c["t"] < PHONE_GONE}
                for k, c in items if not old(c)]
        return sorted(rows, key=lambda r: not r["here"])

    def client_count(self) -> int:
        return sum(1 for p in self.phones() if p["here"])


class Pace:
    """Time spent on each slide in the current timed run, plus one saved
    rehearsal per deck. Every method expects the hub lock to be held."""

    def __init__(self, timer: TalkTimer, path: str):
        self.timer = timer
        self.path = path
        self.spent: dict[int, float] = {}
        self.cur = None             # slide that is accruing time right now
        self.mark = 0.0             # timer reading at the last accounting
        self.rehearsing = False
        self.plans: dict[str, dict] = {}
        try:
            with open(path, encoding="utf-8") as f:
                self.plans = self._valid(json.load(f))
        except Exception as e:      # missing, damaged, or nested too deep to read
            if not isinstance(e, FileNotFoundError):
                log.warning("the saved rehearsals could not be read and are ignored: %s", type(e).__name__)

    @staticmethod
    def _valid(data) -> dict:
        """Keep only rehearsals that have the shape we wrote. A file edited by
        hand, or damaged, must never be able to break the phone."""
        good = {}
        if not isinstance(data, dict):
            return good
        for key, plan in data.items():
            try:
                spent = {str(int(k)): float(v) for k, v in plan["spent"].items()
                         if math.isfinite(float(v)) and float(v) >= 0}
                total = float(plan["total"])
                if spent and math.isfinite(total) and total > 0:
                    good[str(key)] = {"deck": str(plan.get("deck", key)),
                                      "slides": int(plan["slides"]), "total": total,
                                      "spent": spent, "saved": str(plan.get("saved", ""))}
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                continue
        return good

    @staticmethod
    def key(deck: str) -> str:
        return (deck or "").strip().lower()

    def account(self, slide):
        """Credit the time since the last call to the slide that was showing."""
        t = self.timer.elapsed()
        if self.cur is not None and t > self.mark:
            self.spent[self.cur] = self.spent.get(self.cur, 0.0) + (t - self.mark)
        self.mark = t
        self.cur = slide

    def clear(self):
        self.spent = {}
        self.mark = self.timer.elapsed()

    def plan_for(self, snap: dict):
        return self.plans.get(self.key(snap.get("deck", "")))

    @staticmethod
    def _coverage(plan: dict, visible) -> tuple:
        """How many of the slides that will be shown were rehearsed."""
        timed = {int(k) for k, v in plan["spent"].items() if float(v) >= 0.5}
        shown = list(visible) if visible else list(range(1, int(plan["slides"]) + 1))
        return sum(1 for n in shown if n in timed), len(shown)

    def summary(self, snap: dict, visible=None):
        try:
            plan = self.plan_for(snap)
            if not plan:
                return None
            covered, shown = self._coverage(plan, visible)
            same = plan["slides"] == snap.get("total")
            return {"total": plan["total"], "slides": plan["slides"], "saved": plan["saved"],
                    "covered": covered, "shown": shown,
                    # usable for pace: same deck size, and most of it rehearsed
                    "match": bool(same and shown and covered >= 0.8 * shown),
                    "why": "" if same and covered >= 0.8 * shown
                           else ("size" if not same else "partial")}
        except Exception:
            return None

    def save(self, snap: dict) -> bool:
        spent = {str(k): round(v, 1) for k, v in sorted(self.spent.items()) if v >= 0.5}
        total = round(sum(float(v) for v in spent.values()), 1)
        if total < 5 or not snap.get("deck"):
            return False
        self.plans[self.key(snap["deck"])] = {
            "deck": snap["deck"], "slides": int(snap.get("total", 0)), "total": total,
            "spent": spent, "saved": time.strftime("%d %b %Y, %H:%M")}
        return self._write()

    def forget(self, snap: dict):
        if self.plans.pop(self.key(snap.get("deck", "")), None) is not None:
            self._write()

    def _write(self) -> bool:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.plans, f, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            log.warning("could not save the rehearsal: %s", e)
            return False

    def window(self, snap: dict, visible):
        """When, on the talk clock, the current slide should start and end.
        From the rehearsal (stretched to the talk length) if there is a usable
        one for this deck, otherwise equal time for every slide that is not
        hidden."""
        try:
            if snap.get("show") != "running" or self.rehearsing:
                return None
            slide, total, dur = snap["slide"], snap["total"], self.timer.dur
            plan = self.plan_for(snap)
            info = self.summary(snap, visible)
            if plan and info and info["match"]:
                sp = {int(k): float(v) for k, v in plan["spent"].items()}
                scale = dur / float(plan["total"])
                lo = sum(v for k, v in sp.items() if k < slide) * scale
                return {"lo": round(lo, 1), "hi": round(lo + sp.get(slide, 0.0) * scale, 1),
                        "basis": "rehearsal"}
            vis = visible or list(range(1, total + 1))
            n = len(vis) or 1
            before = sum(1 for v in vis if v < slide)
            width = dur / n if slide in vis else 0.0
            return {"lo": round(dur * before / n, 1),
                    "hi": round(dur * before / n + width, 1), "basis": "even"}
        except Exception:
            return None

    def section(self, snap: dict, sections, visible):
        """Where the presenter is in the current PowerPoint section, and, from a
        usable rehearsal, when on the talk clock that section should be over."""
        try:
            if snap.get("show") != "running" or not sections:
                return None
            n = snap["slide"]
            sec = next((s for s in sections if s["first"] <= n <= s["last"]), None)
            if sec is None:
                return None
            vis = [v for v in (visible or range(1, snap["total"] + 1))
                   if sec["first"] <= v <= sec["last"]]
            out = {"name": sec["name"], "i": sections.index(sec) + 1, "of": len(sections),
                   "pos": vis.index(n) + 1 if n in vis else None, "size": len(vis),
                   "first": sec["first"], "last": sec["last"], "end": None, "start": None}
            plan = self.plan_for(snap)
            info = self.summary(snap, visible)
            if plan and info and info["match"] and not self.rehearsing:
                sp = {int(k): float(v) for k, v in plan["spent"].items()}
                scale = self.timer.dur / float(plan["total"])
                out["start"] = round(sum(v for k, v in sp.items() if k < sec["first"]) * scale, 1)
                out["end"] = round(sum(v for k, v in sp.items() if k <= sec["last"]) * scale, 1)
            return out
        except Exception:
            return None

    # kept on disk so that restarting Cuewand does not lose the per-slide times
    def dump(self) -> dict:
        self.account(self.cur)      # credit the slide on screen up to this moment
        return {"spent": {str(k): round(v, 2) for k, v in self.spent.items()},
                "rehearsing": self.rehearsing, "cur": self.cur, "mark": round(self.mark, 2)}

    def load(self, d: dict):
        try:
            self.spent = {int(k): float(v) for k, v in d.get("spent", {}).items()
                          if math.isfinite(float(v)) and float(v) >= 0}
            self.rehearsing = bool(d.get("rehearsing"))
            self.mark = self.timer.elapsed()
            if self.timer.running and d.get("cur") is not None:
                # the time Cuewand was closed belongs to the slide that was showing
                self.cur, self.mark = int(d["cur"]), min(self.mark, float(d["mark"]))
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            self.spent, self.rehearsing, self.cur = {}, False, None


# --------------------------------------------------------------------------
# Demo backend (also used when not on Windows)
# --------------------------------------------------------------------------

DEMO_DECK = [
    # title, builds, hidden, notes
    ("Ten minutes, one idea", 0, False,
     "Say the one idea in a single sentence before anything else.\n\n"
     "If people remember only that sentence, the talk worked."),
    ("Why most talks run over", 3, False,
     "Three reasons, one per click.\n[click]\n"
     "Too many slides. One point per slide, and cut the rest.\n[click]\n"
     "No rehearsal with a clock. You cannot feel ten minutes.\n[click]\n"
     "The introduction eats the results. Start with what you found."),
    ("One slide, one point", 0, False,
     "If a slide needs the word \u2018and\u2019 to describe it, split it."),
    ("Show the result first", 2, False,
     "Result, then method. The audience listens to the method differently "
     "once they know where it lands."),
    ("Numbers people can repeat", 0, False,
     "Round hard. \u2018About a third\u2019 survives the coffee break. \u201834.7%\u2019 does not."),
    ("The slide you skip", 0, True,
     "Hidden slide. Keep it for questions."),
    ("The last minute", 0, False,
     "When the phone buzzes at one minute, go straight to the closing slide.\n\n"
     "Repeat the one idea. Stop."),
    ("Questions", 0, False, ""),
]
DEMO_SECTIONS = [("Opening", 1, 2), ("The idea", 3, 5), ("Closing", 6, 8)]
DEMO_BODY = {
    1: "A talk about giving talks", 2: "Too many slides. No rehearsal. Long introductions.",
    3: "One point per slide", 4: "Result first, then method", 5: "About a third, not 34.7%",
    6: "Backup: the numbers behind the third", 7: "Repeat the one idea", 8: "Thank you",
}
DEMO_COLORS = ["#243B55", "#3B2F4A", "#1F4D46", "#4A3A22", "#2D3F5E",
               "#3A3A3A", "#4B2A33", "#22424F"]


class DemoBackend:
    name = "demo"

    def __init__(self, hub: Hub):
        self.hub = hub
        self.lock = threading.Lock()
        self.running = False
        self.ended = False
        self.slide = 1
        self.click = 0
        self.black = False
        self.gen = 1
        self.last_laser = None
        self.visible = [i + 1 for i, d in enumerate(DEMO_DECK) if not d[2]]
        self.sections = [{"name": nm, "first": a, "last": b} for nm, a, b in DEMO_SECTIONS]
        self.pic_times: dict = {}
        self.delay = 0.0            # seconds each press takes; for trying slow presses
        self.absorb = 0.0           # a press this soon after a move does nothing (a slide appearing)
        self.mislead = False        # the next press is answered "done", then turns out not to move
        self.moved = 0.0

    def start(self):
        self._publish()

    def close(self):
        pass

    def remake_pictures(self):
        pass

    def describe(self) -> str:
        return "Demo deck (no PowerPoint involved)"

    def _next_visible(self, i: int):
        for j in range(i + 1, len(DEMO_DECK) + 1):
            if not DEMO_DECK[j - 1][2]:
                return j
        return None

    def _prev_visible(self, i: int):
        for j in range(i - 1, 0, -1):
            if not DEMO_DECK[j - 1][2]:
                return j
        return None

    def _publish(self):
        n = len(DEMO_DECK)
        d = dict(EMPTY_SHOW)
        d.update(mode="demo", deck="Demo deck.pptx", total=n, deckId=str(self.gen),
                 pics=[n, n, 0])
        if not self.running:
            d.update(show="idle")
        elif self.ended:
            d.update(show="ended", slide=n)
        else:
            title, builds, _hidden, notes = DEMO_DECK[self.slide - 1]
            nxt = self._next_visible(self.slide)
            d.update(show="running", slide=self.slide, click=self.click,
                     clicks=builds, clicksOk=True, black=self.black, notes=notes,
                     next=nxt, pic=True, nextPic=nxt is not None, title=title,
                     nextCue=first_line(DEMO_DECK[nxt - 1][3]) if nxt else "",
                     sec=section_of(self.sections, self.slide), backup=is_backup(self.visible, self.slide))
        self.hub.publish(d)

    def command(self, name: str, args: dict, on_finish=None) -> str:
        """Carry out one press. Raises PressPending if it takes longer than a
        phone should wait; the press still finishes and reports through
        on_finish."""
        box: dict = {}
        done = threading.Event()

        def work():
            if self.delay:
                time.sleep(self.delay)
            try:
                box["result"] = self._do(name, args)
            except Exception as e:
                box["error"] = e
            done.set()
            if on_finish:
                on_finish(box.get("result"), box.get("error"))

        if self.delay:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()
        if not done.wait(PRESS_TIMEOUT):
            raise PressPending()
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _undo_guess(self, pid: str, real: dict):
        time.sleep(0.6)
        self.hub.publish(real)
        self.hub.note_press(pid, "absorbed")

    def _do(self, name: str, args: dict) -> str:
        with self.lock:
            total = len(DEMO_DECK)
            base = args.get("base") if isinstance(args.get("base"), dict) else None
            step = name in ("next", "prev") and self.running and not self.ended and not self.black
            if step and not (base is not None and WindowsBackend._left(base, (self.slide, self.click))):
                if self.absorb and time.monotonic() - self.moved < self.absorb:
                    return "absorbed"       # as PowerPoint does while a slide is still appearing
                if self.mislead:
                    # As if the phone were told at once and PowerPoint then did not move.
                    self.mislead = False
                    real = dict(self.hub.show)
                    keep = (self.slide, self.click, self.ended)
                    self._move(name)
                    self._publish()
                    self.slide, self.click, self.ended = keep
                    threading.Thread(target=self._undo_guess, args=(str(args.get("id") or ""), real),
                                     daemon=True).start()
                    return "done"
            if not self.running:
                if name != "start":
                    return "idle"
                self.running, self.ended, self.black = True, False, False
                self.slide, self.click = 1, 0
                self.gen += 1
            elif name in ("next", "prev") and base is not None and not self.ended and (
                    WindowsBackend._left(base, (self.slide, self.click))):
                self._publish()
                return "stale"      # the show already left the slide this press was made from
            elif name == "next":
                if self.ended:
                    pass
                elif self.black:
                    self.black = False
                else:
                    self._move(name)
            elif name == "prev":
                if self.ended:
                    self.ended = False
                elif self.black:
                    self.black = False
                else:
                    self._move(name)
            elif name == "goto":
                n = int(args.get("n", 0))
                if 1 <= n <= total:
                    self.slide, self.click = n, 0
                    self.ended = self.black = False
            elif name == "first":
                self.slide, self.click, self.ended, self.black = 1, 0, False, False
            elif name == "last":
                self.slide, self.click, self.ended, self.black = total, 0, False, False
            elif name == "black":
                if not self.ended:
                    self.black = not self.black
            elif name == "end":
                self.running = False
            self.moved = time.monotonic()
            self._publish()
            return "done"

    def _move(self, name: str):
        if name == "next":
            if self.click < DEMO_DECK[self.slide - 1][1]:
                self.click += 1
            else:
                nxt = self._next_visible(self.slide)
                if nxt is None:
                    self.ended = True
                else:
                    self.slide, self.click = nxt, 0
        elif self.click > 0:
            self.click -= 1
        else:
            prv = self._prev_visible(self.slide)
            if prv is not None:
                self.slide = prv
                self.click = DEMO_DECK[prv - 1][1]

    def laser(self, x: float, y: float, on: bool):
        self.last_laser = (round(x, 3), round(y, 3), on)

    def slide_image(self, n: int, width: int = 0):
        if not (1 <= n <= len(DEMO_DECK)):
            return None
        title = DEMO_DECK[n - 1][0]
        words, lines, cur = title.split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 > 18 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        y0 = 360 - (len(lines) - 1) * 62
        text = "".join(
            f'<text x="110" y="{y0 + i * 124}" font-size="104" font-weight="700" '
            f'fill="#fff" font-family="Segoe UI, Helvetica, Arial, sans-serif">'
            f'{ln.replace("&", "&amp;")}</text>' for i, ln in enumerate(lines))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
               f'<rect width="1280" height="720" fill="{DEMO_COLORS[(n - 1) % 8]}"/>'
               f'<rect x="110" y="96" width="120" height="10" fill="#F2B544"/>'
               f'{text}'
               f'<text x="1170" y="660" font-size="40" fill="#ffffff99" text-anchor="end" '
               f'font-family="Segoe UI, Helvetica, Arial, sans-serif">{n}</text></svg>')
        return svg.encode("utf-8"), "image/svg+xml"

    def outline(self):
        return [{"n": i + 1, "title": t, "hidden": h, "notes": bool(n), "pic": True,
                 "text": n[:2000], "body": DEMO_BODY.get(i + 1, ""), "steps": b,
                 "marks": len(CLICK_MARK.findall(n)), "sec": section_of(self.sections, i + 1)}
                for i, (t, b, h, n) in enumerate(DEMO_DECK)]


# --------------------------------------------------------------------------
# Windows backend: PowerPoint through COM, arrow keys for everything else
# --------------------------------------------------------------------------

class _Job:
    __slots__ = ("fn", "label", "done", "result", "err", "cancelled", "started",
                 "lock", "on_finish", "queued")

    def __init__(self, fn, label="", on_finish=None):
        self.fn = fn
        self.label = label
        self.done = threading.Event()
        self.result = None
        self.err = None
        self.cancelled = False
        self.started = False
        self.lock = threading.Lock()    # makes "start it" and "give up on it" exclusive
        self.on_finish = on_finish
        self.queued = time.monotonic()


PP_RUNNING, PP_BLACK, PP_WHITE, PP_DONE = 1, 3, 4, 5
MSO_PLACEHOLDER, PP_PLACEHOLDER_BODY = 14, 2
PP_BODY_LIKE = {6, 7}             # vertical body, object: where notes can also sit
# "busy, ask again" answers from PowerPoint: keep the last state, don't drop it
COM_BUSY = {-2147418111, -2147417846}  # RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 1, 2
VK = {"next": 0x27, "prev": 0x25, "black": 0x42, "first": 0x24, "last": 0x23,
      "end": 0x1B}
VK_EXTENDED = {0x27, 0x25, 0x24, 0x23}
PIC_WIDTH = 960           # one picture per slide; the phone scales it
PIC_TRIES = 3             # attempts before a slide's picture is given up on
PIC_RETRY_GAP = 2.0       # s before the second attempt; twice that before the third
SLOW_EXPORT = 0.6         # s. A picture slower than this, mid-show, stops further ones
CALM_AFTER_PRESS = 1.5    # s without a press before a picture may be made mid-show
PPT_EDITOR_CLASS = "PPTFrameClass"   # PowerPoint's editing window (not the slide show)


class WindowsBackend:
    """PowerPoint does one thing at a time, and making a picture of a slide can
    take it seconds (animated GIFs especially). So Cuewand makes the pictures
    while the deck is open and no slide show runs, and during a show it only
    asks PowerPoint for what the talk needs: where are we, next, back."""
    name = "windows"

    def __init__(self, hub: Hub):
        self.hub = hub
        self.q: queue.PriorityQueue = queue.PriorityQueue()
        self.seq = itertools.count()
        self.app = None
        self.ready = False
        self.com_ok = False
        self.com_error = ""
        self.next_try = 0.0
        self.last_poll = 0.0
        self.poll_gap = 0.2
        self.last_snap = dict(EMPTY_SHOW)
        self.sig = ""                   # deck + version that the caches belong to
        self.sig_deck = None            # (full name, slide count) behind it
        self.edits_by: dict = {}        # deck -> unsaved edits noticed so far
        self.saved_by: dict = {}        # deck -> was it saved when we last looked?
        self.notes_cache: dict = {}
        self.notes_tries: dict = {}
        self.outline_cache = None
        self.sections: list = []        # PowerPoint's sections: name, first and last slide
        self.body_cache: dict = {}      # slide -> the text on it, for searching
        self.visible = None             # slide numbers that are not hidden
        self.aspect = 16 / 9
        self.slide_rect = None          # screen pixels: (left, top, width, height)
        self.cache_dir = tempfile.mkdtemp(prefix="cuewand_pics_", dir=pictures_parent())
        self.pic_ready: set = set()
        self.pic_attempts: dict = {}
        self.pic_next: dict = {}        # slide -> earliest time for another attempt
        self.pic_times: dict = {}       # slide -> seconds its picture took
        self.pic_total = 0
        self.shelf: dict = {}           # pictures of decks that were open a moment ago
        self.remake = False
        self.live_export = True         # may pictures still be made during this show?
        self.cv = None                  # the running show's objects, reused between polls
        self.show_fail = 0
        self.auto_cache: dict = {}      # slide -> seconds of its own advance timer
        self.clicks_cache: dict = {}    # slide -> number of animation steps (PowerPoint, in the show)
        self.steps_cache: dict = {}     # slide -> click animations counted before the show
        self.entrance_cache: dict = {}  # slide -> seconds its transition takes
        self.settle: dict = {}          # (slide, step) -> seconds it was seen to need to appear
        self.moved_at = 0.0             # when the show last changed slide or step
        self.moved_to = None            # and to which (slide, step)
        self.guess = None               # a press shown on the phone before PowerPoint confirmed it
        self.stats = {"retried": collections.Counter(), "absorbed": collections.Counter(),
                      "slow": {}}       # for the self-test and the log
        self.doing = ""                 # what the background work is busy with
        self.roll = 0
        self.last_roll = 0.0
        self.last_press = 0.0
        self.last_export = 0.0
        self.pressing = False
        self.announced = False
        self.blocked = False
        self.blocked_since = 0.0
        self.open_decks = 0   # presentations open in PowerPoint, for the pairing page
        self.laser_want = False
        self.laser_time = 0.0
        self.laser_lock = threading.Lock()
        self._logged: dict[str, float] = {}
        self._seen = None
        self.user32 = ctypes.windll.user32
        from ctypes import wintypes
        self.wintypes = wintypes
        u = self.user32
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        try:
            u.GetForegroundWindow.restype = wintypes.HWND
            u.GetClassNameW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
            u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            u.FindWindowW.restype = wintypes.HWND
        except Exception:
            pass
        self.thread = threading.Thread(target=self._run, name="powerpoint", daemon=True)

    # ---- public (any thread) ----

    def start(self):
        self.thread.start()

    def close(self):
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def describe(self) -> str:
        if not self.ready:
            return "Looking for PowerPoint"
        if not self.com_ok:
            return ("No PowerPoint connection on this computer (" + (self.com_error or "pywin32 missing")
                    + "). Next and Back only press the arrow keys: no notes, pictures "
                    "or pace. Close Cuewand and start it again.")
        s = self.hub.snapshot()
        if s["show"] == "running":
            return f'PowerPoint: {s["deck"]}, slide {s["slide"]} of {s["total"]}'
        if s["show"] == "ended":
            return f'PowerPoint: {s["deck"]}, end of slide show'
        if s["show"] == "idle":
            got, total, failed = s["pics"]
            if total and got >= total:
                pics = "Slide pictures are ready."
            elif total and got + failed >= total:
                pics = f"Slide pictures: {got} of {total}; {failed} could not be made."
            else:
                pics = f"Preparing slide pictures: {got} of {total}. Wait for it before you start."
            many = (f' {self.open_decks} decks are open: Cuewand uses the one in front. To use another, '
                    'click its window in PowerPoint.') if self.open_decks > 1 else ''
            return f'Found your deck: {s["deck"]}. Slide show not started. {pics}{many}'
        if self.blocked:
            return ("PowerPoint is running but does not answer Cuewand. Open a presentation; if one "
                    "is open, click Enable Editing on its yellow bar, or click any other window once "
                    "and then PowerPoint again, or check that PowerPoint was not started as administrator.")
        return ("Open your deck in PowerPoint. Cuewand finds it by itself: there is no file to "
                "choose. Until then, Next and Back press the arrow keys.")

    def command(self, name: str, args: dict, on_finish=None) -> str:
        """Carry out one press. Raises TimeoutError if PowerPoint never started
        on it (nothing happened, safe to press again) and PressPending if it
        started and has not finished (it will still land; on_finish reports)."""
        self.last_press = time.monotonic()
        return self._call(0, lambda: self._command(name, args), timeout=PRESS_TIMEOUT,
                          label=name, on_finish=on_finish)

    def laser(self, x: float, y: float, on: bool):
        if on:
            self._move_cursor(x, y)
        with self.laser_lock:
            self.laser_time = time.monotonic()
            changed = on != self.laser_want
            self.laser_want = on
        if changed:
            self.q.put((0, next(self.seq), _Job(lambda: self._set_laser(on), "laser")))

    def slide_image(self, n: int, width: int = 0):
        """Never asks PowerPoint: a picture is either already made, or not there."""
        if n not in self.pic_ready:
            return None
        try:
            with open(self._pic_path(n), "rb") as f:
                return f.read(), "image/jpeg"
        except OSError:
            return None

    def outline(self):
        try:
            rows = self._call(1, self._outline, timeout=15, label="outline") or []
        except PressPending:
            raise TimeoutError("PowerPoint did not answer in time")
        return [dict(r, pic=r["n"] in self.pic_ready) for r in rows]

    def remake_pictures(self):
        self.remake = True

    # ---- worker thread: the only thread that talks to PowerPoint ----

    def _call(self, prio: int, fn, timeout: float = 8.0, label: str = "", on_finish=None):
        job = _Job(fn, label, on_finish)
        self.q.put((prio, next(self.seq), job))
        if not job.done.wait(timeout):
            with job.lock:
                if job.done.is_set():
                    pass
                elif job.started:
                    raise PressPending()        # it is with PowerPoint now and will land
                else:
                    job.cancelled = True        # never started: it will not be done later
                    raise TimeoutError("PowerPoint did not answer in time")
        if job.err is not None:
            raise job.err
        return job.result

    def _run(self):
        try:
            import pythoncom
            import pywintypes
            import win32com.client.dynamic
            pythoncom.CoInitialize()
            self._pythoncom, self._pywintypes = pythoncom, pywintypes
            self._dispatch = win32com.client.dynamic.Dispatch
            self.com_ok = True
        except Exception as e:  # pywin32 not installed, or COM unavailable
            self.com_error = f"{type(e).__name__}: {e}"
            log.warning("No PowerPoint connection: %s", self.com_error)
        self.ready = True
        while True:
            try:
                item = self.q.get(timeout=0.03 if self._quiet_pending() else 0.2)
            except queue.Empty:
                item = None
            if item is not None:
                job = item[2]
                with job.lock:
                    go = not job.cancelled
                    job.started = go
                if not go:
                    log.info("dropped a %s that PowerPoint could not start within %.0f s",
                             job.label or "request", PRESS_TIMEOUT)
                else:
                    t0 = time.monotonic()
                    waited = t0 - job.queued
                    if waited > 0.5:
                        log.info("slow: %s waited %.1f s for its turn (PowerPoint was busy "
                                 "answering Cuewand)", job.label or "request", waited)
                    try:
                        job.result = job.fn()
                    except Exception as e:
                        job.err = e
                        self._note(f"{job.label or 'request'} failed", e)
                    took = time.monotonic() - t0
                    if took > 0.5:
                        log.info("slow: %s took %.1f s", job.label or "request", took)
                with job.lock:
                    job.done.set()
                if go and job.on_finish:
                    try:
                        job.on_finish(job.result, job.err)
                    except Exception as e:
                        self._note("press report failed", e)
                if go and self.guess is not None and self.guess.get("new"):
                    self.guess["new"] = False
                    self._poll()        # the phone has its answer; now PowerPoint confirms it
            if time.monotonic() - self.last_poll >= self.poll_gap:
                self._poll()
            if item is None:
                t0 = time.monotonic()
                self.doing = ""
                self._quiet_work()
                took = time.monotonic() - t0
                if took > 0.5:
                    log.info("slow: background work (%s) took %.1f s", self.doing or "?", took)
            self._laser_watchdog()

    def _note(self, what: str, e: Exception):
        msg = f"{what}: {type(e).__name__}: {e}"
        try:
            frame = traceback.extract_tb(e.__traceback__)[-1]
            msg += f"  [line {frame.lineno}: {frame.line}]"
        except Exception:
            pass
        now = time.monotonic()
        if now - self._logged.get(msg, -1e9) > 60:
            self._logged[msg] = now
            log.info(msg)

    def _get_app(self):
        if not self.com_ok:
            return None
        if self.app is None:
            now = time.monotonic()
            if now < self.next_try:
                return None
            try:
                unk = self._pythoncom.GetActiveObject(
                    self._pywintypes.IID("PowerPoint.Application"))
                self.app = self._dispatch(
                    unk.QueryInterface(self._pythoncom.IID_IDispatch))
                self.blocked, self.blocked_since = False, 0.0
                if not self.announced:
                    self.announced = True
                    try:
                        log.info("Connected to PowerPoint %s", self.app.Version)
                    except Exception:
                        log.info("Connected to PowerPoint")
            except Exception:
                self.app = None
                self.next_try = now + 1.0
                self._check_blocked(now)
        return self.app

    def _check_blocked(self, now: float):
        """PowerPoint has a window on screen but gives us no way in: it has no
        presentation open, shows one in Protected View, or runs as administrator."""
        try:
            there = bool(self.user32.FindWindowW(PPT_EDITOR_CLASS, None))
        except Exception:
            there = False
        if not there:
            self.blocked, self.blocked_since = False, 0.0
        elif not self.blocked_since:
            self.blocked_since = now
        elif now - self.blocked_since > 3 and not self.blocked:
            self.blocked = True
            log.info("PowerPoint has a window open but does not answer Cuewand "
                     "(no presentation, Protected View, running as administrator, or "
                     "PowerPoint not yet reachable: clicking another window once makes it so)")

    def _drop_app(self, wait: float = 1.0):
        self.app = None
        self.next_try = time.monotonic() + wait

    def _show(self):
        """(app, window, view) of the running slide show, or None."""
        app = self._get_app()
        if app is None:
            return None
        if int(app.SlideShowWindows.Count) < 1:
            return None
        win = app.SlideShowWindows(1)
        return app, win, win.View

    @staticmethod
    def _idle_pres(app):
        try:
            return app.ActivePresentation
        except Exception:
            return app.Presentations(1)

    def _sync_deck(self, pres, total: int, running: bool):
        """Notes, outline and pictures are kept until the deck changes: another
        file, a different number of slides, a save, or an edit made while no
        slide show runs. Nothing is ever thrown away in the middle of a show."""
        full = str(pres.FullName)
        if running and self.sig and self.sig_deck == (full, total):
            return
        try:
            mtime = int(os.path.getmtime(full))
        except OSError:
            mtime = 0               # a deck that lives on OneDrive has no local file
        try:
            saved = bool(pres.Saved)
        except Exception:
            saved = True
        if self.saved_by.get(full) is True and not saved:
            self.edits_by[full] = self.edits_by.get(full, 0) + 1    # edited since we last looked
        self.saved_by[full] = saved
        raw = f"{full}|{total}|{mtime}|{self.edits_by.get(full, 0)}"
        sig = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:10]
        if sig == self.sig:
            return
        if self.sig:
            self.shelf[self.sig] = (self.pic_ready, self.pic_attempts, self.pic_times)
            while len(self.shelf) > 3:
                gone = next(iter(self.shelf))
                del self.shelf[gone]
                self._remove_pictures(gone + "_")
        self.sig, self.sig_deck = sig, (full, total)
        self.notes_cache.clear()
        self.notes_tries.clear()
        self.outline_cache = None
        self.sections = []
        self.body_cache.clear()
        self.visible = None
        self.auto_cache.clear()
        self.clicks_cache.clear()
        self.steps_cache.clear()
        self.entrance_cache.clear()
        self.settle.clear()
        self.guess = None
        self.pic_total = total
        kept = self.shelf.pop(sig, None)
        if kept:
            self.pic_ready, self.pic_attempts, self.pic_times = kept
            self.pic_next, self.live_export = {}, True
        else:
            self._forget_pictures()
        log.info("deck: %s, %d slides%s", re.split(r"[\\/]", full)[-1], total,
                 " (slide show already running)" if running
                 else "; its slide pictures are still here" if kept
                 else "; preparing slide pictures")

    def _forget_pictures(self):
        self.pic_ready, self.pic_attempts, self.pic_next = set(), {}, {}
        self.pic_times = {}
        self.live_export = True
        self._remove_pictures(self.sig + "_")

    def _remove_pictures(self, prefix: str):
        try:
            names = os.listdir(self.cache_dir)
        except OSError:
            return
        for name in names:
            if name.startswith(prefix):
                try:
                    os.remove(os.path.join(self.cache_dir, name))
                except OSError:
                    pass

    def _poll(self):
        t0 = time.monotonic()
        self.last_poll = t0
        try:
            snap = self._read()
        except _KeepLast:
            return
        except Exception as e:
            if getattr(e, "hresult", None) in COM_BUSY:
                return  # PowerPoint is busy (a dialog is open): keep last state
            self._note("lost PowerPoint", e)
            self._drop_app()
            self.announced = False
            snap = dict(EMPTY_SHOW)
        took = time.monotonic() - t0
        self.poll_gap = min(2.0, max(0.2, took * 4))   # a slow PowerPoint is asked less often
        self.last_poll = time.monotonic()
        if took > 0.5:
            log.info("slow: PowerPoint took %.1f s to say where it is (%s, slide %s)",
                     took, snap["show"], snap["slide"])
            if snap["show"] == "running" and took > 1.0:
                slow = self.stats["slow"]
                slow[snap["slide"]] = max(slow.get(snap["slide"], 0.0), took)
        if snap["show"] not in ("running", "ended"):
            self.slide_rect = None
        seen = (snap["show"], snap["deck"], snap["total"], snap["link"])
        if seen != self._seen:
            self._seen = seen
            log.info("PowerPoint: %s%s", snap["show"],
                     f', {snap["deck"]}, {snap["total"]} slides' if snap["deck"] else "")
        old = self.last_snap
        if old["show"] in ("running", "ended") and snap["show"] == "idle":
            missed = [n for n in self.pic_attempts if n not in self.pic_ready]
            if missed:      # the show is over: try the pictures that failed once more
                for n in missed:
                    del self.pic_attempts[n]
                self.pic_next = {}
                self.live_export = True
        guessed = self.guess is not None
        if guessed:
            self._check_guess(self._pos_of(snap))
        elif self._pos_of(snap) != self._pos_of(old):
            self.moved_at, self.moved_to = time.monotonic(), self._pos_of(snap)
        if (snap["show"] == old["show"] == "running" and snap["slide"] != old["slide"]
                and not self.pressing and not guessed):
            log.info("slide %s -> %s without a press from Cuewand (keyboard, clicker, "
                     "or the slide's own timer)", old["slide"], snap["slide"])
        self.last_snap = snap
        self.hub.publish(snap)

    def _read(self) -> dict:
        snap = dict(EMPTY_SHOW)
        if not self.com_ok:
            snap["link"] = "off"
        app = self._get_app()
        if app is None:
            if self.blocked:
                snap["link"] = "blocked"
            return snap
        if int(app.SlideShowWindows.Count) >= 1:
            for fresh in (False, True):
                try:
                    if fresh:
                        self.cv = None      # the remembered objects went stale: look again
                    self._read_show(app, snap)
                    self.show_fail = 0
                    return snap
                except Exception as e:
                    if getattr(e, "hresult", None) in COM_BUSY:
                        raise
                    if fresh or self.cv is None:
                        self.show_fail += 1
                        if self.show_fail < 2 and self.last_snap["show"] in ("running", "ended"):
                            raise _KeepLast()   # one odd answer is not the end of the show
                        # The window is still listed while the show closes: treat as closed.
                        self._note("slide show is closing", e)
                        break
            snap = dict(EMPTY_SHOW)
        self.cv = None
        self.show_fail = 0
        self.open_decks = int(app.Presentations.Count)
        if self.open_decks >= 1:
            pres = self._idle_pres(app)
            total = int(pres.Slides.Count)
            self._read_aspect(pres)
            self._sync_deck(pres, total, False)
            snap.update(show="idle", deck=str(pres.Name), total=total, deckId=self.sig,
                        pics=self._pics())
        else:
            # Nothing open: let go of PowerPoint so it can close completely.
            self._drop_app(2.0)
        return snap

    def _read_aspect(self, pres):
        try:
            setup = pres.PageSetup
            self.aspect = float(setup.SlideWidth) / float(setup.SlideHeight)
        except Exception:
            pass

    def _read_show(self, app, snap: dict):
        """Where the slide show is. The window, its view and the deck are looked
        up once and reused for a few seconds, so a normal poll is five short
        questions to PowerPoint and nothing else."""
        now = time.monotonic()
        cv = self.cv
        if cv is None or now - cv["at"] > 3.0:
            win = app.SlideShowWindows(1)
            view = win.View
            pres = win.Presentation
            total = int(pres.Slides.Count)
            self._read_aspect(pres)
            self._sync_deck(pres, total, True)
            try:
                timed = int(pres.SlideShowSettings.AdvanceMode) == 2   # "use timings"
            except Exception:
                timed = True
            try:
                self.slide_rect = self._window_slide_rect(int(win.HWND))
            except Exception:
                self.slide_rect = None
            cv = {"view": view, "pres": pres, "total": total, "name": str(pres.Name),
                  "timed": timed, "at": now}
        view, pres, total = cv["view"], cv["pres"], cv["total"]
        snap.update(mode="powerpoint", deck=cv["name"], total=total, deckId=self.sig,
                    aspect=round(self.aspect, 4), pics=self._pics())
        state = int(view.State)
        if state == PP_DONE:
            snap.update(show="ended", slide=total)
        else:
            slide = view.Slide
            idx = int(slide.SlideIndex)
            snap.update(show="running", slide=idx, black=state in (PP_BLACK, PP_WHITE))
            try:
                snap["click"] = int(view.GetClickIndex())
                if idx not in self.clicks_cache:
                    self.clicks_cache[idx] = int(view.GetClickCount())
                snap["clicks"] = self.clicks_cache[idx]
                snap["clicksOk"] = True
            except Exception:
                pass
            # Notes come from memory: they were read before the show. Reading a
            # notes page while a show runs can keep PowerPoint busy for seconds.
            snap["notes"] = self._notes_for(idx, slide)
            if idx not in self.auto_cache:
                self._read_timing(idx, slide)
            snap["auto"] = self.auto_cache[idx] if cv["timed"] else 0
            if self.visible is None:
                self.visible = [j for j in range(1, total + 1)
                                if not self._hidden(pres.Slides(j))]
            nxt = next((j for j in self.visible if j > idx), None)
            snap.update(next=nxt, pic=idx in self.pic_ready, nextPic=nxt in self.pic_ready,
                        **self._about(idx, nxt))
        self.cv = cv

    def _about(self, idx, nxt) -> dict:
        """Title, section and the next slide's first line, from what was read before the show."""
        rows = self.outline_cache or []
        title = rows[idx - 1]["title"] if 0 < idx <= len(rows) else ""
        return {"title": title, "sec": section_of(self.sections, idx), "backup": is_backup(self.visible, idx),
                "nextCue": first_line(self.notes_cache.get(nxt, "")) if nxt else ""}

    # ---- work for quiet moments: pictures, and keeping notes fresh ----

    def _pic_path(self, n: int) -> str:
        return os.path.join(self.cache_dir, f"{self.sig}_{n}.jpg")

    def _pics(self) -> list:
        failed = sum(1 for n in range(1, self.pic_total + 1)
                     if n not in self.pic_ready and self.pic_attempts.get(n, 0) >= PIC_TRIES)
        return [len(self.pic_ready), self.pic_total, failed]

    def _pics_wanted(self, first_try_only: bool = False) -> bool:
        limit = 1 if first_try_only else PIC_TRIES
        return any(n not in self.pic_ready and self.pic_attempts.get(n, 0) < limit
                   for n in range(1, self.pic_total + 1))

    def _next_missing(self, first, first_try_only: bool = False):
        limit = 1 if first_try_only else PIC_TRIES
        now = time.monotonic()
        for n in list(first) + list(range(1, self.pic_total + 1)):
            if (n and 1 <= n <= self.pic_total and n not in self.pic_ready
                    and self.pic_attempts.get(n, 0) < limit and now >= self.pic_next.get(n, 0)):
                return n
        return None

    def _quiet_pending(self) -> bool:
        """Is there background work worth waking up quickly for?"""
        if not self.sig or self.app is None:
            return False
        show = self.last_snap["show"]
        if show == "idle":
            return self.remake or self._next_missing([]) is not None or self.outline_cache is None
        if show == "running":
            return self.live_export and self._pics_wanted(first_try_only=True)
        return False

    def _quiet_work(self):
        """Things done only when no press is waiting. While the deck is open and
        no show runs: every slide picture, then titles, notes and timings, then
        a walk through the deck to notice edits. During a show: nothing but a
        missing picture, in a calm moment, one at a time, and none at all once a
        single one has turned out to be slow. (Reading a notes page during a
        show kept PowerPoint busy for four seconds on a deck with large GIFs.)"""
        if not self.sig or self.app is None:
            return
        show, now = self.last_snap["show"], time.monotonic()
        try:
            if show == "idle":
                pres = self._idle_pres(self.app)
                if (str(pres.FullName), int(pres.Slides.Count)) != self.sig_deck:
                    return
                if self.remake:
                    self.remake = False
                    self._forget_pictures()
                    log.info("slide pictures: making them again, as asked")
                n = self._next_missing([])
                if n is not None:
                    self.doing = f"picture of slide {n}"
                    self._export_pic(pres, n)
                elif self.outline_cache is None:
                    self.doing = "titles, notes and timings"
                    self._build_outline(pres)     # ahead of the talk
                elif now - self.last_roll > 0.25:
                    self.doing = "looking for edits"
                    self._roll_refresh(pres)
            elif show == "running":
                if now - self.last_press < 0.4:
                    return
                if (not self.live_export or now - self.last_press < CALM_AFTER_PRESS
                        or now - self.last_export < 0.3):
                    return
                n = self._next_missing([self.last_snap["slide"], self.last_snap["next"]], True)
                found = self._show() if n is not None else None
                if found is None:
                    return
                self.doing = f"picture of slide {n}, during the show"
                took = self._export_pic(found[1].Presentation, n)
                if took > SLOW_EXPORT:
                    self.live_export = False
                    log.info("slide pictures paused for this slide show: slide %d took %.1f s. "
                             "They are made while the deck is open and no show runs.", n, took)
        except Exception as e:
            self._note("background work", e)

    def _export_pic(self, pres, n: int) -> float:
        self.pic_attempts[n] = self.pic_attempts.get(n, 0) + 1
        path = self._pic_path(n)
        t0 = time.monotonic()
        ok = False
        try:
            pres.Slides(n).Export(path, "JPG", PIC_WIDTH, int(round(PIC_WIDTH / self.aspect)))
            ok = os.path.exists(path)
        except Exception as e:
            self._note(f"slide {n} could not be exported (try {self.pic_attempts[n]})", e)
        took = time.monotonic() - t0
        self.last_export = time.monotonic()
        if ok:
            self.pic_ready.add(n)
            self.pic_times[n] = took
            log.info("slide picture %d of %d: %.2f s", n, self.pic_total, took)
        else:
            self.pic_next[n] = time.monotonic() + PIC_RETRY_GAP * self.pic_attempts[n]
        if not self._pics_wanted():
            got, total, failed = self._pics()
            log.info("slide pictures: %d of %d ready%s", got, total,
                     f", {failed} could not be made" if failed else "")
        return took

    def _roll_refresh(self, pres):
        """One slide per call, round and round: has its title, notes or hidden
        flag changed since we read it? Catches edits that are not saved yet."""
        self.last_roll = time.monotonic()
        total = self.pic_total
        if not total or not self.outline_cache or len(self.outline_cache) != total:
            return
        self.roll = self.roll % total + 1
        i = self.roll
        s = pres.Slides(i)
        text, _how, problems = self._read_notes(s)
        if problems and not text:
            return
        title, hidden = self._title(s), self._hidden(s)
        row = self.outline_cache[i - 1]
        if text != self.notes_cache.get(i, "") or title != row["title"] or hidden != row["hidden"]:
            self.notes_cache[i] = text
            row.update(title=title, hidden=hidden, notes=bool(text), text=text[:2000],
                       marks=len(CLICK_MARK.findall(text)))
            self.visible = [r["n"] for r in self.outline_cache if not r["hidden"]]
            log.info("slide %d was edited: its notes and title were read again", i)

    def _notes_for(self, idx: int, slide) -> str:
        """Speaker notes of one slide. A read that fails (PowerPoint busy, say)
        is tried again on later polls instead of being remembered as 'no
        notes'. What was found, and how, goes to cuewand.log."""
        if idx in self.notes_cache:
            return self.notes_cache[idx]
        text, how, problems = self._read_notes(slide)
        tries = self.notes_tries.get(idx, 0) + 1
        self.notes_tries[idx] = tries
        if text or not problems or tries >= 5:
            self.notes_cache[idx] = text
            log.info("notes, slide %d: %s%s", idx,
                     f"{len(text)} characters from the {how}" if text else "none found",
                     ("; problems: " + " | ".join(problems[:4])) if problems else "")
        return text

    @staticmethod
    def _clean(text) -> str:
        return (str(text).replace("\r\n", "\n").replace("\r", "\n")
                .replace("\x0b", "\n").strip())

    def _read_notes(self, slide):
        """Returns (text, where it came from, problems met on the way)."""
        problems = []
        try:
            shapes = slide.NotesPage.Shapes
            count = int(shapes.Count)
        except Exception as e:
            return "", "", [f"notes page: {e!r}"]
        found = []          # (placeholder type or None, text)
        for i in range(1, count + 1):
            try:
                shp = shapes(i)
                if not shp.HasTextFrame:
                    continue
                frame = shp.TextFrame
                if not frame.HasText:
                    continue
                text = self._clean(frame.TextRange.Text)
                if not text:
                    continue
                kind = None
                try:
                    if int(shp.Type) == MSO_PLACEHOLDER:
                        kind = int(shp.PlaceholderFormat.Type)
                except Exception:
                    kind = None
                found.append((kind, text))
            except Exception as e:
                problems.append(f"shape {i}: {e!r}")
        body = [t for k, t in found if k == PP_PLACEHOLDER_BODY]
        if body:
            return "\n".join(body), "notes placeholder", problems
        other = [t for k, t in found if k is None or k in PP_BODY_LIKE]
        if other:   # notes typed into a plain text box on the notes page
            return max(other, key=len), "notes page text", problems
        return "", "", problems

    # ---- presses ----

    def _command(self, name: str, args: dict) -> str:
        self.pressing = True
        try:
            tries = 0
            while True:
                try:
                    result = self._do_command(name, args) or "done"
                    break
                except Exception as e:
                    # PowerPoint says "busy, ask again": ask again for a second and a half
                    tries += 1
                    if getattr(e, "hresult", None) not in COM_BUSY or tries >= 10:
                        raise
                    time.sleep(0.15)
            if tries:
                log.info("PowerPoint was busy: asked %d times before it took %s", tries + 1, name)
            if self.guess is None or not self.guess.get("new"):
                self._poll()        # (a press shown early is confirmed right after the reply)
            return result
        finally:
            self.pressing = False

    @staticmethod
    def _pos_of(snap):
        return (snap["slide"], snap["click"]) if snap["show"] == "running" else None

    def _where(self, view):
        """(slide, step) of the show right now; None once it has ended or closed."""
        for _ in range(20):
            try:
                if int(view.State) == PP_DONE:
                    return None
                return self._position(view)
            except Exception as e:
                if getattr(e, "hresult", None) not in COM_BUSY:
                    return None
                time.sleep(0.15)
        return None

    def _steps_of(self, n):
        known = self.clicks_cache.get(n)
        return known if known is not None else self.steps_cache.get(n)

    def _predict(self, name: str, pos):
        """Where a Next or Back that PowerPoint has just taken puts the show,
        worked out from what is known about the deck, so the phone can be told
        at once. None when that is not certain. PowerPoint confirms it a moment
        later (on a slide with large GIFs, a few seconds later)."""
        last, cv = self.last_snap, self.cv
        if last["show"] != "running" or last["black"] or self.visible is None or cv is None:
            return None
        idx, click = pos
        clicks = self.clicks_cache.get(idx)
        if clicks is None:
            return None
        if name == "next":
            if click < clicks:
                to = (idx, click + 1)
            else:
                nxt = next((j for j in self.visible if j > idx), None)
                if nxt is None:
                    return None     # past the last slide: PowerPoint's own setting decides
                to = (nxt, 0)
        else:
            if click > 0:
                to = (idx, click - 1)
            else:
                prv = next((j for j in reversed(self.visible) if j < idx), None)
                if prv is None or self._steps_of(prv) != 0:
                    return None     # the start, or a slide that comes back built up
                to = (prv, 0)
        n = to[0]
        if n not in self.notes_cache:
            return None
        steps = self._steps_of(n) if n != idx else clicks
        nxt = next((j for j in self.visible if j > n), None)
        snap = dict(last)
        snap.update(slide=n, click=to[1], clicks=steps or 0, clicksOk=steps is not None,
                    notes=self.notes_cache[n], next=nxt, pic=n in self.pic_ready,
                    nextPic=nxt in self.pic_ready,
                    auto=self.auto_cache.get(n, 0) if cv["timed"] else 0, **self._about(n, nxt))
        return to, snap

    def _check_guess(self, real):
        """PowerPoint now says where the show is, after a press the phone was
        told about early. Usually that is where it was expected."""
        g, self.guess = self.guess, None
        if g is None:
            return
        took = time.monotonic() - g["at"]
        if real == g["to"]:
            if took > 1.0:
                log.info("press %s [%s]: PowerPoint confirmed slide %d step %d after %.1f s "
                         "(the phone was told at once)", g["name"], g["pid"][:6], real[0], real[1], took)
            return
        if real == g["from"]:
            self.moved_at, self.moved_to = g["moved"]
            self._absorbed(g["name"], g["from"], "after the phone was told it moved")
            self.hub.note_press(g["pid"], "absorbed")
            return
        self.moved_at, self.moved_to = time.monotonic(), real
        log.info("press %s [%s]: the show is at %s, not slide %d step %d as worked out; "
                 "the phone shows where it is", g["name"], g["pid"][:6],
                 f"slide {real[0]} step {real[1]}" if real else "no slide (ended or closed)",
                 g["to"][0], g["to"][1])

    def _absorbed(self, name, pos, how=""):
        age = time.monotonic() - self.moved_at if self.moved_to == pos else 0.0
        self.stats["absorbed"][pos[0]] += 1
        if 0 < age < YOUNG + SETTLE_MAX:
            self.settle[pos] = min(SETTLE_MAX, max(self.settle.get(pos, 0.0), age + 0.3))
        log.info("%s on slide %d step %d: PowerPoint took it but the show did not move "
                 "(the slide had come up %.1f s before)%s; the phone says to press again",
                 name, pos[0], pos[1], age, "; " + how if how else "")

    @staticmethod
    def _send(view, name):
        (view.Next if name == "next" else view.Previous)()

    def _careful(self, view, name: str, pos, young: bool) -> str:
        """After a Next or Back sent to a slide that had only just come up: did
        the show move? PowerPoint uses a press made while a slide is still
        appearing to finish that instead. Then the press is sent once more,
        and if that does not move the show either, the phone is told so."""
        after = self._where(view)
        if after == pos:
            time.sleep(0.25)
            after = self._where(view)
        if after != pos:
            self.moved_at, self.moved_to = time.monotonic(), after
            return "done"
        if name == "prev" and self.visible and pos == (self.visible[0], 0):
            return "done"           # at the start: there is nothing to go back to
        if young:
            age = time.monotonic() - self.moved_at
            self.stats["retried"][pos[0]] += 1
            self.settle[pos] = min(SETTLE_MAX, max(self.settle.get(pos, 0.0), age + 0.3))
            log.info("%s on slide %d step %d: PowerPoint used it to finish the slide "
                     "appearing (%.1f s after it came up); sent once more", name, pos[0], pos[1], age)
            time.sleep(0.2)
            self._send(view, name)
            after = self._where(view)
            if after == pos:
                time.sleep(0.25)
                after = self._where(view)
            if after != pos:
                self.moved_at, self.moved_to = time.monotonic(), after
                return "done"
        self._absorbed(name, pos)
        return "absorbed"

    @staticmethod
    def _position(view) -> tuple:
        idx = int(view.Slide.SlideIndex)
        try:
            click = int(view.GetClickIndex())
        except Exception:
            click = 0
        return idx, click

    @staticmethod
    def _left(base, position) -> bool:
        """Has the show already left the place this press was made from?
        The slide always counts; the step only when the phone knew it."""
        try:
            if int(base["slide"]) != position[0]:
                return True
            return base.get("click") is not None and int(base["click"]) != position[1]
        except (KeyError, TypeError, ValueError):
            return False

    def _do_command(self, name: str, args: dict) -> str:
        last = self.last_snap
        base = args.get("base") if isinstance(args.get("base"), dict) else None
        step = name in ("next", "prev")
        sent = False                # was PowerPoint already asked to move, on the short way?
        cv = self.cv
        if cv is not None and step and last["show"] == "running" and not last["black"]:
            # The common case: ask where the show is, then one request to move it.
            try:
                view = cv["view"]
                pos = self._position(view)
                if self.guess is not None:
                    self._check_guess(pos)
                if base is not None and self._left(base, pos):
                    return "stale"
                age = time.monotonic() - self.moved_at
                young = pos == self.moved_to and age < YOUNG
                if young:
                    # The slide may still be coming up. A press now would only
                    # finish that, so wait for it (its transition, or what an
                    # earlier press showed it needs).
                    need = self.settle.get(pos, 0.0)
                    if pos[1] == 0 and self.entrance_cache.get(pos[0]):
                        need = max(need, self.entrance_cache[pos[0]] + 0.15)
                    hold = min(need, SETTLE_MAX) - age
                    if hold > 0.02:
                        time.sleep(hold)
                sent = True
                self._send(view, name)
            except Exception as e:
                if getattr(e, "hresult", None) in COM_BUSY:
                    raise           # PowerPoint turned it down: nothing moved, ask again
                self._note(f"{name}: PowerPoint answered with an error", e)
                self.cv = None      # the remembered show is gone: take the long way
            else:
                guess = None if young else self._predict(name, pos)
                if guess is None:
                    return self._careful(view, name, pos, young)
                to, snap = guess
                self.guess = {"pid": str(args.get("id") or "")[:40], "name": name, "from": pos,
                              "to": to, "at": time.monotonic(), "new": True,
                              "moved": (self.moved_at, self.moved_to)}
                self.moved_at, self.moved_to = time.monotonic(), to
                self.last_snap = snap
                self.hub.publish(snap)
                return "done"
        show = None
        try:
            show = self._show()
        except Exception as e:
            if getattr(e, "hresult", None) in COM_BUSY:
                raise           # "busy, ask again": asked again, never answered with keys
            self._note("no slide show", e)
        if show is None:
            if name != "start" and last.get("show") == "running":
                # A show was running a moment ago and PowerPoint did not answer now.
                # Arrow keys could land in a dialog or another program: say busy.
                return "busy"
            return self._command_keys(name, args)
        _app, _win, view = show
        state = int(view.State)
        dark = state in (PP_BLACK, PP_WHITE)
        if step and state != PP_DONE and not dark and base is not None:
            # Also guards the long way: if the short way moved the show before it
            # failed, the show has left the base and nothing is done twice.
            if self._left(base, self._position(view)):
                if sent:
                    log.info("%s: PowerPoint moved the show and then reported an error; "
                             "it is not sent a second time", name)
                    return "done"
                return "stale"
        if name == "next":
            if state == PP_DONE:
                pass        # stay on the end screen; Exit is a separate button
            elif dark:
                view.State = PP_RUNNING
            else:
                view.Next()
        elif name == "prev":
            if dark:
                view.State = PP_RUNNING
            else:
                view.Previous()
        elif name == "goto":
            n = int(args.get("n", 0))
            if 1 <= n <= int(self.last_snap.get("total", 0)):
                view.GotoSlide(n)
        elif name == "first":
            view.First()
        elif name == "last":
            view.Last()
        elif name == "black":
            if state != PP_DONE:
                view.State = PP_RUNNING if dark else PP_BLACK
        elif name == "end":
            view.Exit()
            self.cv = None
        return "done"

    def _editor_in_front(self) -> bool:
        """Would a key press go to PowerPoint's editing window right now?
        (A running slide show has a window of another kind, and gets the keys.)"""
        try:
            buf = ctypes.create_unicode_buffer(64)
            self.user32.GetClassNameW(self.user32.GetForegroundWindow(), buf, 64)
            return buf.value == PPT_EDITOR_CLASS
        except Exception:
            return False

    def _command_keys(self, name: str, args: dict) -> str:
        if name == "start":
            app = self._get_app()
            if app is None or int(app.Presentations.Count) < 1:
                return "idle"
            pres = self._idle_pres(app)
            start_at = 1
            if args.get("from") == "current":
                try:
                    start_at = int(app.ActiveWindow.View.Slide.SlideIndex)
                except Exception:
                    start_at = 1
            win = pres.SlideShowSettings.Run()
            if start_at > 1:
                try:
                    win.View.GotoSlide(start_at)
                except Exception as e:
                    self._note("could not jump to the selected slide", e)
            return "done"
        vk = VK.get(name)
        if not vk:
            return "idle"
        if self._editor_in_front():
            # An arrow key here would move a shape or the text cursor in the deck.
            return "idle"
        flags = KEYEVENTF_EXTENDEDKEY if vk in VK_EXTENDED else 0
        self.user32.keybd_event(vk, 0, flags, 0)
        self.user32.keybd_event(vk, 0, flags | KEYEVENTF_KEYUP, 0)
        return "done"

    # ---- titles, hidden slides ----

    @staticmethod
    def _title(s) -> str:
        try:
            if s.Shapes.HasTitle:
                title = str(s.Shapes.Title.TextFrame.TextRange.Text)
                return " ".join(title.replace("\x0b", " ").split())[:120]
        except Exception:
            pass
        return ""

    @staticmethod
    def _hidden(s) -> bool:
        try:
            return bool(s.SlideShowTransition.Hidden)
        except Exception:
            return False

    def _outline(self):
        if self.outline_cache is None:
            found = self._show()
            if found is not None:
                # Cuewand started while a show runs. Opening every notes page now could
                # keep PowerPoint busy for seconds: titles and the notes already read
                # only. The full outline is made once the show ends.
                return self._build_outline(found[1].Presentation, light=True)
            elif self.app is not None and int(self.app.Presentations.Count) >= 1:
                pres = self._idle_pres(self.app)
            else:
                return []
            return self._build_outline(pres)
        return self.outline_cache

    def _read_timing(self, n: int, s):
        """A slide's own advance timer, and how long its transition takes."""
        auto, entrance = 0, 0.0
        try:
            tr = s.SlideShowTransition
            auto = round(float(tr.AdvanceTime), 1) if bool(tr.AdvanceOnTime) else 0
            if int(tr.EntryEffect) != 0:            # 0: no transition
                entrance = float(tr.Duration)
        except Exception:
            pass
        self.auto_cache[n] = auto
        self.entrance_cache[n] = max(0.0, min(entrance, SETTLE_MAX))

    @staticmethod
    def _count_steps(s):
        """Click animations on a slide, counted in its animation list (no show
        needed). PowerPoint's own count, read in the show, takes precedence."""
        try:
            seq = s.TimeLine.MainSequence
            return sum(1 for i in range(1, int(seq.Count) + 1)
                       if int(seq.Item(i).Timing.TriggerType) == 1)   # on click
        except Exception:
            return None

    def _read_sections(self, pres):
        """PowerPoint's sections (Home > Section), for pace per part of the talk."""
        out = []
        try:
            sp = pres.SectionProperties
            for i in range(1, int(sp.Count) + 1):
                first, count = int(sp.FirstSlide(i)), int(sp.SlidesCount(i))
                if count > 0:
                    out.append({"name": " ".join(str(sp.Name(i)).split())[:60] or f"Part {i}",
                                "first": first, "last": first + count - 1})
        except Exception:
            out = []
        # one section covering the whole deck says nothing
        self.sections = out if len(out) > 1 else []

    def _slide_text(self, s) -> str:
        """The words on a slide other than its title, for "Find a slide"."""
        parts = []
        try:
            shapes = s.Shapes
            for i in range(1, int(shapes.Count) + 1):
                try:
                    shp = shapes(i)
                    if not shp.HasTextFrame or not shp.TextFrame.HasText:
                        continue
                    if int(shp.Type) == MSO_PLACEHOLDER and int(shp.PlaceholderFormat.Type) in (1, 3):
                        continue                    # the title is searched already
                    parts.append(self._clean(shp.TextFrame.TextRange.Text))
                except Exception:
                    continue
        except Exception:
            pass
        return " ".join(" ".join(parts).split())[:1000]

    def _build_outline(self, pres, light: bool = False):
        out = []
        if not self.sections:
            self._read_sections(pres)
        for i in range(1, int(pres.Slides.Count) + 1):
            s = pres.Slides(i)
            notes = self.notes_cache.get(i, "") if light else self._notes_for(i, s)
            if not light:
                if i not in self.auto_cache:
                    self._read_timing(i, s)
                if i not in self.steps_cache:
                    steps = self._count_steps(s)
                    if steps is not None:
                        self.steps_cache[i] = steps
                if i not in self.body_cache:
                    self.body_cache[i] = self._slide_text(s)
            out.append({"n": i, "title": self._title(s), "hidden": self._hidden(s),
                        "notes": bool(notes), "text": notes[:2000], "body": self.body_cache.get(i, ""),
                        "steps": self._steps_of(i), "marks": len(CLICK_MARK.findall(notes)),
                        "sec": section_of(self.sections, i)})
        if self.visible is None:
            self.visible = [r["n"] for r in out if not r["hidden"]]
        if not light and all(row["n"] in self.notes_cache for row in out):
            self.outline_cache = out    # otherwise a notes read is still being retried
        return out

    # ---- laser: PowerPoint's own laser dot, steered by moving the cursor ----

    def _window_slide_rect(self, hwnd: int):
        wt = self.wintypes
        rc = wt.RECT()
        if not self.user32.GetClientRect(hwnd, ctypes.byref(rc)):
            return None
        pt = wt.POINT(0, 0)
        self.user32.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w <= 0 or h <= 0:
            return None
        if w / h > self.aspect:
            sh, sw = h, h * self.aspect
        else:
            sw, sh = w, w / self.aspect
        return (pt.x + (w - sw) / 2, pt.y + (h - sh) / 2, sw, sh)

    def _move_cursor(self, x: float, y: float):
        rect = self.slide_rect
        if rect is None:  # no PowerPoint show: the pad covers the main screen
            rect = (0, 0, self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1))
        left, top, w, h = rect
        self.user32.SetCursorPos(int(left + x * (w - 1)), int(top + y * (h - 1)))

    def _set_laser(self, on: bool):
        show = self._show()
        if show is not None:
            show[2].LaserPointerEnabled = bool(on)

    def _laser_watchdog(self):
        """Switch the laser off if the phone went quiet while it was on."""
        with self.laser_lock:
            stale = self.laser_want and time.monotonic() - self.laser_time > 2.5
            if stale:
                self.laser_want = False
        if stale:
            try:
                self._set_laser(False)
            except Exception as e:
                self._note("laser off failed", e)


# --------------------------------------------------------------------------
# Internet link (Cloudflare quick tunnel)
# --------------------------------------------------------------------------

_JOBS = []   # Windows job handles, kept open for as long as Cuewand runs


def _die_with_cuewand(proc):
    """Windows: tie a child program to this one, so that closing the Cuewand
    window can never leave the tunnel program running on its own."""
    if not IS_WIN:
        return
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.c_void_p, ctypes.c_uint32]
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_uint32),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic),
                        ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000      # kill on job close
        if job and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.AssignProcessToJobObject(job, int(proc._handle))
            _JOBS.append(job)
    except Exception as e:
        log.debug("could not tie the tunnel program to Cuewand: %s", e)


class Tunnel:
    # the public address of a quick tunnel; never Cloudflare's own api host
    URL_RE = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")

    def __init__(self, port: int):
        self.port = port
        self.status = "off"   # off | downloading | starting | on | error
        self.url = ""
        self.error = ""
        self.note = ""
        self.progress = 0.0
        self.answering = True     # did the public address reach us at the last check?
        self.why = ""             # why the last check failed
        self.proc = None
        self.lock = threading.Lock()

    def view(self) -> dict:
        return {"status": self.status, "url": self.url, "error": self.error,
                "note": self.note, "progress": round(self.progress, 3),
                "answering": self.answering, "have": bool(self._find_exe())}

    def restart(self):
        """Close the link and open a new one, with a new address."""
        self.stop()
        with self.lock:
            self.status, self.url, self.error, self.note = "off", "", "", ""
        self.start()

    def start(self):
        with self.lock:
            if self.status in ("downloading", "starting", "on"):
                return
            self.status, self.error, self.url, self.note = "starting", "", "", ""
        threading.Thread(target=self._run, name="tunnel", daemon=True).start()

    def stop(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def _fail(self, msg: str):
        log.warning("Internet link: %s", msg)
        self.status, self.error = "error", msg

    def _find_exe(self):
        names = ["cloudflared.exe", "cloudflared"] if IS_WIN else ["cloudflared"]
        for folder in (data_dir(), HERE):
            for name in names:
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    return p
        return shutil.which("cloudflared")

    def download(self) -> str:
        """Fetch the pinned tunnel program and check it is the file we expect."""
        if not IS_WIN:
            raise RuntimeError("cloudflared is not installed. Install it and try again.")
        self.status, self.progress = "downloading", 0.0
        dest = os.path.join(data_dir(), "cloudflared.exe")
        part = dest + ".part"
        digest = hashlib.sha256()
        req = urllib.request.Request(CLOUDFLARED_URL, headers={"User-Agent": APP})
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                if total:
                    self.progress = got / total
        if digest.hexdigest() != CLOUDFLARED_SHA256:
            try:
                os.remove(part)
            except OSError:
                pass
            raise RuntimeError("the downloaded file is not the one Cuewand expects")
        os.replace(part, dest)
        log.info("tunnel program %s downloaded and verified", CLOUDFLARED_VERSION)
        return dest

    def _run(self):
        try:
            exe = self._find_exe()
            if not exe:
                try:
                    exe = self.download()
                except Exception as e:
                    return self._fail(
                        f"Could not download the internet-link program ({e}). "
                        "You can install it yourself: open a Command Prompt and run "
                        "'winget install Cloudflare.cloudflared', then try again.")
            self.status = "starting"
            flags = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(
                [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", creationflags=flags)
            _die_with_cuewand(self.proc)
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        except Exception as e:
            self._fail(f"Could not start the internet link ({e}).")

    def _read(self, proc):
        last = ""
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            last = line
            log.debug("cloudflared: %s", line)
            if not self.url:
                m = self.URL_RE.search(line)
                if m:
                    self.url = m.group(0)
                    threading.Thread(target=self._confirm, daemon=True).start()
        if self.proc is proc:  # ended on its own, not because we stopped it
            self.url = ""
            self._fail("The internet link could not stay connected. Some networks block it; "
                       "your phone's hotspot usually works. Details: " + last[-180:])

    def _ping(self, url: str) -> bool:
        try:
            with urllib.request.urlopen(url + "/api/ping", timeout=6) as r:
                ok = r.status == 200 and b"cuewand" in r.read(200)
                self.why = "" if ok else f"unexpected answer (status {r.status})"
                return ok
        except Exception as e:
            self.why = f"{type(e).__name__}: {e}"
            return False

    def _confirm(self):
        """Wait until the public address actually reaches this program, then
        keep checking it for as long as the link is open."""
        url, deadline = self.url, time.monotonic() + 30
        time.sleep(2)
        confirmed = False
        while time.monotonic() < deadline and self.url == url:
            if self._ping(url):
                confirmed = True
                break
            time.sleep(2)
        if self.url != url or self.status != "starting":
            return
        self.status, self.answering = "on", confirmed
        if confirmed:
            log.info("Internet link ready: %s", url)
        else:
            log.warning("Internet link: address given but this computer cannot reach it (%s)",
                        self.why)
            self.note = ("Could not confirm the link from this computer. "
                         "Try it from your phone.")
        misses = 0
        while self.url == url and self.status == "on":
            time.sleep(10)
            if self.url != url or self.status != "on":
                return
            ok = self._ping(url)
            if ok != self.answering:
                log.info("Internet link %s", "is answering again" if ok
                         else f"stopped answering ({self.why})")
            self.answering = ok
            misses = 0 if ok else misses + 1
            if misses >= 3:     # half a minute of silence: this address is dead
                self.stop()
                self.url = ""
                self._fail("The internet link stopped answering. Turn it on again to "
                           "get a new link and a new code.")
                return


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packet is sent
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


def qr_svg(text: str) -> str:
    """The pairing code as a picture. The small library that draws it travels
    with Cuewand, so this needs no install and no internet."""
    try:
        try:
            import segno
        except ImportError:
            sys.path.insert(0, os.path.join(HERE, "_vendor"))
            import segno
        return segno.make(text, error="m").svg_inline(
            scale=6, border=2, dark="#10141C", light="#FFFFFF", omitsize=True)   # scales to its box
    except Exception as e:
        log.warning("could not draw a pairing code: %s", e)
        return ""


def new_pin() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


SESSION_HOURS = 12


class Context:
    """Everything the web side needs: who may connect, the presses in flight,
    the timer and pace, and what is remembered between runs."""

    def __init__(self, hub, backend, tunnel, port, fresh: bool = False, keep: bool = True):
        self.hub, self.backend, self.tunnel, self.port = hub, backend, tunnel, port
        self.keep = keep            # False: never touch the saved session (self-test)
        self._qr: dict[str, str] = {}
        self._outline = ("", [])
        self.pace = Pace(hub.timer, os.path.join(data_dir(), "cuewand_rehearsals.json"))
        self.session_path = os.path.join(data_dir(), "cuewand_session.json")
        self.presses: collections.OrderedDict = collections.OrderedDict()
        self.press_lock = threading.Lock()
        self.pin_fails: dict = {}       # address -> times of its recent wrong numbers
        self.pin_bad = 0
        self.dirty = False
        self.ended_at = 0.0             # when the clock was stopped by a show ending
        self.show_from = None           # slide the current show was first seen on
        self.holder = None              # the phone that has the slides; None: every phone presses
        self.undo = None                # what a reset clock or rehearsal start can go back to
        self.save_lock = threading.Lock()
        self.save_failed = False
        self._refused: dict[str, float] = {}
        saved = {} if fresh else self._load_session()
        self.restored = bool(saved)
        self.born = saved.get("born") or time.time()     # when these codes were made
        self.key = saved.get("key") or secrets.token_urlsafe(16)
        self.host_key = saved.get("host_key") or secrets.token_urlsafe(16)
        self.pin = saved.get("pin") or new_pin()
        if saved:
            hub.timer.load(saved.get("timer") or {})
            self.pace.load(saved.get("pace") or {})
            log.info("continuing the session saved %d s ago: same codes, timer at %.0f s",
                     time.time() - saved.get("saved", time.time()), hub.timer.elapsed())
        hub.on_change = self._on_change
        hub.extra = self._extra
        hub.on_press = self._press_corrected
        self.save_session()

    # -- what survives a restart --
    def _load_session(self) -> dict:
        try:
            with open(self.session_path, encoding="utf-8") as f:
                d = json.load(f)
            born = float(d.get("born") or d["saved"])
            if (isinstance(d, dict) and 0 <= time.time() - born < SESSION_HOURS * 3600
                    and all(isinstance(d.get(k), str) and len(d[k]) >= 6
                            for k in ("key", "host_key", "pin"))):
                d["born"] = born
                return d
        except Exception as e:      # missing, damaged, or nested too deep to read
            if not isinstance(e, FileNotFoundError):
                log.warning("the saved session could not be read: new codes (%s)", type(e).__name__)
        return {}

    def save_session(self):
        with self.save_lock:        # several threads save: one at a time, newest state last
            with self.hub.cond:
                data = {"saved": time.time(), "born": self.born, "key": self.key,
                        "host_key": self.host_key, "pin": self.pin, "port": self.port,
                        "timer": self.hub.timer.dump(), "pace": self.pace.dump()}
                self.dirty = False
            if not self.keep:
                return
            try:
                tmp = self.session_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                try:
                    os.chmod(tmp, 0o600)    # it holds the codes: this user only
                except OSError:
                    pass
                os.replace(tmp, self.session_path)
                if self.save_failed:
                    self.save_failed = False
                    log.info("the session is being saved again")
            except OSError as e:
                if not self.save_failed:
                    self.save_failed = True
                    log.warning("could not save the session (a restart would lose the clock): %s", e)

    def rotate(self):
        """New codes: every phone and every old link stops working."""
        self.key, self.pin, self.born = secrets.token_urlsafe(16), new_pin(), time.time()
        self.pin_bad, self.pin_fails = 0, {}
        self._qr.clear()
        log.info("new codes made; old links no longer work")
        self.save_session()
        self.hub.bump()

    def pair(self, pin: str, who: str = ""):
        """The 6-digit number from the pairing page, typed on the phone.
        Returns the key, None for a wrong number, or "locked" when this address
        has sent too many wrong ones (other addresses are not affected)."""
        now = time.monotonic()
        with self.press_lock:
            for addr in [a for a, ts in self.pin_fails.items() if not ts or now - ts[-1] >= 60]:
                del self.pin_fails[addr]
            mine = [t for t in self.pin_fails.get(who, []) if now - t < 60]
            if len(mine) >= 8:
                return "locked"
            digits = "".join(ch for ch in str(pin) if ch.isdigit())
            if secrets.compare_digest(digits.encode(), self.pin.encode()):
                return self.key
            if len(self.pin_fails) < 500 or who in self.pin_fails:
                self.pin_fails[who] = mine + [now]
            self.pin_bad += 1
            if self.pin_bad >= 30:      # someone is guessing: change the number
                self.pin, self.pin_bad = new_pin(), 0
                log.warning("30 wrong pairing numbers: a new number was made")
        return None

    def remote_url(self, base: str) -> str:
        return f"{base}/#k={self.key}"

    def qr(self, url: str) -> str:
        if url not in self._qr:
            self._qr[url] = qr_svg(url)
        return self._qr[url]

    def refused(self, what: str, who: str):
        """Log a rejected request, at most once every ten seconds per kind."""
        now = time.monotonic()
        if now - self._refused.get(what, -1e9) > 10:
            self._refused[what] = now
            log.info("refused %s from %s (wrong or old code)", what, who)

    # -- hooks, called by the hub with its lock held --
    @staticmethod
    def _showing(snap: dict):
        return snap["slide"] if snap.get("show") == "running" else None

    def _on_change(self, old: dict, new: dict):
        t = self.hub.timer
        live = ("running", "ended")
        was_live, now_live = old.get("show") in live, new.get("show") in live
        was, now = old.get("show") == "running", new.get("show") == "running"
        mono = time.monotonic()
        if now_live and not was_live:
            self.show_from = new.get("slide")
            if self.ended_at and mono - self.ended_at < RESUME_WITHIN and not t.running:
                # The show only blinked (PowerPoint hiccup, Esc by mistake): carry on.
                self.pace.account(self._showing(new))
                t.start()
                self.ended_at = 0.0
                log.info("timer resumed: the slide show is back")
        advance = was and now and (new["slide"] != old["slide"] or new["click"] > old["click"])
        if advance and t.auto and not t.running and not self.pace.rehearsing:
            if not t.started():
                # the first advance, from the phone, a clicker or the keyboard
                self.pace.account(self._showing(new))
                t.start()
                log.info("timer started by the first advance")
            elif self.ended_at:
                # The clock stopped because the last slide show ended, and this is
                # a new one. From the first slide it is a new run: a fresh clock.
                # From anywhere else the talk goes on: the clock does too.
                first = (getattr(self.backend, "visible", None) or [1])[0]
                fresh = self.show_from == first
                if fresh:
                    self._reset_timer()
                self.pace.account(self._showing(new))
                t.start()
                self.ended_at = 0.0
                log.info("timer %s by the first advance of a new slide show",
                         "started afresh" if fresh else "resumed")
        self.pace.account(self._showing(new))
        if was_live and not now_live:
            if t.running:
                t.pause()       # the show is over: stop the clock, keep the times
                self.ended_at = mono
                log.info("timer paused: the slide show ended")
        self.dirty = True

    def _extra(self, d: dict):
        visible = getattr(self.backend, "visible", None)
        d["timer"]["rehearsing"] = self.pace.rehearsing
        d["pace"] = self.pace.window(d, visible)
        d["plan"] = self.pace.summary(d, visible)
        d["section"] = self.pace.section(d, getattr(self.backend, "sections", None), visible)
        phones = self.hub.phones()
        h = self.holder
        if h and not self.hub.here(h):
            c = self.hub.clients.get(h) or {}
            gone = time.monotonic() - (c.get("left") or c.get("t") or 0)  # a closed page left at a known time
            if gone > 60 and sum(1 for p in phones if p["here"]) <= 1:
                log.info("co-presenters: the phone with the slides has been gone for a minute; "
                         "every phone presses again")
                self.holder = h = None
        d["control"] = {"holder": h, "name": next((p["name"] for p in phones if p["cid"] == h), ""),
                      "here": bool(h) and self.hub.here(h),
                      "phones": [p for p in phones if p["here"] or p["cid"] == h]}

    def _start_timer(self):
        self.pace.account(self._showing(self.hub.show))
        self.hub.timer.start()

    def _reset_timer(self):
        self.hub.timer.reset()
        self.pace.rehearsing = False
        self.pace.clear()

    def _bump(self):
        self.hub.version += 1
        self.hub.cond.notify_all()
        self.dirty = True

    # -- presses: each one is done at most once, and never late without saying so --
    def do_command(self, name: str, body: dict, who: str = "") -> str:
        """Returns "done", "stale" (the show had already left the slide the press
        was made from), "idle" (no slide show to act on), "busy" (PowerPoint
        never started on it; nothing happened) or "pending" (PowerPoint has it
        and it will land; the outcome follows in the state)."""
        pid = str(body.get("id") or "")[:40]
        t0 = time.monotonic()
        entry = None
        if not self.may_press(body.get("cid")):
            log.info("press %s [%s] %s from phone %s: refused, phone %s has the slides",
                     name, pid[:6] or "-", who, str(body.get("cid") or "?")[:8], str(self.holder or "-")[:8])
            return "not-yours"
        if pid:
            with self.press_lock:
                entry = self.presses.get(pid)
                again = entry is not None
                if not again:
                    entry = self.presses[pid] = {"done": threading.Event(), "result": None}
                    while len(self.presses) > 300:
                        self.presses.popitem(last=False)
            if again:
                # The same press arriving twice (the phone retried after a lost
                # answer). Wait for the first one; never do it again.
                entry["done"].wait(PRESS_TIMEOUT)
                log.info("press %s [%s] %s: sent again, answered from the first: %s",
                         name, pid[:6], who, entry["result"] or "pending")
                return entry["result"] or "pending"

        def finish(result, err):
            if err is not None:
                res = "busy" if getattr(err, "hresult", None) in COM_BUSY else "failed"
            else:
                res = result or "done"
            late = False
            if entry is not None:
                with self.press_lock:
                    late = entry["result"] == "pending"
                    entry["result"] = res
                entry["done"].set()
            with self.hub.cond:
                self.hub.last_press = {"id": pid, "result": res}
                if pid:
                    self.hub.recent.append(self.hub.last_press)
                self._bump()
            if late:
                log.info("press %s [%s]: landed late, %.1f s after it was made: %s",
                         name, pid[:6], time.monotonic() - t0, res)

        if name == "next" and self.hub.show.get("show") != "running":
            with self.hub.cond:     # arrow-key mode: there is no slide change to watch for
                t = self.hub.timer
                if t.auto and not t.started() and self.hub.show.get("show") == "none":
                    self._start_timer()
                    self._bump()
        try:
            result = self.backend.command(name, body, on_finish=finish) or "done"
        except PressPending:
            result = "pending"
            if entry is not None:
                with self.press_lock:
                    if entry["result"] is None:
                        entry["result"] = "pending"
                    else:
                        result = entry["result"]    # it finished in the same instant
        except TimeoutError:
            result = "busy"
            if entry is not None:
                entry["result"] = "busy"
                entry["done"].set()
        except Exception as e:
            # PowerPoint took the press and answered with an error
            result = "busy" if getattr(e, "hresult", None) in COM_BUSY else "failed"
            log.info("press %s failed: %s: %s", name, type(e).__name__, e)
        s = self.hub.show
        where = (f'slide {s["slide"]} step {s["click"]}/{s["clicks"]}'
                 if s.get("show") == "running" else s.get("show"))
        base = body.get("base") if isinstance(body.get("base"), dict) else None
        log.info("press %s [%s] %s%s: %s in %.2f s; now %s", name, pid[:6] or "-", who,
                 f' from slide {base.get("slide")} step {base.get("click")}' if base else "",
                 result, time.monotonic() - t0, where)
        return result

    def _press_corrected(self, pid: str, result: str):
        with self.press_lock:
            entry = self.presses.get(pid)
            if entry is not None:
                entry["result"] = result

    def may_press(self, cid) -> bool:
        return self.holder is None or str(cid or "")[:16] == self.holder

    def do_control(self, body: dict) -> dict:
        """Who presses: every phone, or one phone that the others follow.
        pass: give the slides to another phone. take: this phone takes them.
        share: every phone presses again."""
        action, cid = body.get("action"), str(body.get("cid") or "")[:16]
        if action not in ("pass", "take", "share") or not cid:
            raise BadRequest("unknown action")
        with self.hub.cond:
            names = {p["cid"]: p["name"] for p in self.hub.phones()}
            who = names.get(cid) or cid[:8]
            if action == "take":
                if self.holder != cid:
                    log.info("co-presenters: %s took the slides from %s", who,
                             names.get(self.holder, "every phone") if self.holder else "every phone")
                self.holder = cid
            elif action == "pass":
                to = str(body.get("to") or "")[:16]
                if self.holder not in (None, cid) and self.hub.here(self.holder):
                    raise BadRequest("this phone does not have the slides")
                if to not in names or not self.hub.here(to):
                    raise BadRequest("that phone is not connected")
                self.holder = to
                log.info("co-presenters: %s passed the slides to %s", who, names[to])
            elif action == "share":
                if self.holder not in (None, cid) and self.hub.here(self.holder):
                    raise BadRequest("this phone does not have the slides")
                self.holder = None
                log.info("co-presenters: %s let every phone press", who)
            self._bump()
            return self.hub._snapshot()

    # -- undo: a reset clock or a rehearsal start can be taken back for a few seconds --
    def _keep_undo(self, what: str, pos=None):
        t, p, s = self.hub.timer, self.pace, self.hub.show
        p.account(p.cur)
        if pos is None and s.get("show") == "running":
            pos = {"slide": s["slide"], "click": s["click"]}
        self.undo = {"what": what, "until": time.monotonic() + UNDO_FOR, "at": time.monotonic(),
                     "acc": t.elapsed(), "running": t.running, "dur": t.dur,
                     "spent": dict(p.spent), "rehearsing": p.rehearsing, "pos": pos}

    def do_undo(self) -> dict:
        goto = None
        with self.hub.cond:
            u, self.undo = self.undo, None
            if not u or time.monotonic() > u["until"]:
                raise BadRequest("nothing to undo")
            t, p = self.hub.timer, self.pace
            t.reset()
            t.acc, t.dur = u["acc"], u["dur"]
            if u["running"]:            # the talk went on meanwhile: so does its clock
                t.acc += time.monotonic() - u["at"]
                t.start()
            p.spent, p.rehearsing = dict(u["spent"]), u["rehearsing"]
            p.mark, p.cur = t.elapsed(), self._showing(self.hub.show)
            s = self.hub.show
            if u["pos"] and s.get("show") == "running" and s["slide"] != u["pos"]["slide"]:
                goto = int(u["pos"]["slide"])
            self.ended_at = 0.0
            self._bump()
            log.info("undo: %s taken back; clock at %.0f s", u["what"], t.elapsed())
        if goto:
            try:
                self.backend.command("goto", {"n": goto})
            except Exception as e:
                log.info("undo: could not go back to slide %d: %s", goto, e)
        self.save_session()
        snap = self.hub.snapshot()
        snap["undone"] = u["what"]
        return snap

    def press_result(self, pid: str, void: bool = False) -> str:
        """What became of a press the phone never heard back about. void: the phone
        is about to say it did not arrive, so if it has not, it never will: a late
        arrival is refused ("void") instead of carried out."""
        pid = str(pid)[:40]
        with self.press_lock:
            entry = self.presses.get(pid)
            if entry is None and void and pid:
                done = threading.Event()
                done.set()
                self.presses[pid] = {"done": done, "result": "void"}
                while len(self.presses) > 300:
                    self.presses.popitem(last=False)
                log.info("press [%s]: the phone gave up on it; if it still arrives it is refused", pid[:6])
                return "void"
            return (entry["result"] or "pending") if entry else "unknown"

    def do_timer(self, body: dict):
        action = body.get("action")
        if action not in (None, "start", "pause", "reset"):
            raise BadRequest("unknown timer action")
        try:
            dur = None if "dur" not in body else max(30, min(int(body["dur"]), 12 * 3600))
            marks = None
            if "marks" in body:
                if not isinstance(body["marks"], list):
                    raise ValueError
                marks = sorted({int(m) for m in body["marks"][:8] if 0 < int(m) < 12 * 3600},
                               reverse=True)
        except (TypeError, ValueError, OverflowError):
            raise BadRequest("talk length and alerts must be numbers")
        with self.hub.cond:
            t = self.hub.timer
            if action:
                self.ended_at = 0.0     # the presenter has taken the clock in hand
            if action == "start":
                self._start_timer()
            elif action == "pause":
                self.pace.account(self.pace.cur)
                t.pause()
            elif action == "reset":
                if t.started():
                    self._keep_undo("clock reset")
                self._reset_timer()
            if dur is not None:
                t.dur = dur
            if marks is not None:
                t.marks = marks
            if "auto" in body:
                t.auto = bool(body["auto"])
            self._bump()
        self.save_session()

    def do_rehearsal(self, body: dict) -> dict:
        """start: clear the clock and time every slide. save: keep the result
        as this deck's plan. discard: stop without keeping. delete: forget the
        saved plan."""
        action = body.get("action")
        if action not in ("start", "save", "discard", "delete"):
            raise BadRequest("unknown rehearsal action")
        saved = None
        with self.hub.cond:
            self.ended_at = 0.0
            if action == "start":
                back = body.get("back") if isinstance(body.get("back"), dict) else None
                if self.hub.timer.started() or back:
                    self._keep_undo("rehearsal start", back)
                self._reset_timer()
                self.pace.rehearsing = True
                self._start_timer()
            elif action == "save":
                self.pace.account(self.pace.cur)
                saved = self.pace.rehearsing and self.pace.save(self.hub.show)
                if saved:
                    self._reset_timer()
            elif action == "discard":
                if self.hub.timer.started():
                    self._keep_undo("rehearsal discarded")
                self._reset_timer()
            elif action == "delete":
                self.pace.forget(self.hub.show)
            self._bump()
            snap = self.hub._snapshot()
        if saved is not None:
            snap["saved"] = bool(saved)
        self.save_session()
        return snap

    def recap(self) -> dict:
        try:
            outline = self.backend.outline() or []
        except Exception:
            outline = []
        with self.hub.cond:
            snap = self.hub.show
            deck = snap.get("deck", "")
            if outline:
                self._outline = (deck, outline)
            elif self._outline[0] == deck:
                outline = self._outline[1]
            p = self.pace
            p.account(p.cur)
            plan = p.plan_for(snap)
            planned = {int(k): float(v) for k, v in plan["spent"].items()} if plan else {}
            info = {o["n"]: o for o in outline}
            numbers = sorted(set(range(1, int(snap.get("total") or 0) + 1))
                             | set(p.spent) | set(info))
            rows = [{"n": n, "title": info.get(n, {}).get("title", ""),
                     "hidden": bool(info.get(n, {}).get("hidden", False)),
                     "sec": info.get(n, {}).get("sec", ""),
                     "spent": round(p.spent.get(n, 0.0), 1),
                     "plan": planned.get(n, 0.0) if plan else None} for n in numbers]
            return {"deck": deck, "dur": self.hub.timer.dur,
                    "elapsed": round(sum(p.spent.values()), 1),
                    "rehearsing": p.rehearsing,
                    "plan": p.summary(snap, getattr(self.backend, "visible", None)),
                    "rows": rows}

    def host_info(self) -> dict:
        ip = lan_ip()
        lan = self.remote_url(f"http://{ip}:{self.port}")
        net = self.tunnel.view()
        if net["url"]:
            net["url"] = self.remote_url(net["url"])
            net["qr"] = self.qr(net["url"])
        snap = self.hub.snapshot()
        return {"app": APP, "version": VERSION, "windows": IS_WIN,
                "lan": {"url": lan, "qr": self.qr(lan), "short": f"{ip}:{self.port}"},
                "pin": self.pin, "net": net, "phones": self.hub.client_count(),
                "phoneList": [{"name": p["name"] or "A phone", "holder": p["cid"] == self.holder}
                              for p in self.hub.phones() if p["here"]],
                "status": self.backend.describe(), "show": snap["show"], "deck": snap["deck"],
                "pics": snap["pics"], "link": snap["link"], "restored": self.restored}


COMMANDS = {"next", "prev", "goto", "first", "last", "black", "start", "end"}
# the logo's icon files, served from the logo folder for browser tabs and home screens
ICONS = {"/favicon.ico": ("favicon.ico", "image/x-icon"),
         "/favicon.svg": ("cuewand-favicon.svg", "image/svg+xml"),
         "/icon-192.png": ("cuewand-icon-192.png", "image/png"),
         "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
         "/apple-touch-icon-precomposed.png": ("apple-touch-icon.png", "image/png")}
CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' data:; "
       "style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; "
       "frame-ancestors 'none'")
LOCAL_ONLY = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cuewand</title><body style="margin:0;background:#10141C;color:#EDEFF3;font:17px/1.5 system-ui,sans-serif">
<div style="max-width:34em;margin:18vh auto;padding:0 24px"><h1 style="font-size:28px;margin:0 0 10px">This page has moved on</h1>
<p style="color:#8E98AB">The pairing page only opens on the computer that runs Cuewand, with the address Cuewand
gave when it started. Look in the Cuewand window for the current address, or start Cuewand again.</p></div>"""


def make_handler(ctx: Context):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = APP
        sys_version = ""
        timeout = 30        # a connection that sends nothing for this long is closed

        def log_message(self, *a):
            pass

        # -- helpers --
        def _send(self, code, body=b"", ctype="application/json", cache="no-store"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, separators=(",", ":")))

        def _page(self, name):
            try:
                with open(os.path.join(HERE, name), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, f"{name} is missing from the Cuewand folder", "text/plain")

        def _who(self) -> str:
            """Where a request came from, for the log."""
            far = self.headers.get("Cf-Connecting-Ip")
            if far or self.headers.get("Cf-Ray"):
                return f"{far or '?'} through the internet link"
            return f"{self.client_address[0]} on the local network"

        def _addr(self) -> str:
            """Who is asking, for counting wrong pairing numbers. The far address
            is believed only when the request came in through the tunnel program
            on this computer; anyone else could make that header up."""
            near = self.client_address[0]
            far = self.headers.get("Cf-Connecting-Ip")
            return "cf:" + far[:60] if far and near in ("127.0.0.1", "::1") else near

        def _authed(self, q) -> bool:
            given = self.headers.get("X-Cuewand-Key") or q.get("k", [""])[0]
            return secrets.compare_digest(given.encode("utf-8", "replace"), ctx.key.encode())

        def _host_authed(self, q) -> bool:
            given = q.get("h", [""])[0]
            return self._from_this_computer() and secrets.compare_digest(
                given.encode("utf-8", "replace"), ctx.host_key.encode())

        def _from_this_computer(self) -> bool:
            """The pairing page and its buttons answer only this computer: not a
            phone, not a neighbour on the Wi-Fi, and not the internet link (whose
            requests also arrive from 127.0.0.1, but carry Cloudflare's headers)."""
            if self.headers.get("Cf-Ray") or self.headers.get("Cf-Connecting-Ip"):
                return False
            a = self.client_address[0]
            if a.startswith("::ffff:"):
                a = a[7:]
            return a.startswith("127.") or a == "::1" or a == lan_ip()

        def _length(self) -> int:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > 65536:
                self.close_connection = True    # do not try to read what follows
                raise BadRequest("too large" if n > 65536 else "bad length")
            return n

        def _drain(self):
            """Read and ignore the body of a request we are refusing."""
            n = self._length()
            if n:
                self._read(n)

        def _read(self, n: int) -> bytes:
            try:
                raw = self.rfile.read(n)
            except OSError as e:        # the rest of the request never came
                self.close_connection = True
                raise ConnectionError(f"request body did not arrive: {e}")
            if len(raw) < n:
                self.close_connection = True
                raise ConnectionError("request body was cut short")
            return raw

        def _body(self) -> dict:
            n = self._length()
            raw = self._read(n) if n else b"{}"
            try:
                obj = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, RecursionError):
                raise BadRequest("not JSON")
            if not isinstance(obj, dict):
                raise BadRequest("expected an object")
            return obj

        def _guard(self, fn):
            path = self.path.split("?")[0]
            if self.headers.get("Transfer-Encoding"):
                # A chunked body is never read here, so what follows could be taken for
                # a second request hidden in the first: refused, and the connection closed.
                self.close_connection = True
                try:
                    self._json({"error": "chunked requests are not accepted"}, 400)
                except Exception:
                    pass
                return
            if self.command != "POST" and (self.headers.get("Content-Length") or "0").strip() != "0":
                self.close_connection = True    # a body no route reads must not become the next request
            try:
                fn()
            except ConnectionError:
                pass
            except BadRequest as e:
                code = 413 if str(e) == "too large" else 400
                try:
                    self._json({"error": str(e)}, code)
                except ConnectionError:
                    pass
            except (TimeoutError, PressPending):
                log.info("%s: PowerPoint did not answer in time", path)
                try:
                    self._json({"error": "PowerPoint did not answer in time"}, 504)
                except ConnectionError:
                    pass
            except Exception as e:
                busy = getattr(e, "hresult", None) in COM_BUSY
                log.info("%s failed: %s: %s", path, type(e).__name__, e)
                try:    # the phone gets a plain reason, the log gets the detail
                    self._json({"error": "PowerPoint is busy" if busy else "internal error"},
                               504 if busy else 500)
                except Exception:
                    pass

        # -- routes --
        def do_GET(self):
            self._guard(self._get)

        def do_POST(self):
            self._guard(self._post)

        def _get(self):
            u = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(u.query)
            p = u.path
            if p in ("/", "/index.html"):
                return self._page("remote.html")
            if p == "/api/ping":
                return self._json({"cuewand": True, "version": VERSION})
            if p == "/host":
                if not self._host_authed(q):
                    return self._send(403, LOCAL_ONLY, "text/html; charset=utf-8")
                return self._page("host.html")
            if p == "/api/host/info":
                if not self._host_authed(q):
                    return self._json({"error": "forbidden"}, 403)
                return self._json(ctx.host_info())
            if p in ICONS:                  # the logo's icon files: public, no key needed
                try:
                    with open(os.path.join(HERE, "logo", ICONS[p][0]), "rb") as f:
                        return self._send(200, f.read(), ICONS[p][1], cache="public, max-age=86400")
                except OSError:
                    return self._send(404, "not found", "text/plain")
            if p.startswith("/api/"):
                if not self._authed(q):
                    ctx.refused(p, self._who())
                    return self._json({"error": "forbidden"}, 403)
                if p == "/api/state":
                    cid = q.get("c", [""])[0]
                    if ctx.hub.seen(cid, q.get("n", [""])[0]):
                        agent = (self.headers.get("User-Agent") or "")[:90]
                        log.info("phone %s connected from %s (%s; %s)", cid[:8], self._who(),
                                 clean_name(q.get("n", [""])[0]) or "no name", agent)
                    try:
                        since = int(q.get("since", ["0"])[0])
                        hold = max(0.0, min(float(q.get("hold", ["25"])[0]), 25.0))
                    except ValueError:
                        since, hold = 0, 0.0
                    return self._json(ctx.hub.wait(since, hold))
                if p == "/api/press":
                    pid = q.get("id", [""])[0]
                    return self._json({"id": pid, "result": ctx.press_result(pid, q.get("void", [""])[0] == "1")})
                if p == "/api/outline":
                    return self._json({"slides": ctx.backend.outline() or []})
                if p == "/api/recap":
                    return self._json(ctx.recap())
                m = re.fullmatch(r"/api/slide/(\d{1,5})\.jpg", p)
                if m:
                    want = q.get("d", [""])[0]
                    if want and want != str(ctx.hub.show.get("deckId", "")):
                        return self._send(404, "a picture of another deck", "text/plain")
                    img = ctx.backend.slide_image(int(m.group(1)))
                    if not img:
                        return self._send(404, "no such slide", "text/plain")
                    return self._send(200, img[0], img[1], cache="private, max-age=3600")
            self._send(404, "not found", "text/plain")

        def _post(self):
            u = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(u.query)
            p = u.path
            if p == "/api/pair":            # the 6-digit number, typed on the phone
                body = self._body()
                got = ctx.pair(str(body.get("pin", "")), self._addr())
                if got == "locked":
                    log.info("pairing number: too many wrong tries from %s", self._who())
                    return self._json({"error": "Too many tries. Wait a minute."}, 429)
                if got is None:
                    log.info("pairing number: a wrong one from %s", self._who())
                    return self._json({"error": "That is not the number on the computer."}, 403)
                log.info("a phone paired with the number, from %s", self._who())
                return self._json({"key": got})
            if p.startswith("/api/host/"):
                if not self._host_authed(q):
                    self._drain()
                    return self._json({"error": "forbidden"}, 403)
                body = self._body()
                if p == "/api/host/tunnel":
                    if body.get("restart"):
                        ctx.tunnel.restart()
                    else:
                        ctx.tunnel.start()
                    return self._json(ctx.tunnel.view())
                if p == "/api/host/rotate":
                    ctx.rotate()
                    return self._json({"ok": True})
                return self._json({"error": "not found"}, 404)
            if not p.startswith("/api/") or not self._authed(q):
                self._drain()
                ctx.refused(p, self._who())
                return self._json({"error": "forbidden"}, 403)
            body = self._body()
            if p == "/api/cmd":
                name = str(body.get("cmd", ""))
                if name not in COMMANDS:
                    raise BadRequest("unknown command")
                if name == "goto":
                    try:
                        body["n"] = int(body.get("n"))
                    except (TypeError, ValueError, OverflowError):
                        raise BadRequest("which slide?")
                result = ctx.do_command(name, body, self._who())
                snap = ctx.hub.snapshot()
                snap["press"] = {"id": str(body.get("id") or ""), "result": result}
                return self._json(snap)
            if p == "/api/laser":
                if not ctx.may_press(body.get("cid")):
                    return self._json({"ok": False, "why": "not-yours"})
                try:
                    x, y = float(body.get("x", 0.5)), float(body.get("y", 0.5))
                except (TypeError, ValueError):
                    x = y = 0.5
                if not (math.isfinite(x) and math.isfinite(y)):
                    x = y = 0.5
                ctx.backend.laser(min(1.0, max(0.0, x)), min(1.0, max(0.0, y)),
                                  bool(body.get("on")))
                return self._json({"ok": True})
            if p == "/api/timer":
                ctx.do_timer(body)
                return self._json(ctx.hub.snapshot())
            if p == "/api/rehearsal":
                return self._json(ctx.do_rehearsal(body))
            if p == "/api/pics":
                ctx.backend.remake_pictures()
                return self._json({"ok": True})
            if p == "/api/control":
                return self._json(ctx.do_control(body))
            if p == "/api/undo":
                return self._json(ctx.do_undo())
            if p == "/api/bye":             # a phone closed its page
                cid = str(body.get("cid") or q.get("c", [""])[0])[:16]
                if cid:
                    ctx.hub.gone(cid)
                    log.info("phone %s closed its page", cid[:8])
                return self._json({"ok": True})
            if p == "/api/demo" and ctx.backend.name == "demo":   # for trying what PowerPoint does
                be = ctx.backend
                try:
                    be.delay = max(0.0, min(float(body.get("delay", 0)), 30.0))
                    be.absorb = max(0.0, min(float(body.get("absorb", 0)), 10.0))
                except (TypeError, ValueError):
                    raise BadRequest("delay and absorb must be numbers")
                be.mislead = bool(body.get("mislead"))
                return self._json({"delay": be.delay, "absorb": be.absorb, "mislead": be.mislead})
            self._json({"error": "not found"}, 404)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64     # several phones reconnecting at once must not be turned away
    # On Windows, address reuse would let a second copy share the port silently.
    allow_reuse_address = not IS_WIN
    # Every open connection has a thread. A device that opens connections and never
    # finishes them must not be able to use them all: a phone needs a handful at
    # once, this computer (and the internet link, which arrives from it) more.
    PER_ADDRESS, PER_ADDRESS_LOCAL, AT_MOST = 40, 200, 400

    def __init__(self, *a, **k):
        self._open = collections.Counter()
        self._open_lock = threading.Lock()
        super().__init__(*a, **k)

    def process_request(self, request, client_address):
        who = client_address[0]
        cap = self.PER_ADDRESS_LOCAL if who in ("127.0.0.1", "::1") else self.PER_ADDRESS
        with self._open_lock:
            ok = self._open[who] < cap and sum(self._open.values()) < self.AT_MOST
            if ok:
                self._open[who] += 1
        if not ok:
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._closed(who)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._closed(client_address[0])

    def _closed(self, who):
        with self._open_lock:
            self._open[who] -= 1
            if self._open[who] <= 0:
                del self._open[who]


def bind(handler, port: int):
    last = None
    for p in range(port, port + 20):
        try:
            return Server(("0.0.0.0", p), handler), p
        except OSError as e:
            last = e
    raise SystemExit(f"Could not open a port near {port}: {last}")


def already_running(port: int) -> bool:
    """Is another Cuewand answering on this port?"""
    try:
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with direct.open(f"http://127.0.0.1:{port}/api/ping", timeout=0.6) as r:
            return b'"cuewand"' in r.read(200)
    except Exception:
        return False


# --------------------------------------------------------------------------
# First run: the PowerPoint connection needs the pywin32 package in *this* Python
# --------------------------------------------------------------------------

def _add_pywin32_paths():
    """Do by hand what pywin32's .pth file does, for the case where it was
    installed a moment ago or the .pth file was not processed."""
    import site
    roots = []
    for get in (getattr(site, "getsitepackages", None), getattr(site, "getusersitepackages", None)):
        try:
            got = get() if get else []
            roots += [got] if isinstance(got, str) else list(got)
        except Exception:
            pass
    roots += [p for p in sys.path if p.lower().rstrip("\\/").endswith("site-packages")]
    for root in dict.fromkeys(roots):
        if not os.path.isdir(os.path.join(root, "win32")):
            continue
        for sub in ("", "win32", os.path.join("win32", "lib"), "Pythonwin"):
            d = os.path.join(root, sub) if sub else root
            if os.path.isdir(d) and d not in sys.path:
                sys.path.append(d)
        dlls = os.path.join(root, "pywin32_system32")
        if os.path.isdir(dlls):
            try:
                os.add_dll_directory(dlls)
            except Exception:
                pass
            os.environ["PATH"] = dlls + os.pathsep + os.environ.get("PATH", "")


def _try_import(names) -> str:
    importlib.invalidate_caches()
    try:
        for name in names:
            importlib.import_module(name)
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"


LINK_MODULES = ("pythoncom", "pywintypes", "win32com.client.dynamic")


def ensure_powerpoint_link(pip=None) -> str:
    """Returns "" when this Python can talk to PowerPoint, otherwise why not.
    Installs the one thing that cannot travel with Cuewand: pywin32."""
    why = _try_import(LINK_MODULES)
    if why:
        _add_pywin32_paths()
        why = _try_import(LINK_MODULES)
    if not why:
        return ""
    print("\n  First run with this Python: installing pywin32, the piece that talks to PowerPoint.")
    print("  This needs the internet once and takes about half a minute.")
    log.info("pywin32 missing (%s); installing with pip into %s", why, sys.executable)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
           "pywin32"]
    try:
        rc = (pip or subprocess.call)(cmd)
    except Exception as e:
        rc = f"{type(e).__name__}: {e}"
    if rc != 0:
        log.warning("pip failed: %s", rc)
        return ("pywin32 could not be installed. In a Command Prompt, run:  "
                f'"{sys.executable}" -m pip install pywin32')
    _add_pywin32_paths()
    why = _try_import(LINK_MODULES)
    if why:
        log.info("pywin32 installed but not loadable yet (%s)", why)
        return "restart"
    log.info("pywin32 installed and loaded")
    return ""


# --------------------------------------------------------------------------
# Self-test: proof, on this computer and this deck, that presses land once
# --------------------------------------------------------------------------

def run_selftest(ctx: Context, want: int = 200, say=print, gap: float = 0.1) -> bool:
    """Drives the open deck through the same code a phone uses and checks,
    after every press, that the show is exactly where it should be."""
    hub, backend = ctx.hub, ctx.backend
    lines: list = []
    problems: list = []
    stats = {"sent": 0, "exact": 0, "self": 0, "lat": [], "absorbed": collections.Counter()}

    def out(text=""):
        say(text)
        lines.append(text)

    def wait(pred, seconds, step=0.1):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            s = hub.snapshot()
            if pred(s):
                return s
            time.sleep(step)
        return None

    on_slide = {"slide": None, "since": time.monotonic(), "age": 0.0}

    def note_slide(s):
        if s.get("slide") != on_slide["slide"]:
            on_slide.update(slide=s.get("slide"), since=time.monotonic())

    def press(name, base=True, pid=None, want=None, **extra):
        """One press, as a phone makes it. `want(before, after)` says where the
        show should be afterwards; PowerPoint is given a moment to report it,
        and then it has to stay there."""
        before = hub.snapshot()
        note_slide(before)
        on_slide["age"] = time.monotonic() - on_slide["since"]     # how long the slide had been up
        pid = pid or secrets.token_hex(6)
        body = dict(extra, cmd=name, id=pid)
        if base is True and before["show"] == "running" and name in ("next", "prev"):
            body["base"] = {"slide": before["slide"], "click": before["click"]}
        elif isinstance(base, dict):
            body["base"] = base
        t0 = time.monotonic()
        try:
            result = ctx.do_command(name, body, "self-test")
        except Exception as e:
            result = f"error ({type(e).__name__}: {e})"
        if result == "pending":
            wait(lambda s: (s["lastPress"] or {}).get("id") == pid, 20, 0.05)
            result = (hub.snapshot()["lastPress"] or {}).get("result", "pending")
        took = time.monotonic() - t0
        stats["sent"] += 1
        stats["lat"].append(took)
        # The phone may be told before PowerPoint confirms: wait for PowerPoint,
        # then judge by what it says, and by what became of the press in the end.
        end = time.monotonic() + 10
        while getattr(backend, "guess", None) is not None and time.monotonic() < end:
            time.sleep(0.05)
        if want is not None:
            wait(lambda s: want(before, s), 1.5, 0.05)
        if result == "done":
            result = ctx.press_result(pid) if ctx.press_result(pid) != "unknown" else result
        time.sleep(gap)
        after = hub.snapshot()
        note_slide(after)
        return before, after, result, took

    def expect(what, before, after, result, took, ok, timer_ok=False):
        if ok and result == "done":
            stats["exact"] += 1
        elif timer_ok:
            stats["self"] += 1      # the slide's own timer moved it first; not a fault
        elif result == "absorbed" and (after["slide"], after["click"]) == (before["slide"], before["click"]):
            stats["absorbed"][before["slide"]] += 1     # nothing moved, and the phone was told so
        else:
            problems.append(f"{what}: answered {result} in {took:.2f} s; show went from slide "
                            f"{before['slide']} step {before['click']} to slide "
                            f"{after['slide']} step {after['click']} ({after['show']})")

    out(f"{APP} {VERSION} self-test, {time.strftime('%d %b %Y %H:%M')}")
    s = wait(lambda s: s["total"] > 0 and s["show"] in ("idle", "running", "ended"), 20)
    if not s:
        why = backend.describe()
        out("No presentation found. Open your deck in PowerPoint (not in slide show), then run this again.")
        out("What Cuewand sees: " + why)
        return False
    if s["show"] != "idle":
        out("A slide show is running: ending it so the test starts from a known place.")
        press("end", base=False)
        s = wait(lambda s: s["show"] == "idle", 10) or hub.snapshot()
    out(f"Deck: {s['deck']}, {s['total']} slides.")

    out("Making the slide pictures (this is done before a show, never during one)...")
    t0 = time.monotonic()
    s = wait(lambda s: s["pics"][1] > 0 and s["pics"][0] + s["pics"][2] >= s["pics"][1], 600, 0.3)
    times = dict(getattr(backend, "pic_times", {}) or {})
    if s is None:
        s = hub.snapshot()
        out(f"  Pictures did not finish in 10 minutes: {s['pics'][0]} of {s['pics'][1]}.")
        problems.append("slide pictures did not finish")
    else:
        out(f"  {s['pics'][0]} of {s['pics'][1]} pictures in {time.monotonic() - t0:.0f} s"
            + (f"; {s['pics'][2]} could not be made" if s["pics"][2] else "") + ".")
    if times:
        slow = sorted(times.items(), key=lambda kv: -kv[1])[:5]
        out("  Slowest slides to draw: " + ", ".join(f"slide {n} {t:.1f} s" for n, t in slow) + ".")
    try:
        outline = backend.outline() or []
        shown = [r for r in outline if not r["hidden"]]
        out(f"Speaker notes found on {sum(1 for r in shown if r['notes'])} of {len(shown)} "
            f"slides that will be shown ({len(outline) - len(shown)} hidden).")
    except Exception as e:
        outline = []
        problems.append(f"could not read titles and notes: {type(e).__name__}: {e}")

    out("Starting the slide show...")
    press("start", base=False, **{"from": "first"})
    s = wait(lambda s: s["show"] == "running", 15)
    if not s:
        out("The slide show did not start. What Cuewand sees: " + backend.describe())
        return False
    visible = list(getattr(backend, "visible", None) or range(1, s["total"] + 1))

    def at_end(s):
        return s["show"] == "running" and s["next"] is None and s["click"] >= s["clicks"]

    def went_on(b, a):
        if b["click"] < b["clicks"]:
            return (a["slide"], a["click"]) == (b["slide"], b["click"] + 1)
        return a["slide"] == b["next"] and a["show"] == "running"

    def went_back(b, a):
        if b["click"] > 0:
            return (a["slide"], a["click"]) == (b["slide"], b["click"] - 1)
        earlier = [v for v in visible if v < b["slide"]]
        return bool(earlier) and a["slide"] == earlier[-1]

    def still(b, a):
        return (a["show"], a["slide"], a["click"]) == (b["show"], b["slide"], b["click"])

    def forward():
        n = stuck = 0
        while stats["sent"] < 5000 and stuck < 3:     # three presses in a row that move nothing: stop
            s = hub.snapshot()
            if s["show"] != "running" or at_end(s):
                return n
            b, a, r, took = press("next", want=went_on)
            ok = went_on(b, a)
            expect("Next", b, a, r, took, ok, timer_ok=by_timer(b, a, r))
            stuck = stuck + 1 if still(b, a) else 0
            n += 1
        return n

    def by_timer(b, a, r):
        """The slide's own timer moved the show and the press was rightly refused as
        made from a slide the show had left. Only one step on, and only once the
        slide had been up as long as its timer: a skip is never excused."""
        return (r == "stale" and b["auto"] > 0 and went_on(b, a)
                and on_slide["age"] >= b["auto"] - 0.5)

    def at_start(s):
        return s["show"] == "running" and s["slide"] == visible[0] and s["click"] == 0

    def backward():
        n = stuck = 0
        while stats["sent"] < 5000 and stuck < 3:
            s = hub.snapshot()
            if s["show"] != "running" or at_start(s):
                return n
            b, a, r, took = press("prev", want=went_back)
            ok = went_back(b, a)
            expect("Back", b, a, r, took, ok, timer_ok=by_timer(b, a, r))
            stuck = stuck + 1 if still(b, a) else 0
            n += 1
        return n

    passes = 0
    while stats["sent"] < want and passes < 40:
        passes += 1
        f = forward()
        if not at_end(hub.snapshot()):
            problems.append(f"pass {passes}: the walk forward stopped at slide "
                            f"{hub.snapshot()['slide']} ({hub.snapshot()['show']})")
            break
        b = backward()
        out(f"  Pass {passes}: {f} Next and {b} Back presses.")
        if hub.snapshot()["show"] != "running":
            problems.append(f"pass {passes}: the slide show ended on its own")
            break
        if not at_start(hub.snapshot()):
            problems.append(f"pass {passes}: the walk back stopped at slide {hub.snapshot()['slide']}")
            break

    if hub.snapshot()["show"] == "running":
        out("Checking the safeguards...")
        # 1. the same press arriving twice must move the show once
        b, a, r, took = press("next", pid="selftest-twice")
        b2, a2, r2, took2 = press("next", pid="selftest-twice")
        stats["sent"] -= 1
        if (a2["slide"], a2["click"]) != (a["slide"], a["click"]):
            problems.append("a press that arrived twice moved the show twice")
        else:
            out("  A press that arrives twice moves the show once: yes.")
        # 2. a press made from a slide the show has left must do nothing
        b, a, r, took = press("next", base={"slide": 9999, "click": 0})
        stats["sent"] -= 1
        if r != "stale" or (a["slide"], a["click"]) != (b["slide"], b["click"]):
            problems.append(f"a press made from another slide was carried out ({r})")
        else:
            out("  A press made from a slide the show has left is refused: yes.")
        # 3. jumps
        for target in [visible[len(visible) // 2], visible[-1], visible[0]]:
            b, a, r, took = press("goto", base=False, n=target, want=lambda b, a, t=target: a["slide"] == t)
            expect(f"Go to slide {target}", b, a, r, took, a["slide"] == target)
        # 4. black out and back
        b, a, r, took = press("black", base=False, want=lambda b, a: a["black"] is True)
        expect("Black out", b, a, r, took, a["black"] is True)
        b, a, r, took = press("black", base=False, want=lambda b, a: a["black"] is False)
        expect("Show slides again", b, a, r, took, a["black"] is False)
        # 5. a burst with no pause at all
        saved_gap, gap = gap, 0.0
        for _ in range(min(12, len(visible) - 1)):
            s = hub.snapshot()
            if at_end(s):
                break
            b, a, r, took = press("next", want=went_on)
            ok = went_on(b, a)
            expect("Next (burst)", b, a, r, took, ok, timer_ok=by_timer(b, a, r))
        gap = saved_gap
        press("end", base=False)
        stats["sent"] -= 1
        wait(lambda s: s["show"] == "idle", 10)

    lat = sorted(stats["lat"])
    absorbed = stats["absorbed"]
    judged = (stats["exact"] + stats["self"] + sum(absorbed.values())
              + len([p for p in problems if ": answered" in p]))
    out()
    out(f"Presses checked: {judged}. Landed exactly once, where expected: {stats['exact']}."
        + (f" Moved first by a slide's own timer (not a fault): {stats['self']}."
           if stats["self"] else ""))
    if lat:
        mid, p95 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        out(f"Time until the phone hears back: typical {mid * 1000:.0f} ms, "
            f"95% under {p95 * 1000:.0f} ms, slowest {lat[-1] * 1000:.0f} ms.")
    bstats = getattr(backend, "stats", None) or {}

    def slides(counter):
        return ", ".join(str(n) for n in sorted(counter))

    slow = bstats.get("slow") or {}
    if slow:
        out("PowerPoint is slow to answer for a few seconds after these slides come up: "
            + ", ".join(f"slide {n} {t:.1f} s" for n, t in sorted(slow.items())) + ". "
            "The phone still shows each press at once; a second press made in that time "
            "waits for PowerPoint and lands after it.")
    retried = bstats.get("retried") or {}
    if retried:
        out(f"Pressed while a slide was still appearing (slides {slides(retried)}): "
            "PowerPoint used the press to finish it, so Cuewand sent it once more "
            f"({sum(retried.values())} times). Not a fault.")
    if absorbed:
        out(f"Presses PowerPoint took without moving: {sum(absorbed.values())} (slides "
            f"{slides(absorbed)}). The phone said 'Nothing moved, press again', so nothing "
            "is skipped and nothing lands twice. Not a fault, but the presenter has to "
            "press again there.")
    if problems:
        out(f"PROBLEMS: {len(problems)}")
        for p in problems[:25]:
            out("  - " + p)
    else:
        out("RESULT: every press landed exactly once.")
    path = os.path.join(data_dir(), "cuewand_selftest.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        say(f"\nSaved as {path}. Details of every press are in cuewand_selftest.log.")
    except OSError:
        pass
    return not problems


# --------------------------------------------------------------------------

def pictures_parent():
    """Where the slide pictures are made: the temp folder, except under a
    Microsoft Store Python, which sees a private copy of AppData (and so of
    its temp folder) that PowerPoint cannot write into. Then: Cuewand's folder."""
    if IS_WIN and "windowsapps" in (sys.executable or "").lower():
        d = data_dir()
        if "appdata" not in d.lower():
            return d
    return None


def _sweep_old_pictures(base=None):
    """Slide-picture folders left behind when a Cuewand window was closed without
    warning. Only a folder Cuewand made itself is touched: named exactly as Cuewand
    names them, old, and holding nothing but Cuewand's own pictures."""
    base = base or tempfile.gettempdir()
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        if not re.fullmatch(r"cuewand_pics_[a-z0-9_]{8}", name):
            continue
        path = os.path.join(base, name)
        try:
            if (os.path.islink(path) or not os.path.isdir(path)
                    or time.time() - os.path.getmtime(path) < 6 * 3600):
                continue
            inside = os.listdir(path)
            if all(re.fullmatch(r"[0-9a-f]{10}_\d{1,5}\.jpg", f) for f in inside):
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


_KEEP = []   # the console handler must stay referenced


def _on_window_close(cleanup):
    """Windows: run cleanup when the console window is closed with its X."""
    if not IS_WIN:
        return
    try:
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
        def handler(_event):
            try:
                cleanup()
            except Exception:
                pass
            return False
        _KEEP.append(handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Cuewand: run your slides from your phone.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--demo", action="store_true", help="use a built-in demo deck")
    ap.add_argument("--internet", action="store_true",
                    help="turn on the internet link straight away")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open the pairing page")
    ap.add_argument("--new-codes", action="store_true",
                    help="forget the saved session: new codes, timer at zero")
    ap.add_argument("--prepare", action="store_true",
                    help="download the internet-link program now (do this at home), then stop")
    ap.add_argument("--selftest", action="store_true",
                    help="drive the open deck through a few hundred presses and report")
    ap.add_argument("--presses", type=int, default=200, help="how many presses --selftest sends")
    args = ap.parse_args()

    if args.selftest and (already_running(args.port) or not hold_lock()):
        print(f"\n  {APP} is running in another window. Close that window first, then run the test again.\n")
        sys.exit(1)
    if not args.selftest and not args.prepare and (already_running(args.port) or not hold_lock()):
        print(f"\n  {APP} is already running on this computer.")
        try:
            with open(os.path.join(data_dir(), "cuewand_session.json"), encoding="utf-8") as f:
                saved = json.load(f)
            url = f"http://127.0.0.1:{int(saved.get('port') or args.port)}/host?h={saved['host_key']}"
            if args.no_browser:
                print(f"  Its pairing page:\n    {url}\n")
            else:
                print(f"  Opening its pairing page:\n    {url}\n")
                webbrowser.open(url)
        except Exception:
            print("  Use the pairing page it opened, or close that window first.\n")
        return

    if args.prepare:
        t = Tunnel(args.port)
        if t._find_exe():
            print("\n  The internet-link program is already here. Nothing to do.\n")
            return
        print(f"\n  Downloading the internet-link program, version {CLOUDFLARED_VERSION} (about 55 MB)...")
        try:
            print(f"  Saved and checked: {t.download()}\n")
        except Exception as e:
            print(f"  That did not work: {e}\n")
        return

    log_path = os.path.join(data_dir(), "cuewand_selftest.log" if args.selftest else "cuewand.log")
    try:
        if os.path.exists(log_path) and not args.selftest:
            os.replace(log_path, os.path.join(data_dir(), "cuewand.previous.log"))
    except OSError:
        pass
    logging.basicConfig(
        filename=log_path, filemode="w",
        level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
    if not IS_WIN:
        try:
            os.chmod(log_path, 0o600)   # phone names and addresses: this user only
        except OSError:
            pass
    log.info("%s %s starting on %s, Python %s, port %d, address %s", APP, VERSION, sys.platform,
             sys.version.split()[0], args.port, lan_ip())
    _sweep_old_pictures()
    if pictures_parent():
        _sweep_old_pictures(pictures_parent())

    if IS_WIN:
        try:  # so pointer positions are in real pixels on scaled displays
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    link_why = ""
    if IS_WIN and not args.demo:
        link_why = ensure_powerpoint_link()
        if link_why == "restart":
            if not os.environ.get("CUEWAND_RELAUNCHED"):
                logging.shutdown()   # start once more so the new package is picked up
                release_lock()       # the new start takes it
                sys.exit(subprocess.call([sys.executable] + sys.argv,
                                         env=dict(os.environ, CUEWAND_RELAUNCHED="1")))
            link_why = "pywin32 is installed but this Python cannot load it"
        try:
            from importlib import metadata
            log.info("PowerPoint connection: %s (pywin32 %s)", link_why or "ready",
                     metadata.version("pywin32"))
        except Exception:
            log.info("PowerPoint connection: %s", link_why or "ready")

    hub = Hub()
    demo = args.demo or not IS_WIN
    backend = DemoBackend(hub) if demo else WindowsBackend(hub)

    if args.selftest:
        ctx = Context(hub, backend, Tunnel(args.port), args.port, fresh=True, keep=False)
        backend.start()
        if not demo:
            print("\n  This test takes over PowerPoint for a minute or two: it starts your slide show")
            print("  and steps through it several times. Open your deck first, and do not touch")
            print("  the keyboard or mouse until it says it is finished.\n")
            try:
                input("  Press Enter to begin, or close this window to cancel. ")
            except EOFError:
                pass
        ok = run_selftest(ctx, want=max(10, args.presses))
        backend.close()
        sys.exit(0 if ok else 1)

    ctx = Context(hub, backend, None, args.port, fresh=args.new_codes)
    server, port = bind(make_handler(ctx), args.port)
    ctx.port = port
    ctx.tunnel = Tunnel(port)
    ctx.save_session()

    def cleanup():
        ctx.save_session()
        ctx.tunnel.stop()
        backend.close()
    atexit.register(cleanup)
    _on_window_close(cleanup)

    backend.start()
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()

    host_url = f"http://127.0.0.1:{port}/host?h={ctx.host_key}"
    print(f"\n  {APP} {VERSION} is running.\n")
    if demo and not args.demo:
        print("  This is not Windows, so Cuewand is showing its demo deck.\n")
    if IS_WIN and not args.demo:
        if link_why:
            print("  PowerPoint connection: OFF. " + link_why)
            print("  Until that is fixed, Next and Back only press the arrow keys:")
            print("  no notes, no slide pictures, no pace.\n")
        else:
            print("  PowerPoint connection: ready.\n")
    if ctx.restored:
        print("  Continuing where the last run stopped: same codes, same timer.")
        print("  (Start with --new-codes to begin afresh.)\n")
    print(f"  Pairing page (opens in your browser):\n    {host_url}\n")
    print(f"  No camera? On the phone open  {lan_ip()}:{port}  and type  {ctx.pin[:3]} {ctx.pin[3:]}\n")
    print("  Keep this window open while you present. Close it to stop.\n")
    if not args.no_browser:
        try:
            webbrowser.open(host_url)
        except Exception:
            pass
    if args.internet:
        ctx.tunnel.start()
    try:
        last = time.monotonic()
        while True:
            time.sleep(1)
            if ctx.dirty or (hub.timer.running and time.monotonic() - last > 5):
                ctx.save_session()      # so a restart picks the talk up where it was
                last = time.monotonic()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
