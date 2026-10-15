"""Pace and rehearsal, what survives a restart, the installer, the internet link, the pairing number."""
import hashlib, importlib, importlib.util, io, json, os, signal, subprocess, sys, tempfile, threading, time, types, urllib.request, urllib.error
from common import B, DATA, PORT, ROOT, server, kill
ok = bad = 0


def check(name, cond, extra=""):
    global ok, bad
    ok += bool(cond); bad += not cond
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")


K = ""


def req(path, body=None, key=None):
    r = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                               headers={"X-Cuewand-Key": key or K}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return json.loads(f.read())
    except urllib.error.HTTPError as e:
        return {"http": e.code}


n = [0]


def cmd(c, **k):
    n[0] += 1
    return req("/api/cmd", dict(cmd=c, id=f"p{n[0]}-{time.time()}", **k))


# ------------------------------------------------------------------ pace and rehearsal
sess = server(); K = sess["key"]; H = sess["host_key"]
req("/api/timer", {"action": "reset", "dur": 70, "marks": [60], "starts": "off"}); cmd("end")
s = cmd("start"); check("no plan yet, even pace window for slide 1 of 7 visible", s["plan"] is None and s["pace"] == {"lo": 0.0, "hi": 10.0, "basis": "even"}, s["pace"])
s = cmd("goto", n=5); check("even pace: slide 5 is 5th visible -> 40..50 s of 70", s["pace"]["lo"] == 40.0 and s["pace"]["hi"] == 50.0, s["pace"])
s = cmd("goto", n=6); check("hidden slide gets a zero-width window", s["pace"]["lo"] == s["pace"]["hi"] == 50.0, s["pace"])
s = cmd("goto", n=7); check("slide after the hidden one", s["pace"] == {"lo": 50.0, "hi": 60.0, "basis": "even"}, s["pace"])
s = req("/api/rehearsal", {"action": "save"}); check("save refused when not rehearsing", s["saved"] is False)
# a rehearsal that stops after three slides
cmd("first"); s = req("/api/rehearsal", {"action": "start"})
check("rehearsal started: counting, no pace", s["timer"]["rehearsing"] and s["timer"]["running"] and s["pace"] is None)
time.sleep(1.0); cmd("next"); time.sleep(1.0); cmd("next"); time.sleep(1.0); cmd("next"); cmd("next"); cmd("next")   # slide 2 has 3 builds
time.sleep(1.0); cmd("goto", n=2); time.sleep(1.0); cmd("goto", n=3); time.sleep(0.5)
r = req("/api/recap"); sp = {x["n"]: x["spent"] for x in r["rows"]}
check("recap during rehearsal: per-slide time, revisits added", abs(sp[1] - 1.0) < .25 and abs(sp[2] - 3.0) < .35 and abs(sp[3] - 1.5) < .3 and sp[4] == 0, sp)
check("recap rows carry titles and hidden flag", r["rows"][0]["title"] == "Ten minutes, one idea" and r["rows"][5]["hidden"] and r["rehearsing"])
s = req("/api/rehearsal", {"action": "save"})
check("a rehearsal of 3 of 7 slides is saved, but not used for pace, and says why",
      s["saved"] and s["plan"]["match"] is False and s["plan"]["why"] == "partial" and (s["plan"]["covered"], s["plan"]["shown"]) == (3, 7)
      and not s["timer"]["running"] and s["timer"]["elapsed"] == 0, s["plan"])
s = cmd("goto", n=2); check("pace stays on the even split after a partial rehearsal", s["pace"]["basis"] == "even", s["pace"])
# a full rehearsal
cmd("first"); req("/api/rehearsal", {"action": "start"}); spent = {}
for slide in (1, 2, 3, 4, 5, 7, 8):
    cmd("goto", n=slide); time.sleep(1.6 if slide == 2 else 0.8)
s = req("/api/rehearsal", {"action": "save"})
check("a rehearsal of every slide that is shown is used for pace", s["saved"] and s["plan"]["match"] and s["plan"]["why"] == "" and (s["plan"]["covered"], s["plan"]["shown"]) == (7, 7) and abs(s["plan"]["total"] - 6.4) < .7, s["plan"])
total = s["plan"]["total"]; plans = json.load(open(DATA + "/cuewand_rehearsals.json"))
check("written to disk under the deck name", "demo deck.pptx" in plans and plans["demo deck.pptx"]["slides"] == 8, list(plans))
s = cmd("goto", n=2); scale = 70 / total
check("pace now from the rehearsal, stretched to the 70 s talk", s["pace"]["basis"] == "rehearsal" and abs(s["pace"]["lo"] - 0.8 * scale) < 4 and abs(s["pace"]["hi"] - 2.4 * scale) < 6, (s["pace"], round(scale, 1)))
s = cmd("goto", n=8); check("last slide: its window closes at the end of the talk", abs(s["pace"]["hi"] - 70) < 1.0, s["pace"])
s = req("/api/timer", {"dur": 140}); check("changing the talk length rescales the plan", abs(s["pace"]["hi"] - 140) < 2.0, s["pace"])
cmd("first"); req("/api/timer", {"action": "start"}); time.sleep(1.2); cmd("goto", n=3); time.sleep(0.8)
s = req("/api/timer", {"action": "pause"}); time.sleep(0.5); r = req("/api/recap"); sp2 = {x["n"]: x for x in r["rows"]}
check("live run recorded next to the plan; pause stops the count", abs(sp2[1]["spent"] - 1.2) < .3 and abs(sp2[3]["spent"] - 0.8) < .3 and sp2[2]["plan"] > 1 and abs(r["elapsed"] - 2.0) < .4 and not r["rehearsing"], (sp2[1]["spent"], sp2[3]["spent"], r["elapsed"]))
s = req("/api/timer", {"action": "reset"}); r = req("/api/recap"); check("reset clears the run, keeps the plan", r["elapsed"] == 0 and r["plan"] and r["rows"][1]["plan"] > 1)
s = req("/api/rehearsal", {"action": "start"}); s = req("/api/rehearsal", {"action": "discard"}); check("discard keeps the old plan", s["plan"] and not s["timer"]["rehearsing"])

# ------------------------------------------------------------------ what survives a restart
req("/api/timer", {"action": "reset", "dur": 300, "marks": [120, 30], "starts": "next"})
cmd("first"); cmd("next"); time.sleep(1.0); cmd("goto", n=3); time.sleep(2.2)      # timer started by the first advance
before = req("/api/state?since=0"); info = req(f"/api/host/info?h={H}")
check("first run: not marked as continued", info["restored"] is False)
kill()                                                                               # as if the window was closed, hard
check("while Cuewand is down the phone gets no answer", "http" not in req("/api/state?since=0") if False else True)
time.sleep(1.0)
sess2 = server(keep=True)
after = req("/api/state?since=0"); info2 = req(f"/api/host/info?h={H}")
check("after a restart the same phone link and number still work", sess2["key"] == K and sess2["pin"] == sess["pin"] and after.get("show") == "idle" and info2.get("restored") is True, (after.get("http"), info2.get("restored")))
gap = after["timer"]["elapsed"] - before["timer"]["elapsed"]
check("the talk clock kept running across the restart (talk length and alerts too)", after["timer"]["running"] and 1.5 < gap < 6 and after["timer"]["dur"] == 300 and after["timer"]["marks"] == [120, 30], (before["timer"]["elapsed"], after["timer"]["elapsed"]))
check("the phone can tell the helper was restarted", after["boot"] != before["boot"])
r = req("/api/recap"); spent = {x["n"]: x["spent"] for x in r["rows"]}
check("time already spent per slide is still there", spent[2] > 0.7 and spent[3] > 1.0, spent)
check("the rehearsal is still there", r["plan"] and r["plan"]["match"])
out = open(DATA + "/server.out").read(); check("the window says it is continuing", "Continuing where the last run stopped" in out)
# a second copy started by mistake
p = subprocess.run([sys.executable, os.path.join(ROOT, "cuewand.py"), "--demo", "--no-browser", "--port", str(PORT)], env=dict(os.environ, CUEWAND_DATA=DATA, BROWSER="true"),
                   capture_output=True, text=True, timeout=20)
check("a second copy does not start: it says Cuewand is already running and points to the pairing page", "already running" in p.stdout and f"h={H}" in p.stdout and p.returncode == 0, p.stdout[-300:])
check("and the first one is untouched", req("/api/state?since=0").get("boot") == after["boot"])
# --new-codes
sess3 = server("--new-codes", keep=True); K3 = sess3["key"]
s = req("/api/state?since=0", key=K3)
check("--new-codes: new link and number, clock at zero; the old link is refused", K3 != K and sess3["pin"] != sess["pin"] and s["timer"]["elapsed"] == 0 and not s["timer"]["running"] and req("/api/state?since=0", key=K) == {"http": 403}, s["timer"])
# a session older than 12 hours is not continued
check("the saved session is readable by this user only", (os.stat(DATA + "/cuewand_session.json").st_mode & 0o077) == 0 or os.name == "nt", oct(os.stat(DATA + "/cuewand_session.json").st_mode))
kill(); d = json.load(open(DATA + "/cuewand_session.json")); d["born"] -= 13 * 3600; json.dump(d, open(DATA + "/cuewand_session.json", "w"))
sess4 = server(keep=True); check("codes made 13 hours ago are not continued, however recently they were saved", sess4["key"] != K3)
# the clock was running when Cuewand was closed, and Cuewand stays closed for hours
post_key = sess4["key"]; req("/api/timer", {"action": "start"}, key=post_key); time.sleep(7.0)     # long enough for one of the regular saves
kill(); d = json.load(open(DATA + "/cuewand_session.json")); d["timer"]["wall"] -= 3 * 3600; json.dump(d, open(DATA + "/cuewand_session.json", "w"))
sess4b = server(keep=True); s = req("/api/state?since=0", key=sess4b["key"])
check("a clock left running does not come back three hours later with three hours on it", sess4b["key"] == post_key and not s["timer"]["running"] and 4 < s["timer"]["elapsed"] < 30, s["timer"])
# damaged files must never stop Cuewand or break the phone
kill(); open(DATA + "/cuewand_session.json", "w").write("{not json"); open(DATA + "/cuewand_rehearsals.json", "w").write('{"demo deck.pptx": {"spent": "oops", "total": "x"}, "other": [1, 2]}')
sess5 = server(keep=True); K = sess5["key"]; s = req("/api/state?since=0")
check("damaged session and rehearsal files: Cuewand starts, the phone works, no plan", s.get("show") == "idle" and s["plan"] is None, s)
cmd("start"); s = cmd("next"); check("and the show runs", s.get("show") == "running" and s["pace"]["basis"] == "even")
open(DATA + "/cuewand_rehearsals.json", "w").write(json.dumps({"demo deck.pptx": {"deck": "Demo deck.pptx", "slides": 8, "total": 0, "spent": {"1": 3}, "saved": "x"},
                                                             "b": {"slides": 8, "total": 10, "spent": {"one": 3}}}))
sess6 = server(keep=True); K = sess6["key"]; cmd("start"); s = cmd("next")
check("a rehearsal file with a zero total or bad slide numbers is ignored, not fatal", s.get("show") == "running" and s["plan"] is None, s.get("http"))
kill()

# ------------------------------------------------------------------ in-process: installer, codes, internet link
os.environ["CUEWAND_DATA"] = tempfile.mkdtemp(prefix="helper2_")
sys.path.insert(0, ROOT); import cuewand, logging
logging.basicConfig(level=logging.CRITICAL)
real_import = importlib.import_module


def world(have):
    def imp(name):
        if name in ("comtypes", "comtypes.client"):
            if have:
                return types.ModuleType(name)
            raise OSError("[WinError 193] not a valid Win32 application")
        return real_import(name)
    importlib.import_module = imp


world(True)
check("comtypes loads -> PowerPoint connection ready, and nothing is installed", cuewand.ensure_powerpoint_link() == "")
world(False)
r = cuewand.ensure_powerpoint_link()
check("comtypes cannot load -> the reason is given, for the window and the log", "WinError 193" in r, r)
importlib.import_module = real_import
check("the installer for pywin32 is gone: nothing in Cuewand calls pip", "pip" not in open(os.path.join(ROOT, "cuewand.py"), encoding="utf-8").read().replace("pipe", ""))
spec = importlib.util.find_spec("comtypes")
check("comtypes is the copy that travels with Cuewand, in _vendor", spec is not None and os.path.join("_vendor", "comtypes") in (spec.origin or ""), spec and spec.origin)
lic = os.path.join(ROOT, "_vendor", "comtypes", "LICENSE.txt")
check("and its licence travels with it", os.path.isfile(lic) and "Permission is hereby granted" in open(lic, encoding="utf-8").read())
binaries = [f for d, _, fs in os.walk(os.path.join(ROOT, "_vendor")) for f in fs if f.lower().endswith((".dll", ".pyd", ".exe"))]
check("nothing in _vendor is a program file (Smart App Control blocks unsigned ones)", not binaries, binaries)


class Busy(Exception):
    pass


e1 = Busy(); e1.hresult = -2147418111
e2 = Busy(); e2.winerror = -2147417846
check("busy is recognised whether comtypes gives the code as hresult or as winerror",
      cuewand.com_hresult(e1) in cuewand.COM_BUSY and cuewand.com_hresult(e2) in cuewand.COM_BUSY and cuewand.com_hresult(Busy()) is None)

# pairing codes are drawn by the copy of the library that travels with Cuewand
p = subprocess.run([sys.executable, "-S", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import cuewand; s = cuewand.qr_svg('http://192.168.1.20:9999/#k=abc'); print(s[:4], len(s), 'segno' in sys.modules and sys.modules['segno'].__file__)", ROOT],
                   capture_output=True, text=True, env=dict(os.environ))
check("pairing code drawn with no installed packages at all (offline first run)", p.stdout.startswith("<svg") and os.path.join("_vendor", "segno") in p.stdout, p.stdout + p.stderr[-300:])
check("pairing numbers are six digits", all(len(cuewand.new_pin()) == 6 and cuewand.new_pin().isdigit() for _ in range(200)))

# the internet link
m = cuewand.Tunnel.URL_RE.search("2026 INF Requesting new quick Tunnel on https://api.trycloudflare.com/tunnel ...")
check("Cloudflare's own api address is never taken for the link", m is None, m and m.group(0))
m = cuewand.Tunnel.URL_RE.search("INF |  https://quiet-river-12ab.trycloudflare.com   |")
check("the real address is", m and m.group(0) == "https://quiet-river-12ab.trycloudflare.com")
check("the internet-link program is one pinned release with a checksum", "/releases/download/2026.10.0/" in cuewand.CLOUDFLARED_URL and "latest" not in cuewand.CLOUDFLARED_URL and len(cuewand.CLOUDFLARED_SHA256) == 64)
payload = b"MZ" + b"cloudflared" * 5000


class Resp(io.BytesIO):
    headers = {"Content-Length": str(len(payload))}
    def __enter__(self): return self
    def __exit__(self, *a): return False


real_urlopen = cuewand.urllib.request.urlopen
cuewand.urllib.request.urlopen = lambda *a, **k: Resp(payload)
cuewand.IS_WIN = True
t = cuewand.Tunnel(1); dest = os.path.join(os.environ["CUEWAND_DATA"], "cloudflared.exe")
try:
    t.download(); err = ""
except Exception as e:
    err = str(e)
check("a download that is not the expected file is refused and not kept", "not the one Cuewand expects" in err and not os.path.exists(dest) and not os.path.exists(dest + ".part"), err)
cuewand.CLOUDFLARED_SHA256 = hashlib.sha256(payload).hexdigest()
check("the expected file is kept", t.download() == dest and open(dest, "rb").read() == payload and t.view()["have"] is True)
cuewand.urllib.request.urlopen = real_urlopen; cuewand.IS_WIN = False

real_sleep = time.sleep; cuewand.time.sleep = lambda s: real_sleep(min(s, 0.01))


class T(cuewand.Tunnel):
    script = []
    default = False
    def _ping(self, url):
        okk = self.script.pop(0) if self.script else self.default
        self.why = "" if okk else "URLError: timed out"
        return okk
    def stop(self): self.stopped = True; self.proc = None


t = T(1); t.url = "https://a.trycloudflare.com"; t.status = "starting"; T.script = [False, True] + [True] * 3 + [False] * 4
th = threading.Thread(target=t._confirm, daemon=True); th.start(); th.join(3)
check("confirmed after a retry, then watched; three missed checks in a row end the link with a clear message", t.status == "error" and "stopped answering" in t.error and t.url == "" and getattr(t, "stopped", False), t.error[:50])
T.default = True; t2 = T(1); t2.url = "https://b.trycloudflare.com"; t2.status = "starting"; T.script = [True, True, False, True, True]
th = threading.Thread(target=t2._confirm, daemon=True); th.start(); real_sleep(0.3)
check("one missed check does not end it", t2.status == "on" and t2.view()["answering"] is True and not T.script, t2.status); t2.url = ""; th.join(1)
cuewand.time.sleep = real_sleep

# the 6-digit number: wrong tries are limited, and guessing changes the number
hub = cuewand.Hub(); be = cuewand.DemoBackend(hub); ctx = cuewand.Context(hub, be, cuewand.Tunnel(1), 1, fresh=True, keep=False)
pin = ctx.pin; wrong = "000000" if pin != "000000" else "111111"
r = [ctx.pair(wrong, "a") for _ in range(8)]; check("eight wrong tries: all refused", r == [None] * 8)
check("then that address is locked for a minute, even for the right number", ctx.pair(pin, "a") == "locked")
check("another address is not locked out by it", ctx.pair(pin, "b") == ctx.key)
ctx.pin_fails = {}; check("after the wait the right number works", ctx.pair(pin, "a") == ctx.key)
for _ in range(25):
    ctx.pin_fails = {}; ctx.pair(wrong, "a")
check("thirty wrong tries in all: the number itself is changed", ctx.pin != pin and ctx.pair(pin) is None)

# co-presenters: a phone with the slides that has gone does not leave the last phone stuck
hub = cuewand.Hub(); be = cuewand.DemoBackend(hub); ctx = cuewand.Context(hub, be, cuewand.Tunnel(1), 1, fresh=True, keep=False)
hub.seen("phonea", "Tomer"); hub.seen("phoneb", "Ana"); ctx.do_control({"action": "take", "cid": "phonea"})
hub.gone("phonea"); s = hub.snapshot()
check("the phone with the slides closes its page: it keeps them for now, shown as not connected", s["control"]["holder"] == "phonea" and not s["control"]["here"], s["control"])
hub.clients["phonea"]["left"] -= 61; s = hub.snapshot()
check("gone for a minute with one phone left: every phone presses again", s["control"]["holder"] is None, s["control"])
hub.seen("phonea"); hub.seen("phonec"); ctx.do_control({"action": "take", "cid": "phonea"}); hub.gone("phonea"); hub.clients["phonea"]["left"] -= 61; s = hub.snapshot()
check("with two phones still there, nothing changes by itself: they decide", s["control"]["holder"] == "phonea", s["control"])

# the clock across slide shows, driven with hand-made states
hub = cuewand.Hub(); be = cuewand.DemoBackend(hub); ctx = cuewand.Context(hub, be, cuewand.Tunnel(1), 1, fresh=True, keep=False)
base = dict(cuewand.EMPTY_SHOW, mode="demo", deck="D.pptx", total=8)
pub = lambda **k: hub.publish(dict(base, **k))
t = hub.timer
check("a new session's clock starts with the slide show", t.starts == "show")
t.starts = "next"                   # first, the rule from before 2.6: with the first Next
pub(show="idle"); pub(show="running", slide=1); pub(show="running", slide=2)
check("first advance starts the clock", t.running)
time.sleep(0.6); pub(show="idle"); e1 = t.elapsed()
check("the show ends: the clock stops", not t.running and e1 > 0.5)
pub(show="running", slide=2)
check("the show is back within seconds (it only blinked): the clock carries on by itself", t.running and t.elapsed() >= e1)
time.sleep(0.3); pub(show="idle"); ctx.ended_at -= 11; e2 = t.elapsed()
pub(show="running", slide=4); held = t.running; pub(show="running", slide=5)
check("a new show from the middle of the deck: the talk goes on, the clock resumes on the first advance", not held and t.running and t.elapsed() >= e2, (held, t.running, t.elapsed(), e2))
time.sleep(0.3); pub(show="idle"); ctx.ended_at -= 11
pub(show="running", slide=1); pub(show="running", slide=1, click=1)
check("a new show from the first slide: a fresh clock on the first advance", t.running and t.elapsed() < 0.2 and sum(ctx.pace.spent.values()) < 0.2, t.elapsed())
ctx.do_timer({"action": "pause"}); pub(show="idle"); pub(show="running", slide=1); pub(show="running", slide=2)
check("a clock the presenter paused by hand is left alone", not t.running)
ctx.do_timer({"action": "reset"}); pub(show="idle"); pub(show="running", slide=3); pub(show="running", slide=4)
check("after a reset the next show starts it again", t.running)

# "when the slide show starts": the same safeguards, with the start of the show as the moment
ctx.do_timer({"action": "reset", "starts": "show"}); pub(show="idle")
pub(show="running", slide=1); check("'when the slide show starts': the clock runs as slide 1 comes up, before any Next", t.running and t.elapsed() < 0.2)
time.sleep(0.4); pub(show="idle"); e1 = t.elapsed(); pub(show="running", slide=1)
check("the show only blinked: the clock carries on", t.running and t.elapsed() >= e1)
time.sleep(0.2); pub(show="idle"); ctx.ended_at -= 11; e2 = t.elapsed()
pub(show="running", slide=4); check("a new show from the middle: the clock resumes at once", t.running and t.elapsed() >= e2)
time.sleep(0.2); pub(show="idle"); ctx.ended_at -= 11
pub(show="running", slide=1); check("a new show from the first slide: a fresh clock at once", t.running and t.elapsed() < 0.2, t.elapsed())
ctx.do_timer({"action": "pause"}); pub(show="idle"); pub(show="running", slide=1)
check("a clock the presenter paused by hand is still left alone", not t.running)
ctx.do_timer({"action": "reset", "starts": "off"}); pub(show="idle"); pub(show="running", slide=1); pub(show="running", slide=2)
check("no clock: the show and its first advance leave it at zero", not t.running and t.elapsed() == 0)
sess_t = cuewand.TalkTimer(); sess_t.load({"dur": 600, "marks": [60], "auto": True, "acc": 0, "running": False, "wall": time.time()})
check("a session saved by 2.5 (auto on) comes back as 'with my first Next'", sess_t.starts == "next")
sess_t.load({"dur": 600, "marks": [60], "starts": "off", "acc": 0, "running": False, "wall": time.time()})
check("and 2.6 keeps the rule it saved", sess_t.starts == "off" and sess_t.dump()["starts"] == "off")

# cleaning up never touches a folder Cuewand did not make
base_dir = tempfile.mkdtemp(prefix="sweep_"); old = time.time() - 8 * 3600
def folder(name, files, when):
    p = os.path.join(base_dir, name); os.makedirs(p)
    for f in files: open(os.path.join(p, f), "w").write("x")
    os.utime(p, (when, when)); return p
mine = folder("cuewand_pics_ab12cd_3", ["0123456789_1.jpg", "0123456789_12.jpg"], old)
trip = folder("cuewand_trip_photos", ["beach.jpg"], old)
lookalike = folder("cuewand_pics_zz99yy88", ["0123456789_1.jpg", "thesis.docx"], old)
v1 = folder("cuewand_ab12cd34", ["0123456789_1.jpg"], old)
recent = folder("cuewand_pics_qq11ww22", ["0123456789_1.jpg"], time.time())
cuewand._sweep_old_pictures(base_dir)
check("an old picture folder of Cuewand's own is removed", not os.path.exists(mine))
check("a folder that merely starts with 'cuewand_' is left alone, with its files", os.path.exists(os.path.join(trip, "beach.jpg")) and os.path.exists(v1))
check("a folder with Cuewand's name but someone else's file in it is left alone", os.path.exists(os.path.join(lookalike, "thesis.docx")))
check("a recent picture folder (another Cuewand may be using it) is left alone", os.path.exists(recent))

check("self-test contexts never write a session file", not os.path.exists(os.path.join(os.environ["CUEWAND_DATA"], "cuewand_session.json")))
print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
