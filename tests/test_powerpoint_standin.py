"""Run the Windows backend (Cuewand 2.2) against a stand-in PowerPoint object model.
Checks control flow and internal consistency only; it is not real PowerPoint."""
import ctypes, os, sys, tempfile, time, types
os.environ["CUEWAND_DATA"] = tempfile.mkdtemp(prefix="wintest_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXPORTS = []    # (slide, was a slide show running?)
COUNT = {"next": 0, "lookups": 0, "absorbed": 0}
FRONT = {"class": "Chrome_WidgetWin_1", "editor": 0}   # the window in front; is PowerPoint's editor on screen?


class Strict:
    """Attribute access fails loudly for any name the stand-in does not define."""
    def __getattr__(self, n): raise AttributeError(f"{type(self).__name__} has no member {n!r}")


class ComError(Exception):
    def __init__(self, hr): super().__init__(hr); self.hresult = hr


calls = {"cursor": [], "keys": [], "mouse": []}
PIDS = {0xF00D: 4242, 0x50A1E: 4242}      # window -> program: the window in front and the slide show
GRANT = {"front": True}                   # does Windows let Cuewand bring the show to the front?


class FnBox:
    def __init__(s, fn): s.fn = fn
    def __call__(s, *a): return s.fn(*a)


def _classname(hwnd, buf, n):
    buf.value = FRONT["class"]
    return len(FRONT["class"])


class U32(Strict):
    def __init__(s):
        s.GetClientRect = FnBox(lambda hwnd, ref: (setattr(ref._obj, "right", 1920), setattr(ref._obj, "bottom", 1200), 1)[2])
        s.ClientToScreen = FnBox(lambda hwnd, ref: (setattr(ref._obj, "x", 1920), setattr(ref._obj, "y", 0), 1)[2])
        s.SetCursorPos = FnBox(lambda x, y: calls["cursor"].append((x, y)))
        s.GetSystemMetrics = lambda i: (1920, 1080)[i]
        s.keybd_event = lambda vk, sc, fl, ex: calls["keys"].append((vk, fl))
        s.GetForegroundWindow = FnBox(lambda: 0xF00D)
        s.GetClassNameW = FnBox(_classname)
        s.FindWindowW = FnBox(lambda cls, title: FRONT["editor"] if cls == "PPTFrameClass" else 0)
        s.mouse_event = lambda fl, x, y, d, ex: calls["mouse"].append(fl)
        s.GetWindowThreadProcessId = FnBox(lambda hwnd, ref: (setattr(ref._obj, "value", PIDS.get(hwnd, 0)), 1)[1])
        s.SetForegroundWindow = FnBox(lambda hwnd: PIDS.__setitem__(0xF00D, PIDS[0x50A1E]) if GRANT["front"] else None)


ctypes.windll = types.SimpleNamespace(user32=U32())


# ---- stand-in PowerPoint ----
class Coll(Strict):
    def __init__(s, items): s.items = items
    @property
    def Count(s): return len(s.items)
    def __call__(s, i): return s.items[i - 1]
    def __iter__(s): return iter(s.items)
class TR(Strict):
    def __init__(s, t): s.Text = t
class TF(Strict):
    def __init__(s, t): s.TextRange = TR(t); s.HasText = -1 if t else 0
class PF(Strict):
    def __init__(s, t): s.Type = t
class Shape(Strict):
    def __init__(s, typ, ph, text): s.Type, s.PlaceholderFormat, s.HasTextFrame, s.TextFrame = typ, PF(ph), True, TF(text)
class NoPH(Strict):
    Type = 1
    HasTextFrame = 0
    @property
    def PlaceholderFormat(s): raise ComError(-2147024809)
class Shapes(Coll):
    def __init__(s, title): super().__init__([]); s.HasTitle = bool(title); s._t = title
    @property
    def Title(s): return Shape(14, 1, s._t)
class NotesPage(Strict):
    def __init__(s, notes): s._shapes = Coll([NoPH(), Shape(14, 1, "thumb"), Shape(14, 2, notes)]); s.reads = 0
    @property
    def Shapes(s): s.reads += 1; return s._shapes
def notes_reads(deck_slides): return sum(getattr(x.NotesPage, "reads", 0) for x in deck_slides)
class TextBoxNotes(Strict):
    """Notes typed into a plain text box, with a slide-number placeholder beside it."""
    def __init__(s, notes): s.Shapes = Coll([Shape(14, 13, "5"), Shape(17, 0, notes)])
class Trans(Strict):
    def __init__(s, h): s.Hidden = -1 if h else 0; s.AdvanceOnTime = 0; s.AdvanceTime = 0.0; s.EntryEffect = 0; s.Duration = 0.0
class Timing(Strict):
    def __init__(s, t): s.TriggerType = t
class Effect(Strict):
    def __init__(s, t): s.Timing = Timing(t)
class Sequence(Strict):
    def __init__(s, items): s.items = items
    @property
    def Count(s): return len(s.items)
    def Item(s, i): return s.items[i - 1]
class TimeLine(Strict):
    def __init__(s, clicks, auto=0): s.MainSequence = Sequence([Effect(3)] * auto + [Effect(1), Effect(2)] * clicks)
class Slide(Strict):
    def __init__(s, i, title, notes, hidden, clicks):
        s.SlideIndex, s.SlideID, s.clicks = i, 255 + i, clicks
        s.NotesPage, s.SlideShowTransition, s.Shapes = NotesPage(notes), Trans(hidden), Shapes(title)
        s.TimeLine = TimeLine(clicks)
        s.exports = []
    slow = 0
    fail = 0
    def Export(s, path, fmt, w, h):
        EXPORTS.append((s.SlideIndex, bool(APP.SlideShowWindows.Count)))
        if s.slow: time.sleep(s.slow)
        if s.fail: s.fail -= 1; raise ComError(-2147467259)
        s.exports.append((fmt, w, h)); open(path, "wb").write(b"\xff\xd8JPEG" + str((s.SlideIndex, w, h)).encode())
class View(Strict):
    appear = {}     # slide -> seconds after it comes up in which a press only finishes it appearing
    stall = {}      # slide -> seconds after it comes up in which PowerPoint answers nothing (large GIFs)
    stuck = set()   # slides on which Next and Back never move the show
    def __init__(s, pres): s.pres, s.pos, s.click, s.State, s.LaserPointerEnabled, s.exited, s.arrived = pres, 1, 0, 1, False, False, time.monotonic()
    def __getattribute__(s, n):      # a view whose show has closed answers nothing, as in PowerPoint
        if n in ("State", "Slide", "GetClickIndex", "Next", "Previous"):
            g = lambda k: object.__getattribute__(s, k)
            if n != "Next" and n != "Previous" and g("exited"): raise ComError(-2147188720)
            left = type(s).stall.get(g("pos"), 0) - (time.monotonic() - g("arrived"))
            if left > 0: time.sleep(left)
        return object.__getattribute__(s, n)
    def _came(s): s.arrived = time.monotonic()
    def _absorbs(s):
        if s.pos in type(s).stuck: COUNT["absorbed"] += 1; return True
        if s.click == 0 and time.monotonic() - s.arrived < type(s).appear.get(s.pos, 0):
            COUNT["absorbed"] += 1; s.arrived = -1e9; return True     # finished appearing
        return False
    def _vis(s, i, step):
        while 1 <= i <= s.pres.Slides.Count and s.pres.Slides(i).SlideShowTransition.Hidden: i += step
        return i
    @property
    def Slide(s):
        if s.State == 5: raise ComError(-2147188160)
        return s.pres.Slides(s.pos)
    busy = 0        # answer "busy, ask again" this many times
    glitch = 0      # move the show, then report an error (once per count)
    lag = 0.0       # seconds PowerPoint takes over one Next
    def Next(s):
        COUNT["next"] += 1
        if s.exited: raise ComError(-2147188160)
        if type(s).busy > 0: type(s).busy -= 1; raise ComError(-2147418111)
        if type(s).lag: time.sleep(type(s).lag)
        if s.State == 1 and s._absorbs(): return
        sl = s.pres.Slides(s.pos)
        if s.click < sl.clicks: s.click += 1
        else:
            n = s._vis(s.pos + 1, 1)
            if n > s.pres.Slides.Count: s.State = 5
            else: s.pos, s.click = n, 0; s._came()
        if type(s).glitch > 0: type(s).glitch -= 1; raise ComError(-2147467259)
    def Previous(s):
        if s.State == 5: s.State = 1; return
        if s._absorbs(): return
        if s.click: s.click -= 1; return
        n = s._vis(s.pos - 1, -1)
        if n >= 1: s.pos = n; s._came()
    def GotoSlide(s, n): s.pos, s.click, s.State = n, 0, 1; s._came()
    def First(s): s.GotoSlide(1)
    def Last(s): s.GotoSlide(s.pres.Slides.Count)
    def Exit(s): s.exited = True; APP.SlideShowWindows.items.clear()
    def GetClickIndex(s): return s.click
    def GetClickCount(s): return s.pres.Slides(s.pos).clicks
class Win(Strict):
    view_class = None
    def __init__(s, pres): s._view, s.Presentation, s.HWND = (Win.view_class or View)(pres), pres, 0x50A1E
    @property
    def View(s): COUNT["lookups"] += 1; return s._view
class SSS(Strict):
    def __init__(s, pres): s.pres = pres; s.AdvanceMode = 2
    def Run(s): w = Win(s.pres); APP.SlideShowWindows.items[:] = [w]; return w
class PageSetup(Strict): SlideWidth, SlideHeight = 960.0, 540.0
class Sections(Strict):
    def __init__(s, rows): s.rows = rows
    @property
    def Count(s): return len(s.rows)
    def Name(s, i): return s.rows[i - 1][0]
    def FirstSlide(s, i): return s.rows[i - 1][1]
    def SlidesCount(s, i): return s.rows[i - 1][2]
class Pres(Strict):
    def __init__(s, name, slides):
        s.Name, s.FullName, s.Slides, s.PageSetup = name, "C:\\Talks\\" + name, Coll(slides), PageSetup()
        s.Saved = -1
        s.SlideShowSettings = SSS(s)
class EditView(Strict):
    def __init__(s, slide): s.Slide = slide
class EditWin(Strict):
    def __init__(s, slide): s.View = EditView(slide)
class App(Strict):
    Version = "16.0"
    def __init__(s): s.SlideShowWindows, s.Presentations, s.dead = Coll([]), Coll([]), False
    def __getattribute__(s, n):
        if n in ("SlideShowWindows", "Presentations", "ActivePresentation", "ActiveWindow") and object.__getattribute__(s, "dead"):
            raise ComError(-2147023174)  # RPC server unavailable
        return object.__getattribute__(s, n)
    @property
    def ActivePresentation(s): return s.Presentations(1)
    @property
    def ActiveWindow(s): return EditWin(s.Presentations(1).Slides(3))
APP = None
ASKED = []      # how Cuewand asked comtypes for PowerPoint
def get_active(progid, interface=None, dynamic=False):
    ASKED.append((progid, interface, dynamic))
    if APP is None: raise ComError(-2147221021)   # MK_E_UNAVAILABLE: PowerPoint not running
    return APP
ct = types.ModuleType("comtypes"); ctc = types.ModuleType("comtypes.client")
ct.CoInitialize = lambda: None; ct.__version__ = "stand-in"; ctc.GetActiveObject = get_active; ct.client = ctc
sys.modules.update({"comtypes": ct, "comtypes.client": ctc})

import cuewand, logging
LOG = os.path.join(os.environ["CUEWAND_DATA"], "wintest.log")
logging.basicConfig(filename=LOG, level=logging.DEBUG, format="%(message)s")
cuewand.PIC_RETRY_GAP = 0.5
hub = cuewand.Hub(); be = cuewand.WindowsBackend(hub); be.start()
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    ok += bool(cond); bad += not cond
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
def settle(t=0.6): time.sleep(t); return hub.snapshot()
def logged(text): return text in open(LOG).read()

s = settle(); check("no PowerPoint -> arrow-key mode", s["mode"] == "keys" and s["show"] == "none" and s["link"] == "ok", be.describe())
check("pairing page, nothing open: says to open the deck and that Cuewand finds it by itself", "Open your deck in PowerPoint" in be.describe() and "finds it by itself" in be.describe() and "arrow keys" in be.describe(), be.describe())
r = [be.command("next", {}), be.command("prev", {}), be.command("black", {})]
check("keys: Right, Left, B pressed and released; each reported done", calls["keys"] == [(0x27, 1), (0x27, 3), (0x25, 1), (0x25, 3), (0x42, 0), (0x42, 2)] and r == ["done"] * 3, (calls["keys"], r))
be.laser(0.5, 0.5, True); check("keys: pad maps to main screen", calls["cursor"][-1] == (959, 539), calls["cursor"][-1]); be.laser(0.5, 0.5, False)

# PowerPoint has a window but gives Cuewand no way in (no deck, Protected View, administrator)
FRONT["editor"] = 0xBEEF; s = settle(4.6)
check("PowerPoint on screen but not answering: said so on the phone and the pairing page", s["link"] == "blocked" and "does not answer" in be.describe(), (s["link"], be.describe()))
FRONT["editor"] = 0; s = settle(1.4); check("and cleared when that window goes", s["link"] == "ok", s["link"])

slides = [Slide(1, "Title", "Hello\rworld\x0bline", False, 0), Slide(2, "Methods", "", False, 2), Slide(3, "Results", "R notes", False, 0),
          Slide(4, "Backup", "hidden one", True, 0), Slide(5, "", "last", False, 0)]
class Flaky(Slide):
    """Notes page that is unavailable for the first two reads."""
    fails = 2
    def __getattribute__(s, n):
        if n == "NotesPage" and type(s).fails > 0:
            type(s).fails -= 1; raise ComError(-2147418111)
        return object.__getattribute__(s, n)
slides[2] = Flaky(3, "Results", "R notes", False, 0)
slides[4].NotesPage = TextBoxNotes("typed in a text box")
slides[1].SlideShowTransition.AdvanceOnTime = -1; slides[1].SlideShowTransition.AdvanceTime = 6.23
slides[3].fail = 1      # its first picture fails
APP = App(); deck = Pres("Talk.pptx", slides); APP.Presentations.items.append(deck); FRONT["editor"] = 0xBEEF
s = settle(1.2)
check("PowerPoint is found through comtypes, late-bound with its type information", ASKED and ASKED[-1] == ("PowerPoint.Application", None, True), ASKED[-1:])
check("deck open, no show -> idle", s["show"] == "idle" and s["deck"] == "Talk.pptx" and s["total"] == 5 and s["link"] == "ok")
check("a picture that fails is not counted ready, and the pairing page keeps waiting", s["pics"] == [4, 5, 0] and "Preparing slide pictures: 4 of 5" in be.describe(), (s["pics"], be.describe()))
s = settle(1.6)
check("the failed picture is tried again and made", s["pics"] == [5, 5, 0] and sorted(EXPORTS) == [(1, False), (2, False), (3, False), (4, False), (4, False), (5, False)] and slides[0].exports == [("JPG", 960, 540)], (s["pics"], EXPORTS))
check("pairing page says the pictures are ready", "Slide pictures are ready" in be.describe(), be.describe())
check("pairing page names the deck it found, and with one deck open says nothing about several", be.describe().startswith("Found your deck: Talk.pptx.") and "decks are open" not in be.describe(), be.describe())
check("titles and notes read ahead of the talk too; flaky notes retried", be.outline_cache is not None and [r["notes"] for r in be.outline_cache] == [True, False, True, True, True], be.outline_cache and [r["notes"] for r in be.outline_cache])
sig0 = s["deckId"]

# no slide show: a key press must not land in the deck being edited
n = len(calls["keys"]); FRONT["class"] = "PPTFrameClass"; r = be.command("next", {})
check("idle with PowerPoint's editor in front: Next does nothing, and says 'idle'", r == "idle" and len(calls["keys"]) == n, (r, calls["keys"][n:]))
FRONT["class"] = "AcrobatSDIWindow"; r = be.command("next", {})
check("idle with another program in front (a PDF, say): the arrow key is sent", r == "done" and len(calls["keys"]) == n + 2, r)
FRONT["class"] = "PPTFrameClass"

# an edit that is not saved: notes and titles are noticed without any press
deck.Saved = 0; n0 = len(EXPORTS); s = settle(1.8)
check("first edit while idle remakes the pictures", len(EXPORTS) == n0 + 5 and s["pics"] == [5, 5, 0] and s["deckId"] != sig0, (len(EXPORTS) - n0, s["pics"]))
sig1 = s["deckId"]; slides[0].NotesPage = NotesPage("Rewritten opening"); slides[1].Shapes = Shapes("Methods, revised"); s = settle(3.0)
o = be.outline()
check("a second edit, still unsaved: notes and title are read again within seconds", be.notes_cache.get(1) == "Rewritten opening" and o[1]["title"] == "Methods, revised" and logged("slide 1 was edited"), (be.notes_cache.get(1), o[1]["title"]))
n0 = len(EXPORTS); be.remake_pictures(); s = settle(1.2)
check("'Remake the slide pictures' makes all of them again", len(EXPORTS) == n0 + 5 and s["pics"] == [5, 5, 0] and s["deckId"] == sig1, len(EXPORTS) - n0)
deck.Saved = -1; settle(0.5); n0 = len(EXPORTS); deck.Saved = 0; s = settle(1.6)
check("save, then edit again: pictures remade again", len(EXPORTS) == n0 + 5 and s["deckId"] != sig1, len(EXPORTS) - n0)
sig0 = s["deckId"]; EXPORTS.clear()
# a second deck is opened and comes to the front, then the first one again
other = Pres("Other.pptx", [Slide(i, f"O{i}", "", False, 0) for i in range(1, 4)]); other.Saved = 0
APP.Presentations.items.insert(0, other); s = settle(1.0)
check("a second deck in front: its pictures are made", s["deck"] == "Other.pptx" and s["pics"] == [3, 3, 0] and len(EXPORTS) == 3, (s["deck"], s["pics"], len(EXPORTS)))
check("two decks open: the pairing page names the one in front and says how to switch", be.describe().startswith("Found your deck: Other.pptx.") and "2 decks are open: Cuewand uses the one in front" in be.describe(), be.describe())
APP.Presentations.items.remove(other); s = settle(0.8)
check("back to the first deck: its pictures are still there, nothing is made again", s["deck"] == "Talk.pptx" and s["deckId"] == sig0 and s["pics"] == [5, 5, 0] and len(EXPORTS) == 3 and be.slide_image(2) is not None, (s["deck"], s["pics"], len(EXPORTS)))
check("one deck again: the note about several decks is gone", be.describe().startswith("Found your deck: Talk.pptx.") and "decks are open" not in be.describe(), be.describe())
EXPORTS.clear()

r = be.command("start", {"from": "current"}); s = hub.snapshot()
check("start from selected slide (3)", r == "done" and s["show"] == "running" and s["slide"] == 3 and s["mode"] == "powerpoint", s["slide"])
check("notes there at once, next skips the hidden slide, pictures flagged ready", s["notes"] == "R notes" and s["next"] == 5 and s["pic"] and s["nextPic"], (s["notes"], s["next"], s["pic"]))
check("aspect from page setup", abs(s["aspect"] - 16 / 9) < 1e-3)
be.command("first", {}); s = hub.snapshot(); check("the rewritten notes are what the show displays", s["notes"] == "Rewritten opening", repr(s["notes"]))
check("slide without its own timer says so", s["auto"] == 0)

# ---- presses: exactly once, on the slide they were made from ----
r = be.command("next", {"base": {"slide": 1, "click": 0}}); s = hub.snapshot()
check("Next from slide 1 -> slide 2 with 2 builds", r == "done" and s["slide"] == 2 and s["clicks"] == 2 and s["click"] == 0)
check("a slide that PowerPoint moves on by itself is flagged with its seconds", s["auto"] == 6.2, s["auto"])
c0 = COUNT["next"]; r = be.command("next", {"base": {"slide": 1, "click": 0}}); s = hub.snapshot()
check("a press made from slide 1 arriving when the show is on slide 2: refused as stale, PowerPoint not asked to move", r == "stale" and s["slide"] == 2 and s["click"] == 0 and COUNT["next"] == c0, (r, s["slide"], s["click"]))
r = be.command("prev", {"base": {"slide": 2, "click": 1}}); s = hub.snapshot(); check("stale Back refused too", r == "stale" and s["slide"] == 2)
c0 = dict(COUNT); time.sleep(2.0); check("two seconds of watching: the show's objects are looked up at most once", COUNT["lookups"] - c0["lookups"] <= 1, COUNT["lookups"] - c0["lookups"])
View.busy = 3; c0 = COUNT["next"]; t0 = time.monotonic(); r = be.command("next", {"base": {"slide": 2, "click": 0}}); took = time.monotonic() - t0; s = hub.snapshot()
check("PowerPoint says busy three times: asked again, the press lands once", r == "done" and s["click"] == 1 and COUNT["next"] - c0 == 4 and 0.4 < took < 1.2, (s["click"], COUNT["next"] - c0, round(took, 2)))
be.command("prev", {}); s = hub.snapshot(); check("and Back undoes it", s["click"] == 0)
View.busy = 99
try: be.command("next", {}); err = None
except Exception as e: err = getattr(e, "hresult", None)
View.busy = 0; s = hub.snapshot(); check("busy for longer than that: the press fails as busy, nothing moves", err == -2147418111 and s["click"] == 0, err)
View.glitch = 1; c0 = COUNT["next"]; r = be.command("next", {"base": {"slide": 2, "click": 0}}); s = hub.snapshot()
check("PowerPoint moves the show but reports an error: not sent a second time, reported as done, and logged", r == "done" and s["slide"] == 2 and s["click"] == 1 and COUNT["next"] - c0 == 1 and logged("moved the show and then reported an error") and logged("next: PowerPoint answered with an error"), (r, s["click"], COUNT["next"] - c0))
# a press PowerPoint is slow to carry out: the phone is told 'pending', and hears when it lands
View.lag = 1.0; got = []
try: be._call(0, lambda: be._command("next", {"base": {"slide": 2, "click": 1}}), timeout=0.3, label="next", on_finish=lambda res, err: got.append((res, err))); res = "returned"
except cuewand.PressPending: res = "pending"
except TimeoutError: res = "timeout"
mid = hub.snapshot()["click"]; time.sleep(1.3); View.lag = 0.0; s = hub.snapshot()
check("a press PowerPoint has started but not finished is 'pending', not 'failed'; it lands once and reports", res == "pending" and mid == 1 and s["click"] == 2 and got == [("done", None)], (res, mid, s["click"], got))
be.command("prev", {}); s = hub.snapshot()
be.command("black", {}); s = hub.snapshot(); view = APP.SlideShowWindows(1).View
check("black screen", s["black"] and view.State == 3)
be.command("next", {"base": {"slide": 2, "click": 1}}); s = hub.snapshot(); check("Next from black restores without advancing", not s["black"] and s["click"] == 1 and view.State == 1)
img = be.slide_image(3, 1200); check("picture served during the show without asking PowerPoint", img[1] == "image/jpeg" and EXPORTS == [])
o = be.outline(); check("outline titles + hidden flag", [x["title"] for x in o] == ["Title", "Methods, revised", "Results", "Backup", ""] and o[3]["hidden"], o)
# laser: 1920x1200 window on a second monitor at x=1920; 16:9 slide letterboxed to 1920x1080, top offset 60
be.laser(0.0, 0.0, True); time.sleep(0.4)
check("laser top-left lands on the slide corner of monitor 2", calls["cursor"][-1] == (1920, 60) and view.LaserPointerEnabled is True, calls["cursor"][-1])
be.laser(1.0, 1.0, True); check("laser bottom-right", calls["cursor"][-1] == (3839, 1139), calls["cursor"][-1])
be.laser(1.0, 1.0, False); time.sleep(0.4); check("laser off on release", view.LaserPointerEnabled is False)
be.laser(0.5, 0.5, True); time.sleep(0.4); on = view.LaserPointerEnabled; time.sleep(2.8)
check("laser auto-off when phone goes quiet", on is True and view.LaserPointerEnabled is False)

# zoom on the big screen (a trial): the + and - keys of the number pad, as many minuses as pluses
FRONT["class"] = "screenClass"      # the slide show is the window in front
k0 = len(calls["keys"]); r = be.zoom("out")
check("zoom out at normal size sends nothing (minus would show all slides to the room)", r == "fit" and len(calls["keys"]) == k0, r)
r1, r2 = be.zoom("in"), be.zoom("in")
check("zoom in twice: two pluses, key down and up", (r1, r2) == ("done", "done") and calls["keys"][k0:] == [(0x6B, 0), (0x6B, 2)] * 2 and be.zoom_level == 2, calls["keys"][k0:])
m0 = len(calls["mouse"]); be.pan("down", 0.0, 0.0); be.pan("move", 1.0, 1.0); be.pan("up", 1.0, 1.0)
check("zoomed in, the finger drags the slide: button down on the slide, moved, let go", calls["mouse"][m0:] == [2, 4] and calls["cursor"][-1] == (3839, 1139), calls["mouse"][m0:])
be.pan("down", 0.5, 0.5); time.sleep(3.0)
check("the phone goes quiet mid-drag: the button is let go by itself", calls["mouse"][-1] == 4 and not be.pan_down, calls["mouse"][-2:])
k0 = len(calls["keys"]); r = be.zoom("fit")
check("Fit: as many minuses as pluses, no more", r == "done" and calls["keys"][k0:] == [(0x6D, 0), (0x6D, 2)] * 2 and be.zoom_level == 0, calls["keys"][k0:])
m0 = len(calls["mouse"]); r = be.pan("down", 0.5, 0.5)
check("not zoomed in: no mouse press (it would be a click, and move the show on)", r == "not-zoomed" and calls["mouse"][m0:] == [])
PIDS[0xF00D] = 777; GRANT["front"] = False; k0 = len(calls["keys"]); r = be.zoom("in")
check("another program in front, and Windows will not hand the front over: no key is sent", r == "not-front" and len(calls["keys"]) == k0, r)
GRANT["front"] = True; r = be.zoom("in")
check("when Windows does hand it over, the zoom goes to the show", r == "done" and be.zoom_level == 1, r)
FRONT["class"] = "PPTFrameClass"; k0 = len(calls["keys"]); r = be.zoom("in")
check("PowerPoint's editor in front: no key (a plus would land in the deck)", r == "not-front" and len(calls["keys"]) == k0, r)
FRONT["class"] = "screenClass"; be.zoom("fit"); FRONT["class"] = "PPTFrameClass"
be.command("goto", {"n": 99}); s = hub.snapshot(); check("goto out of range ignored", s["slide"] == 2)

# during a show the notes come from memory: reading a notes page then kept a real PowerPoint busy for 4 s
n0 = notes_reads(slides); be.command("last", {}); settle(1.0); be.command("goto", {"n": 1}); s = settle(1.0)
check("during the show no notes page is read (that kept a real PowerPoint busy for seconds)", notes_reads(slides) == n0 and s["notes"] == "Rewritten opening", (notes_reads(slides) - n0, s["notes"]))
be.command("last", {}); s = settle(0.3)
o2 = be.outline(); check("outline says which slides have notes and pictures", [x["notes"] for x in o2] == [True, False, True, True, True] and all(x["pic"] for x in o2), [x["notes"] for x in o2])
be.command("next", {}); s = hub.snapshot(); check("end of show reported", s["show"] == "ended" and s["slide"] == 5)
be.command("next", {}); s = hub.snapshot(); check("Next at end does not exit", s["show"] == "ended" and not view.exited)
be.command("prev", {}); s = hub.snapshot(); check("Back from end returns to last slide", s["show"] == "running" and s["slide"] == 5)
r = be.command("end", {}); s = hub.snapshot(); check("exit -> idle", s["show"] == "idle" and view.exited)
be.command("start", {}); be.command("next", {}); s0 = hub.snapshot(); be.command("prev", {})
check("a press right after a restart goes to the new show, not the old one", s0["slide"] == 2 and s0["show"] == "running", (s0["show"], s0["slide"]))
s = settle(0.5); check("second show reuses the pictures: nothing exported again", s["deckId"] == sig0 and s["slide"] == 1 and EXPORTS == [] and s["pic"], len(EXPORTS))
# a press PowerPoint cannot take in time is dropped, not done late
ran = []; be.q.put((0, -1, cuewand._Job(lambda: time.sleep(1.2), "stall")))
try: be._call(0, lambda: ran.append(1), timeout=0.4, label="next"); late = False
except TimeoutError: late = True
time.sleep(1.5); check("a press that PowerPoint never started on is not carried out later", late and ran == [] and logged("dropped a next"))
# one odd answer is not the end of the show
v3 = APP.SlideShowWindows(1)
class Closing(Win):
    @property
    def View(s): raise ComError(-2147352567)
v3._view.exited = True; be.cv = None; time.sleep(0.25); v3._view.exited = False; s = settle(0.5)
check("one failed read during a show keeps the show on the phone", s["show"] == "running" and s["slide"] == 1, s["show"])
# the window is still listed while the show closes: no error, no reconnect
v3._view.exited = True; APP.SlideShowWindows.items[:] = [Closing.__new__(Closing)]; s = settle(0.9)
check("a closing slide show reads as idle, PowerPoint stays connected", s["show"] == "idle" and be.app is not None, s["show"])
v3._view.exited = False; APP.SlideShowWindows.items[:] = [v3]; s = settle(0.5); check("and is picked up again", s["show"] == "running")
# PowerPoint busy: keep state. PowerPoint gone: fall back to keys.
v2 = APP.SlideShowWindows(1).View; v2.__class__ = type("BusyView", (View,), {"GetClickIndex": lambda s: (_ for _ in ()).throw(ComError(-2147418111))})
s = settle(0.6); check("click-count failure tolerated", s["show"] == "running")
APP.dead = True; s = settle(0.8); check("PowerPoint vanished -> arrow-key mode", s["show"] == "none" and s["mode"] == "keys", be.describe())
FRONT["editor"] = 0; FRONT["class"] = "screenClass"
n = len(calls["keys"]); r = be.command("next", {}); check("keys work again after PowerPoint vanished", r == "done" and len(calls["keys"]) == n + 2)
APP = None; s = settle(1.2)
APP = App(); APP.Presentations.items.append(deck); s = settle(1.6); check("PowerPoint reopened -> found again", s["show"] == "idle")
be.close(); check("temp pictures removed", not os.path.exists(be.cache_dir))

# a picture that can never be made is given up on, and said so
EXPORTS.clear(); slidesB = [Slide(i, f"B{i}", "n", False, 0) for i in range(1, 4)]; slidesB[1].fail = 99
APP = App(); deckB = Pres("Broken.pptx", slidesB); APP.Presentations.items.append(deckB)
hubB = cuewand.Hub(); beB = cuewand.WindowsBackend(hubB); beB.start(); sB = None
for _ in range(40):
    time.sleep(0.2); sB = hubB.snapshot()
    if sB["pics"][2]: break
check("three failed tries: counted as given up, the rest are ready, and the page says which", sB["pics"] == [2, 3, 1] and [n for n, _ in EXPORTS].count(2) == 3 and "1 could not be made" in beB.describe(), (sB["pics"], EXPORTS, beB.describe()))
deckB.SlideShowSettings.AdvanceMode = 1; slidesB[0].SlideShowTransition.AdvanceOnTime = -1; slidesB[0].SlideShowTransition.AdvanceTime = 4.0
beB.command("start", {}); sB = hubB.snapshot()
check("'Use timings' switched off in the deck: slides are not flagged as moving on by themselves", sB["show"] == "running" and sB["auto"] == 0, sB["auto"])
beB.command("next", {}); sB = hubB.snapshot(); check("a slide whose picture could not be made says so", sB["slide"] == 2 and sB["pic"] is False and beB.slide_image(2) is None)
n2 = [n for n, _ in EXPORTS].count(2); beB.command("end", {}); time.sleep(2.6)
check("after the show, a picture that could not be made is tried again", [n for n, _ in EXPORTS].count(2) > n2, ([n for n, _ in EXPORTS].count(2), n2))
beB.close()

# a show that is already running when Cuewand starts, in a deck whose slide 2 renders slowly
EXPORTS.clear(); slides2 = [Slide(i, f"S{i}", "n", False, 0) for i in range(1, 7)]; slides2[1].slow = 0.9
APP = App(); deck2 = Pres("Gifs.pptx", slides2); APP.Presentations.items.append(deck2); deck2.SlideShowSettings.Run()
hubL = cuewand.Hub(); beL = cuewand.WindowsBackend(hubL); beL.last_press = time.monotonic(); beL.start(); time.sleep(0.8)
check("no picture is made within 1.5 s of a press", EXPORTS == [], EXPORTS)
time.sleep(3.5); sL = hubL.snapshot()
check("mid-show: current, then next, then stop for good after one slow picture", EXPORTS == [(1, True), (2, True)] and beL.live_export is False and sL["pic"] and sL["pics"] == [2, 6, 0], (EXPORTS, sL["pics"]))
t0 = time.monotonic(); beL.command("next", {}); beL.command("next", {}); took = time.monotonic() - t0; sL = hubL.snapshot()
check("presses stay instant; a slide without a picture says so", took < 0.3 and sL["slide"] == 3 and sL["pic"] is False and beL.slide_image(3) is None, round(took, 2))
beL.command("end", {}); time.sleep(1.2); sL = hubL.snapshot()
check("after the show the remaining pictures are made", sL["show"] == "idle" and sL["pics"] == [6, 6, 0] and EXPORTS[2:] and not any(live for _, live in EXPORTS[2:]), (sL["pics"], EXPORTS[2:]))

# ---- 2.2: slides still appearing, and slides that keep PowerPoint busy (as on a real deck with large GIFs) ----
EXPORTS.clear(); APP_GIFS = APP
sl = [Slide(i, f"T{i}", f"notes {i}", False, 0) for i in range(1, 10)]
sl[2].SlideShowTransition.EntryEffect = 3849; sl[2].SlideShowTransition.Duration = 0.6     # slide 3: a 0.6 s fade
sl[4].clicks = 2; sl[4].TimeLine = TimeLine(2)                                              # slide 5: two click steps
sl[4].NotesPage = NotesPage("Say A[click]Say B\n[ Click ]Say C")                             # ... with a mark per step
sl[4].Shapes.items = [Shape(14, 1, "T5"), Shape(1, 0, "Ladder of\x0bevidence")]                  # ... and words on it
APP = App(); deckT = Pres("Transitions.pptx", sl); APP.Presentations.items.append(deckT)
deckT.SectionProperties = Sections([("Intro", 1, 3), ("Middle", 4, 3), ("End", 7, 3)])
View.appear = {3: 0.6, 4: 0.5, 7: 3.0}; View.stall = {2: 1.5}; View.stuck = {6}
hubT = cuewand.Hub(); beT = cuewand.WindowsBackend(hubT); beT.start()
ctxT = cuewand.Context(hubT, beT, cuewand.Tunnel(1), 1, fresh=True, keep=False)
for _ in range(60):
    time.sleep(0.1)
    if beT.outline_cache: break
check("before the show: each slide's transition time and click steps are read with its notes", beT.entrance_cache.get(3) == 0.6 and beT.steps_cache.get(5) == 2 and beT.steps_cache.get(1) == 0, (beT.entrance_cache, beT.steps_cache))
o5 = beT.outline()[4]
check("and PowerPoint's sections, the words on each slide (not its title) and the [click] marks in its notes", [x["name"] for x in beT.sections] == ["Intro", "Middle", "End"] and beT.sections[1] == {"name": "Middle", "first": 4, "last": 6} and o5["sec"] == "Middle" and o5["body"] == "Ladder of evidence" and o5["marks"] == 2 and o5["steps"] == 2, (beT.sections, o5))
T = {"n": 0}
def tp(name, base=True, **kw):
    s = hubT.snapshot(); T["n"] += 1; pid = f"t22-{T['n']}"
    body = dict(kw, cmd=name, id=pid)
    if base: body["base"] = {"slide": s["slide"], "click": s["click"]}
    t0 = time.monotonic(); r = ctxT.do_command(name, body, "test"); return r, time.monotonic() - t0, hubT.snapshot(), pid
def confirmed(limit=6.0):
    end = time.monotonic() + limit
    while beT.guess is not None and time.monotonic() < end: time.sleep(0.02)
    return hubT.snapshot()
seen = []; _orig = hubT.on_change; hubT.on_change = lambda old, new: (seen.append(new.get("slide")), _orig(old, new))[1]
nreads = notes_reads(sl)
ctxT.do_command("start", {"cmd": "start", "id": "t22-start"}, "test"); time.sleep(2.2)
r, took, s, pid = tp("next")
check("a press on a slide that has been up a while: the phone is answered at once, with the slide it lands on and its notes", r == "done" and took < 0.3 and s["slide"] == 2 and s["notes"] == "notes 2", (r, round(took, 2), s["slide"]))
check("... and its title, section and the next slide's first line, all from memory", (s["title"], s["sec"], s["nextCue"]) == ("T2", "Intro", "notes 3"), (s["title"], s["sec"], s["nextCue"]))
r, took, s, pid = tp("next")
check("a press made while PowerPoint is still busy with that slide (GIFs) waits for it, lands once, and the wait is logged", r == "done" and s["slide"] == 3 and 1.0 < took < 2.5 and logged("waited") and logged("for its turn"), (r, round(took, 2), s["slide"]))
check("PowerPoint's late confirmation is logged", logged("PowerPoint confirmed slide 2 step 0 after 1."))
a0 = COUNT["absorbed"]; r, took, s, pid = tp("next")
check("a quick press on a slide still fading in is held until its transition is over, then lands (none used up)", r == "done" and s["slide"] == 4 and COUNT["absorbed"] == a0 and 0.4 < took < 1.5, (r, round(took, 2), s["slide"], COUNT["absorbed"] - a0))
a0 = COUNT["absorbed"]; r, took, s, pid = tp("next")
check("a quick press that PowerPoint uses to finish a slide's own animation is sent once more, and lands once", r == "done" and s["slide"] == 5 and COUNT["absorbed"] == a0 + 1 and beT.stats["retried"][4] == 1 and logged("used it to finish the slide appearing"), (r, s["slide"], COUNT["absorbed"] - a0, dict(beT.stats["retried"])))
check("and Cuewand remembers how long that slide needs", 0.3 < beT.settle.get((4, 0), 0) <= cuewand.SETTLE_MAX, beT.settle)
time.sleep(2.1); r, took, s, pid = tp("next")
check("a step on a slide with click animations is shown at once too", r == "done" and took < 0.3 and (s["slide"], s["click"], s["clicks"]) == (5, 1, 2) and s["clicksOk"], (r, s["slide"], s["click"], s["clicks"]))
r, took, s, pid = tp("prev"); s = confirmed()
check("and Back undoes it", r == "done" and (s["slide"], s["click"]) == (5, 0), (r, s["slide"], s["click"]))
tp("goto", base=False, n=7); time.sleep(2.3)
r, took, s, pid = tp("next")
told = r; s = confirmed(); time.sleep(0.1)
check("a press the phone was told moved, which PowerPoint then used to finish the slide: corrected on the phone and in the press record", told == "done" and 8 in seen and s["slide"] == 7 and ctxT.press_result(pid) == "absorbed" and any(p["id"] == pid and p["result"] == "absorbed" for p in s["presses"]) and logged("after the phone was told it moved"), (told, s["slide"], ctxT.press_result(pid)))
r, took, s, pid = tp("next"); s = confirmed()
check("the press after it lands", r == "done" and s["slide"] == 8 and ctxT.press_result(pid) == "done", (r, s["slide"]))
tp("goto", base=False, n=6); r, took, s, pid = tp("next")
check("a press PowerPoint will not take at all: 'absorbed', said to the phone; nothing moved, sent at most twice", r == "absorbed" and s["slide"] == 6 and logged("the show did not move"), (r, s["slide"]))
tp("goto", base=False, n=1); rt = dict(beT.stats["retried"]); a0 = COUNT["absorbed"]; r, took, s, pid = tp("prev")
check("Back on the first slide is simply nothing to do: not sent again, not reported as a fault", r == "done" and s["slide"] == 1 and dict(beT.stats["retried"]) == rt, (r, s["slide"]))
tp("goto", base=False, n=4); a0 = COUNT["absorbed"]; r, took, s, pid = tp("next")
check("the second time on that slide, the press is held just long enough and lands first time", r == "done" and s["slide"] == 5 and COUNT["absorbed"] == a0 and beT.stats["retried"][4] == 1, (r, s["slide"], COUNT["absorbed"] - a0))
check("no notes page was read during the whole show", notes_reads(sl) == nreads, notes_reads(sl) - nreads)
lines = []; t0 = time.monotonic(); good = cuewand.run_selftest(ctxT, want=40, say=lines.append, gap=0.02); text = "\n".join(lines)
check("self-test on a slide PowerPoint never leaves: stops there after three presses and says so, without calling them faults", not good and "the walk forward stopped at slide 6" in text and "Presses PowerPoint took without moving:" in text and "(slides 6)" in text and ": answered" not in text, text[-700:])
View.stuck = set()
lines = []; good = cuewand.run_selftest(ctxT, want=40, say=lines.append, gap=0.02); text = "\n".join(lines)
check("self-test on a deck with fades, animations and a busy slide: every press lands exactly once", good and "RESULT: every press landed exactly once." in text, text[-900:])
check("and it names the slide PowerPoint is slow on, and the presses it had to send again", "slow to answer" in text and "slide 2 1." in text and "Pressed while a slide was still appearing" in text, text[-900:])
View.appear, View.stall = {}, {}
beT.close(); APP = APP_GIFS

# the whole thing end to end: Context + self-test on the stand-in
ctx = cuewand.Context(hubL, beL, cuewand.Tunnel(1), 1, fresh=True, keep=False)
lines = []; good = cuewand.run_selftest(ctx, want=40, say=lines.append, gap=0.02)
text = "\n".join(lines)
check("self-test on the stand-in: every press lands exactly once", good and "RESULT: every press landed exactly once." in text and "Slowest slides to draw: slide 2" in text, text[-600:])
check("self-test never touches the saved session", not os.path.exists(os.path.join(os.environ["CUEWAND_DATA"], "cuewand_session.json")))
View.glitch = 0
class Doubler(View):
    """A PowerPoint that, now and then, moves two steps for one request."""
    n = 0
    def Next(s):
        View.Next(s); type(s).n += 1
        if type(s).n % 7 == 0: View.Next(s)
Win.view_class = Doubler
lines = []; good = cuewand.run_selftest(ctx, want=30, say=lines.append, gap=0.02); text = "\n".join(lines)
check("self-test catches a show that moves twice for one press", (not good) and "PROBLEMS" in text, text[-400:])
beL.close()

check("log: connection, deck, pictures, slow export", logged("Connected to PowerPoint 16.0") and logged("deck: Talk.pptx, 5 slides") and logged("slide pictures: 5 of 5 ready") and logged("slide pictures paused for this slide show"))
for m in ("comtypes", "comtypes.client"): sys.modules[m] = None   # as on a computer where comtypes cannot load
hub2 = cuewand.Hub(); be2 = cuewand.WindowsBackend(hub2); be2.start(); time.sleep(0.7); s2 = hub2.snapshot()
check("without comtypes: snapshot says link off, arrow keys still work", s2["link"] == "off" and s2["mode"] == "keys" and "No PowerPoint connection" in be2.describe(), be2.describe()[:60])
n = len(calls["keys"]); be2.command("next", {}); check("arrow key sent in that state", len(calls["keys"]) == n + 2)
print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
