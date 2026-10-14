"""Cuewand over HTTP, against the demo deck: who may come in, presses, the clock, junk input."""
import json, os, socket, sys, time, threading, urllib.request, urllib.error
from common import B, DATA, PORT, server
sess = server()
K, H, PIN = sess["key"], sess["host_key"], sess["pin"]


def req(path, body=None, key="*", raw=False, timeout=40):
    key = K if key == "*" else key
    r = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                               headers={"X-Cuewand-Key": key} if key else {},
                               method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            d = f.read()
            return f.status, (d if raw else json.loads(d)), f.headers
    except urllib.error.HTTPError as e:
        d = e.read()
        try:
            return e.code, json.loads(d), e.headers
        except ValueError:
            return e.code, d, e.headers


ok = fails = 0


def check(name, cond, extra=""):
    global ok, fails
    if cond:
        ok += 1
    else:
        fails += 1
    print(("PASS " if cond else "FAIL ") + name, extra if not cond or extra else "")


n = [0]


def press(cmd, base=None, pid=None, **kw):
    n[0] += 1
    body = dict(kw, cmd=cmd, id=pid or f"t{n[0]}-{time.time()}")
    if base is not None:
        body["base"] = base
    c, s, _ = req("/api/cmd", body)
    return c, s


# ---- who may come in ----
c, _, h = req("/", key=None, raw=True)
check("remote page opens without a key, with a CSP", c == 200 and "media-src" in h["Content-Security-Policy"])
c, d, _ = req("/api/ping", key=None); check("ping says cuewand + version", d.get("cuewand") is True and d["version"].startswith("2."), d)
for path, kind in (("/favicon.ico", "image/x-icon"), ("/favicon.svg", "image/svg+xml"), ("/icon-192.png", "image/png"), ("/apple-touch-icon.png", "image/png"), ("/apple-touch-icon-precomposed.png", "image/png")):
    c, d, h = req(path, key=None, raw=True)
    check(f"{path}: the logo's icon, without a key, cached", c == 200 and h["Content-Type"] == kind and h["Cache-Control"].startswith("public") and len(d) > 300, (c, h["Content-Type"], len(d)))
c, d, h = req("/favicon.svg", key=None, raw=True)
check("the favicon is the small cut: no chevron, nothing that runs", d.startswith(b"<svg") and b"<script" not in d and d.count(b"<path") == 3, d[:80])
c, _, _ = req("/logo/favicon.ico", key=None, raw=True); check("the logo folder itself is not served", c == 404)
c, _, _ = req("/api/state", key=None); check("state without key -> 403", c == 403)
c, _, _ = req("/api/state", key="wrong"); check("state wrong key -> 403", c == 403)
c, _, _ = req("/api/cmd", {"cmd": "next"}, key="wrong"); check("cmd wrong key -> 403", c == 403)
c, _, _ = req("/host?h=nope", key=None, raw=True); check("host page wrong token -> 403", c == 403)
c, _, _ = req("/api/host/info?h=" + K, key=K, raw=True); check("host info with the phone key -> 403", c == 403)
c, d, _ = req("/api/host/info?h=" + H, key=None)
check("host info: code picture, number, short address, picture count",
      c == 200 and d["lan"]["qr"].startswith("<svg") and d["net"]["status"] == "off" and d["pin"] == PIN
      and d["lan"]["short"].endswith(f":{PORT}") and d["pics"] == [8, 8, 0] and d["link"] == "ok", d)
check("host info names the deck it found", d.get("deck") == "Demo deck.pptx", d.get("deck"))

# ---- pairing with the 6-digit number ----
c, d, _ = req("/api/pair", {"pin": "000000"}, key=None); check("wrong number -> 403 with a plain reason", c == 403 and "number" in d["error"], d)
c, d, _ = req("/api/pair", {"pin": f"{PIN[:3]} {PIN[3:]}"}, key=None); check("right number (typed with a space) -> key", c == 200 and d["key"] == K)
for i in range(8):
    c, d, _ = req("/api/pair", {"pin": "111111"}, key=None)
check("8 wrong numbers in a minute -> locked", c in (403, 429))
c, d, _ = req("/api/pair", {"pin": PIN}, key=None); check("this address is locked out, even with the right number", c == 429, c)


def pair_from(addr, pin):       # as a phone arriving through the tunnel program on this computer
    r = urllib.request.Request(B + "/api/pair", data=json.dumps({"pin": pin}).encode(), headers={"Cf-Connecting-Ip": addr}, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=10) as f:
            return f.status
    except urllib.error.HTTPError as e:
        return e.code


codes = [pair_from("203.0.113.9", "222222") for _ in range(9)]
check("another address guessing wrong is locked out by itself", codes[:8] == [403] * 8 and codes[8] == 429, codes)
check("and nobody else is: the right number still pairs from a third address", pair_from("198.51.100.7", PIN) == 200)

# ---- the show ----
c, s, _ = req("/api/state?since=0&c=t1")
check("idle at start; snapshot carries boot, lastPress, pics, link",
      s["show"] == "idle" and s["deck"] == "Demo deck.pptx" and len(s["boot"]) == 8 and s["lastPress"] is None
      and s["pics"] == [8, 8, 0] and s["link"] == "ok" and s["timer"]["auto"] is True, s)
boot = s["boot"]
c, s = press("next"); check("next with no slide show -> idle, nothing happens", s["press"]["result"] == "idle" and s["show"] == "idle", s["press"])
c, s = press("start", **{"from": "first"}); check("start -> running slide 1", s["show"] == "running" and s["slide"] == 1 and s["next"] == 2 and s["press"]["result"] == "done")
check("timer not started by starting the show", not s["timer"]["running"])
c, s = press("next", base={"slide": 1, "click": 0}); check("next -> slide 2 with 3 builds", s["slide"] == 2 and s["clicks"] == 3 and s["click"] == 0 and s["press"]["result"] == "done")
check("first advance starts the timer", s["timer"]["running"])
for i in range(3):
    c, s = press("next", base={"slide": 2, "click": i})
check("3 nexts stay on slide 2, builds done", s["slide"] == 2 and s["click"] == 3)

# ---- a press can never double, and never lands on another slide ----
c, s = press("next", base={"slide": 2, "click": 3}, pid="dup-1"); check("next -> slide 3", s["slide"] == 3 and s["press"] == {"id": "dup-1", "result": "done"})
c, s = press("next", base={"slide": 2, "click": 3}, pid="dup-1"); check("same press id again: answered, not done again", s["slide"] == 3 and s["press"]["result"] == "done", s["slide"])
c, d, _ = req("/api/press?id=dup-1"); check("press lookup: done", d == {"id": "dup-1", "result": "done"}, d)
c, d, _ = req("/api/press?id=never-sent"); check("press lookup: unknown", d["result"] == "unknown")
c, s = press("next", base={"slide": 2, "click": 3}); check("press made from a slide the show has left -> stale, no move", s["press"]["result"] == "stale" and s["slide"] == 3, s["press"])
c, s = press("prev", base={"slide": 9, "click": 0}); check("stale Back too", s["press"]["result"] == "stale" and s["slide"] == 3)
c, s, _ = req("/api/state?since=0"); check("lastPress follows the last finished press", s["lastPress"]["result"] == "stale", s["lastPress"])

c, s = press("goto", n=5); check("goto 5; next skips hidden 6", s["slide"] == 5 and s["next"] == 7)
c, s = press("black"); check("black on", s["black"] is True)
c, s = press("next", base={"slide": 5, "click": 0}); check("next from black only un-blacks", s["black"] is False and s["slide"] == 5)
c, s = press("black"); c, s = press("last"); check("'last' clears black", s["slide"] == 8 and s["black"] is False)
c, s = press("next"); check("past last -> ended", s["show"] == "ended")
c, s = press("next"); check("next at the end does not exit", s["show"] == "ended")
c, s = press("prev"); check("back from the end -> last slide", s["show"] == "running" and s["slide"] == 8)

# ---- junk in, plain answers out ----
c, d, _ = req("/api/cmd", {"cmd": "rm -rf"}); check("unknown command -> 400", c == 400 and d["error"] == "unknown command", d)
c, d, _ = req("/api/cmd", {"cmd": "goto", "n": "abc"}); check("bad goto -> 400, plain words", c == 400 and "Traceback" not in str(d), d)
c, d, _ = req("/api/cmd", {"cmd": "goto"}); check("goto without a number -> 400", c == 400)
c, d, _ = req("/api/timer", {"dur": "long"}); check("bad talk length -> 400", c == 400, d)
for raw, what in ((b'{"cmd":"goto","n":1e999}', "/api/cmd"), (b'{"dur":1e999}', "/api/timer"), (b'{"marks":[1e999]}', "/api/timer"), (b'{"a":' + b"[" * 20000 + b"]" * 20000 + b"}", "/api/cmd")):
    r = urllib.request.Request(B + what, data=raw, headers={"X-Cuewand-Key": K}, method="POST")
    try:
        urllib.request.urlopen(r, timeout=5); code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    check(f"absurd input ({raw[:22].decode()}...) -> 400, never a 500", code == 400, code)
c, d, _ = req("/api/timer", {"marks": "soon"}); check("bad alerts -> 400", c == 400, d)
c, d, _ = req("/api/timer", {"action": "explode"}); check("bad timer action -> 400", c == 400)
c, d, _ = req("/api/rehearsal", {"action": "explode"}); check("bad rehearsal action -> 400", c == 400)
c, d, _ = req("/api/state?since=abc&hold=x"); check("bad poll numbers do not break the poll", c == 200 and d["show"] == "running")
r = urllib.request.Request(B + "/api/cmd", data=b"[1,2]", headers={"X-Cuewand-Key": K}, method="POST")
try:
    urllib.request.urlopen(r, timeout=5); check("a list instead of an object -> 400", False)
except urllib.error.HTTPError as e:
    check("a list instead of an object -> 400", e.code == 400)
r = urllib.request.Request(B + "/api/cmd", data=b"{not json", headers={"X-Cuewand-Key": K}, method="POST")
try:
    urllib.request.urlopen(r, timeout=5); check("not JSON -> 400", False)
except urllib.error.HTTPError as e:
    check("not JSON -> 400", e.code == 400)
big = urllib.request.Request(B + "/api/cmd", data=b"x" * 70000, headers={"X-Cuewand-Key": K}, method="POST")
try:
    urllib.request.urlopen(big, timeout=5); check("oversize body -> 413", False)
except urllib.error.HTTPError as e:
    check("oversize body -> 413", e.code == 413, e.code)
except Exception as e:
    check("oversize body refused", True, type(e).__name__)
c, d, h = req("/api/slide/3.jpg?k=" + K, key=None, raw=True); check("slide picture via ?k=", c == 200 and d[:4] == b"<svg" and "max-age" in h["Cache-Control"])
c, d, _ = req("/api/slide/99.jpg", raw=True); check("missing slide -> 404", c == 404)
c, d, _ = req("/api/outline"); check("outline: 8 slides, #6 hidden, pictures flagged", len(d["slides"]) == 8 and d["slides"][5]["hidden"] and d["slides"][0]["pic"] is True)
c, d, _ = req("/api/laser", {"x": "NaN", "y": 2, "on": True}); check("laser tolerates junk", c == 200)
c, d, _ = req("/api/pics", {}); check("remake pictures accepted", c == 200 and d["ok"])

# ---- timer ----
req("/api/timer", {"action": "reset"})
c, s, _ = req("/api/timer", {"dur": 600, "marks": [120, 60, 60, -5]}); check("timer set", s["timer"]["dur"] == 600 and s["timer"]["marks"] == [120, 60] and not s["timer"]["running"])
c, s, _ = req("/api/timer", {"action": "start"}); time.sleep(1.2); c, s, _ = req("/api/state?since=0")
check("timer runs", s["timer"]["running"] and 1.0 < s["timer"]["elapsed"] < 2.0, s["timer"]["elapsed"])
c, s, _ = req("/api/timer", {"action": "pause"}); e1 = s["timer"]["elapsed"]; time.sleep(.5); c, s, _ = req("/api/state?since=0")
check("timer pauses", s["timer"]["elapsed"] == e1)
c, s, _ = req("/api/timer", {"action": "reset"}); req("/api/timer", {"action": "reset"})
c, s = press("goto", n=2); req("/api/timer", {"action": "reset"})
c, s = press("next", base={"slide": 2, "click": 0}); check("auto: a build step (same slide) starts the timer", s["timer"]["running"] and s["slide"] == 2 and s["click"] == 1)
time.sleep(0.15)
c, s = press("end"); check("end -> idle, and the clock stops with the show", s["show"] == "idle" and not s["timer"]["running"] and s["timer"]["elapsed"] > 0, s["timer"])
req("/api/timer", {"action": "reset", "auto": False})
c, s = press("start"); c, s = press("next"); check("auto off: advancing does not start the timer", not s["timer"]["running"])
req("/api/timer", {"auto": True})

# ---- long poll, short hold, phones ----
c, s, _ = req("/api/state?since=0"); v = s["v"]; got = {}


def waiter():
    t = time.time(); c, s2, _ = req(f"/api/state?since={v}&c=t2"); got["dt"] = time.time() - t; got["s"] = s2


th = threading.Thread(target=waiter); th.start(); time.sleep(.6); press("goto", n=4); th.join()
check("long-poll wakes on a change", .5 < got["dt"] < 1.2 and got["s"]["slide"] == 4, f'{got["dt"]:.2f}s')
c, s, _ = req("/api/state?since=0"); t = time.time(); c, s2, _ = req(f"/api/state?since={s['v']}&hold=1"); dt = time.time() - t
check("hold=1 returns after about a second when nothing changes", 0.9 < dt < 1.6 and s2["v"] == s["v"], f"{dt:.2f}s")
c, d, _ = req("/api/host/info?h=" + H, key=None); check("phones counted", d["phones"] == 2, d["phones"])

# ---- a slow PowerPoint: the press is 'pending', then lands once, and the phone is told ----
press("goto", n=7)
req("/api/demo", {"delay": 5.5})
c, s, _ = req("/api/state?since=0"); at = s["slide"]
t = time.time(); c, s = press("next", base={"slide": at, "click": s["click"]}, pid="slow-1"); dt = time.time() - t
check("slow press: answered 'pending' after ~4 s, show not moved yet", s["press"]["result"] == "pending" and 3.8 < dt < 4.8 and s["slide"] == at, (s["press"], round(dt, 2)))
c, d, _ = req("/api/press?id=slow-1"); check("lookup while pending", d["result"] == "pending")
c, s2 = press("next", base={"slide": at, "click": s["click"]}, pid="slow-1")
check("the same press sent again while pending: waits, lands once", s2["press"]["result"] == "done" and s2["slide"] == at + 1, (s2["press"], s2["slide"]))
c, s3, _ = req("/api/state?since=0"); check("lastPress reports the late landing", s3["lastPress"] == {"id": "slow-1", "result": "done"} and s3["slide"] == at + 1, s3["lastPress"])
check("and it stays findable among the recent presses, for when another phone presses in between", {"id": "slow-1", "result": "done"} in s3["presses"] and len(s3["presses"]) <= 12, s3["presses"])
req("/api/demo", {"delay": 0})
time.sleep(0.2)

# ---- PowerPoint takes a press but does not move (a slide still appearing): said so, never 'done' ----
press("goto", n=2); c, s, _ = req("/api/state?since=0"); at = (s["slide"], s["click"])
req("/api/demo", {"absorb": 30})
c, s = press("next", base={"slide": at[0], "click": at[1]}, pid="soak-1")
check("a press PowerPoint takes without moving is answered 'absorbed', and the show is where it was", s["press"]["result"] == "absorbed" and (s["slide"], s["click"]) == at, (s["press"], s["slide"]))
c, d, _ = req("/api/press?id=soak-1"); check("and looked up later, it says the same", d["result"] == "absorbed", d)
req("/api/demo", {"mislead": True})
c, s = press("next", base={"slide": at[0], "click": at[1]}, pid="soak-2")
told = (s["press"]["result"], (s["slide"], s["click"]) != at)
time.sleep(1.0); c, s2, _ = req("/api/state?since=0"); c, d, _ = req("/api/press?id=soak-2")
check("told 'done' at once, then PowerPoint did not move after all: the state goes back and the press record says so", told == ("done", True) and (s2["slide"], s2["click"]) == at and d["result"] == "absorbed" and {"id": "soak-2", "result": "absorbed"} in s2["presses"], (told, s2["slide"], d))
req("/api/demo", {"delay": 0})
c, d, _ = req("/api/demo", {"absorb": "lots"}); check("demo knobs take numbers only", c == 400, c)
time.sleep(0.2)

# ---- two phones pressing Next on the same slide at once: one advance ----
press("goto", n=1)
c, s, _ = req("/api/state?since=0"); at = s["slide"]; res = []


def tap(i):
    c, r = press("next", base={"slide": at, "click": 0}, pid=f"race-{i}")
    res.append(r["press"]["result"])


ths = [threading.Thread(target=tap, args=(i,)) for i in range(6)]
[t.start() for t in ths]; [t.join() for t in ths]
c, s, _ = req("/api/state?since=0")
check("each of the six can find its own result", {p["id"] for p in s["presses"]} >= {f"race-{i}" for i in range(6)}, s["presses"])
check("6 phones press Next on the same slide: exactly one advance", s["slide"] == 2 and s["click"] == 0 and sorted(res) == ["done"] + ["stale"] * 5, (at, s["slide"], res))

# ---- 2.3: what the phone needs about each slide ----
press("start"); press("goto", n=2)
c, s, _ = req("/api/state?since=0")
check("the state names the slide, its section, and the next slide's first line", s["title"] == "Why most talks run over" and s["sec"] == "Opening" and s["nextCue"].startswith("If a slide needs the word") and s["section"]["name"] == "Opening" and (s["section"]["pos"], s["section"]["size"]) == (2, 2), (s["title"], s["sec"], s["section"]))
c, d, _ = req("/api/outline")
r2 = d["slides"][1]
check("the outline carries notes, slide text, steps, click marks and section for searching", r2["marks"] == 3 and r2["steps"] == 3 and "Too many slides" in r2["text"] and r2["body"] and r2["sec"] == "Opening" and d["slides"][5]["hidden"], r2)

press("goto", n=6); c, s, _ = req("/api/state?since=0"); b6 = s["backup"]
press("goto", n=7); c, s, _ = req("/api/state?since=0")
check("a hidden slide is marked as a backup, so the phone offers the way back only there; a shown one is not", b6 is True and s["backup"] is False, (b6, s["backup"]))
c, d, _ = req("/api/recap")
check("the recap's rows carry their section, so the phone can total each", c == 200 and all("sec" in r for r in d["rows"]) and d["rows"][0]["sec"] == "Opening" and d["rows"][7]["sec"] == "Closing", [r.get("sec") for r in d["rows"]])

# ---- co-presenters: one phone can have the slides ----
req("/api/state?since=0&hold=0&c=phoneone&n=One%01Two")    # a control character in a name is dropped
req("/api/state?since=0&hold=0&c=phonetwo&n=Ana")
c, s, _ = req("/api/state?since=0")
names = {p["cid"]: p["name"] for p in s["control"]["phones"]}
check("phones are listed by the names their owners gave", names.get("phoneone") == "OneTwo" and names.get("phonetwo") == "Ana" and s["control"]["holder"] is None, names)
c, s, _ = req("/api/control", {"action": "take", "cid": "phoneone"})
check("a phone takes the slides", c == 200 and s["control"]["holder"] == "phoneone" and s["control"]["name"] == "OneTwo" and s["control"]["here"])
at = (s["slide"], s["click"])
c, s = press("next", pid="co-1")
check("then a press with no phone named is refused, nothing moves", s["press"]["result"] == "not-yours" and (s["slide"], s["click"]) == at, s["press"])
c, s = press("next", pid="co-2", cid="phonetwo")
check("and so is a press from the other phone", s["press"]["result"] == "not-yours" and (s["slide"], s["click"]) == at)
c, s = press("next", pid="co-3", cid="phoneone")
check("the phone with the slides presses as usual", s["press"]["result"] == "done" and (s["slide"], s["click"]) != at)
c, d, _ = req("/api/laser", {"x": .5, "y": .5, "on": True, "cid": "phonetwo"})
check("the laser too answers only that phone", d == {"ok": False, "why": "not-yours"}, d)
c, d, _ = req("/api/control", {"action": "share", "cid": "phonetwo"})
check("the other phone cannot hand the slides round while the holder is connected", c == 400, (c, d))
c, d, _ = req("/api/control", {"action": "pass", "cid": "phoneone", "to": "nobody"})
check("nor can they be passed to a phone that is not connected", c == 400)
c, s, _ = req("/api/control", {"action": "pass", "cid": "phoneone", "to": "phonetwo"})
check("passing hands them over", c == 200 and s["control"]["holder"] == "phonetwo")
c, d, _ = req("/api/host/info?h=" + H, key=None)
check("the pairing page lists the phones, and which one has the slides", any(p["name"] == "Ana" and p["holder"] for p in d["phoneList"]), d["phoneList"])
c, d, _ = req(f"/api/bye?k={K}&c=phonetwo", {}, key=None)
c, s, _ = req("/api/state?since=0")
check("a phone that closes its page is gone at once, so another can take over", c == 200 and s["control"]["holder"] == "phonetwo" and not s["control"]["here"], s["control"])
c, s, _ = req("/api/control", {"action": "share", "cid": "phoneone"})
check("with the holder gone, another phone can let every phone press again", c == 200 and s["control"]["holder"] is None)
c, d, _ = req("/api/control", {"action": "wave", "cid": "phoneone"})
check("unknown co-presenter actions are refused", c == 400)

# ---- undo ----
press("goto", n=4); req("/api/timer", {"action": "start"}); time.sleep(1.3)
c, d, _ = req("/api/timer", {"action": "reset"}); time.sleep(1.5)
c, s, _ = req("/api/undo", {})
check("a reset clock can be undone: still running, and the seconds talked since the reset count too", c == 200 and s["timer"]["elapsed"] > 2.7 and s["timer"]["running"] and s["undone"] == "clock reset", (c, s.get("undone"), s["timer"]))
c, d, _ = req("/api/undo", {})
check("but only once", c == 400)
c, s, _ = req("/api/rehearsal", {"action": "start", "back": {"slide": 4, "click": 0}}); press("first"); time.sleep(0.3)
c, s, _ = req("/api/undo", {})
check("a rehearsal started by mistake mid-talk can be undone: clock and slide come back", c == 200 and not s["timer"]["rehearsing"] and s["timer"]["elapsed"] > 1.2 and s["slide"] == 4, (s["timer"], s["slide"]))
req("/api/timer", {"action": "reset"}); req("/api/timer", {"action": "pause"})

# ---- new codes ----
c, d, _ = req("/api/host/rotate?h=" + H, {}, key=None); check("new codes made", c == 200)
c, _, _ = req("/api/state?since=0"); check("old key refused after new codes", c == 403)
c, d, _ = req("/api/host/info?h=" + H, key=None); check("new number differs; host page still works", d["pin"] != PIN and len(d["pin"]) == 6)
sess2 = json.load(open(DATA + "/cuewand_session.json")); check("new codes saved", sess2["key"] != K and sess2["pin"] == d["pin"])
K = sess2["key"]
c, s = press("end"); check("end with the new key", c == 200 and s["show"] == "idle")

# ---- a connection that sends nothing is closed, it does not hold a thread for ever ----
cut = socket.create_connection(("127.0.0.1", PORT))     # a request whose body is cut off half-way
cut.sendall(b"POST /api/cmd HTTP/1.1\r\nHost: x\r\nX-Cuewand-Key: " + K.encode() + b"\r\nContent-Length: 40\r\n\r\n{\"cmd\":"); cut.shutdown(socket.SHUT_WR); time.sleep(0.4); cut.close()
sk = socket.create_connection(("127.0.0.1", PORT)); sk.sendall(b"GET /api/ping HTTP/1.1\r\nHost: x\r\n")  # never finishes
c, d, _ = req("/api/ping", key=None); check("server answers others while one connection stalls", c == 200)
sk.close()
# ---- found by red-teaming: the pairing page is this computer's alone ----
def raw(path, headers=None):
    r = urllib.request.Request(B + path, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=10) as f:
            return f.status, f.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
c, _ = raw("/host?h=" + H, {"Cf-Ray": "8a1b2c3d4e5f6a7b-AMS"}); check("the pairing page refuses the internet link: only this computer opens it", c == 403)
c, _ = raw("/api/host/info?h=" + H, {"Cf-Connecting-Ip": "203.0.113.9"}); check("and so do its buttons and the codes behind them", c == 403)
c, _ = raw("/api/host/info?h=" + H); check("this computer itself still gets them", c == 200)
# ---- a chunked request cannot hide a second request inside it ----
sk = socket.create_connection(("127.0.0.1", PORT)); sk.settimeout(5)
sk.sendall(b"POST /api/pair HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\nGET /api/ping HTTP/1.1\r\nHost: x\r\n\r\n")
got = b""
try:
    while True:
        part = sk.recv(4096)
        if not part:
            break
        got += part
except socket.timeout:
    pass
sk.close()
check("a chunked request is refused, and nothing hidden in it is answered", got.startswith(b"HTTP/1.1 400") and got.count(b"HTTP/1.1 ") == 1, got[:100])
# ---- a press the phone gave up on can never land later ----
req("/api/cmd", {"cmd": "start", "from": "first", "id": "rt-start"}); time.sleep(0.5)
s0 = req("/api/state?since=0")[1]
c, d, _ = req("/api/press?id=gaveup-1&void=1"); check("a press the phone gave up on is cancelled before the phone says it did not arrive", d.get("result") == "void", d)
c, s = press("next", pid="gaveup-1"); time.sleep(0.3); s1 = req("/api/state?since=0")[1]
check("so if it still arrives later, it is refused and nothing moves", (s.get("press") or {}).get("result") == "void" and (s1["slide"], s1["click"]) == (s0["slide"], s0["click"]), (s.get("press"), s0["slide"], s1["slide"], s1["click"]))
c, s = press("next", pid="landed-1"); c, d, _ = req("/api/press?id=landed-1&void=1")
check("a press that did arrive is not cancelled after the fact", d.get("result") == "done", d)
# ---- a picture asked for another deck is never served as this one's ----
st = req("/api/state?since=0")[1]
c, _ = raw(f"/api/slide/1.jpg?d={st['deckId']}&k={K}"); check("a slide picture of this deck", c == 200)
c, _ = raw(f"/api/slide/1.jpg?d=another-deck&k={K}"); check("a picture asked for by another deck's id is not served", c == 404)
press("end")
# ---- a second copy started by mistake, even one that would move to another port, does not run ----
import subprocess
from common import ROOT
p2 = subprocess.run([sys.executable, os.path.join(ROOT, "cuewand.py"), "--demo", "--no-browser", "--port", str(PORT + 7)],
                    env=dict(os.environ, CUEWAND_DATA=DATA, BROWSER="true"), capture_output=True, text=True, timeout=30)
check("a second Cuewand with the same folder does not start, even on a free port", "already running" in p2.stdout and f":{PORT}/host" in p2.stdout, p2.stdout[-300:])
log = open(DATA + "/cuewand.log").read()
check("log: presses with id, base, result and place", "press next [dup-1]" in log and "from slide 2 step 3" in log and ": stale in" in log, "")
check("log: phone connection with where from", "phone t1 connected from 127.0.0.1 on the local network" in log)
check("log: late press", "landed late" in log)
check("log: refused requests", "refused /api/state" in log)
check("log: wrong pairing numbers, one line each", log.count("pairing number: a wrong one") >= 16)
check("log: a request cut off half-way is not blamed on PowerPoint", "PowerPoint did not answer in time" not in log)
# ---- damaged saved files never stop Cuewand from starting ----
sv = json.load(open(DATA + "/cuewand_session.json"))
sv["timer"] = {"dur": float("inf"), "marks": [float("inf")], "acc": 1, "running": True, "wall": float("nan")}
sv["pace"] = {"spent": {"1": float("inf")}, "cur": float("inf"), "mark": 1}
json.dump(sv, open(DATA + "/cuewand_session.json", "w"))
open(DATA + "/cuewand_rehearsals.json", "w").write("[" * 200000 + "]" * 200000)
try:
    sess3 = server(keep=True)
    K = sess3["key"]
    c, s, _ = req("/api/state?since=0")
    check("damaged saved files (infinite numbers, nesting too deep) are ignored: Cuewand starts and answers", c == 200 and 30 <= s["timer"]["dur"] <= 12 * 3600, s.get("timer"))
except SystemExit as e:
    check("damaged saved files (infinite numbers, nesting too deep) are ignored: Cuewand starts and answers", False, str(e))
print(f"\n{ok} passed, {fails} failed")
sys.exit(1 if fails else 0)
