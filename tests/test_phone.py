"""The phone page, driven in a phone-sized Chromium against the demo deck (needs Playwright).
Usage: python test_phone.py [flow press trouble clock picture small access]   (none = all)"""
import json, os, re, signal, subprocess, sys, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright
import common
from common import B, DATA, kill
OUT = common.SHOTS
ok = bad = 0
K = H = PIN = ""
errs = []


def check(name, cond, extra=""):
    global ok, bad
    ok += bool(cond); bad += not cond
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "", flush=True)


def server(*args, keep=False):
    global K, H, PIN
    d = common.server(*args, keep=keep); K, H, PIN = d["key"], d["host_key"], d["pin"]


def post(path, body, key=None):
    r = urllib.request.Request(B + path, data=json.dumps(body).encode(), headers={"X-Cuewand-Key": key or K}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=20).read())


def state():
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + "/api/state?since=0", headers={"X-Cuewand-Key": K}), timeout=10).read())


def cmd(c, **k):
    return post("/api/cmd", dict(cmd=c, **k))


def fresh(show=None, slide=None, **timer):
    """Put the helper in a known place."""
    post("/api/demo", {"delay": 0})
    post("/api/control", {"action": "take", "cid": "testreset"}); post("/api/control", {"action": "share", "cid": "testreset"})   # every phone presses
    cmd("end"); post("/api/rehearsal", {"action": "discard"}); post("/api/rehearsal", {"action": "delete"})
    post("/api/timer", dict({"action": "reset", "dur": 900, "marks": [300, 60], "starts": "next"}, **timer))
    if show:
        cmd("start")
        if slide:
            cmd("goto", n=slide); post("/api/timer", {"action": "reset"})


HOOK = """(() => { const real = window.fetch.bind(window); window.__hold = false; window.__slowCmd = 0;
  const gone = opt => new Promise((res, rej) => { if (opt && opt.signal) opt.signal.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))); });
  window.fetch = (url, opt) => {
    if (window.__hold && String(url).includes('/api/state')) return gone(opt);
    if (window.__slowCmd && String(url).includes('/api/cmd'))       // the computer gets the press; its answer is held back
      return Promise.race([real(url, Object.assign({}, opt, {signal: undefined})).then(r => new Promise(res => setTimeout(() => res(r), window.__slowCmd))), gone(opt)]);
    return real(url, opt);
  }; })();"""


class Phone:
    def __init__(self, browser, w=390, h=844, vibrate=True, seen=False, name=None, ts=None):
        self.ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, has_touch=True, is_mobile=True)
        self.ctx.add_init_script(HOOK)
        if name: self.ctx.add_init_script(f"try {{ localStorage.setItem('cuewand.name', {json.dumps(name)}) }} catch (e) {{}}")
        if ts: self.ctx.add_init_script(f"try {{ localStorage.setItem('cuewand.ts', '{ts}') }} catch (e) {{}}")
        if not vibrate:
            self.ctx.add_init_script("Object.defineProperty(Navigator.prototype, 'vibrate', {value: undefined, configurable: true});")
        if seen:
            self.ctx.add_init_script("try { sessionStorage.setItem('cuewand.ready.' + new URLSearchParams(location.hash.slice(1)).get('k'), '1'); } catch (e) {}")
        self.pg = self.ctx.new_page()
        self.pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text and "ERR_" not in m.text else None)
        self.pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
        self.w, self.h = w, h

    def open(self, key=None, wait=700):
        self.pg.goto(B + "/#k=" + (key or K)); self.pg.wait_for_timeout(wait)
        return self

    def tap(self, sel, x=0.5, y=0.5, dx=0, dy=0, hold=0):
        bx = self.pg.locator(sel).bounding_box(); x0 = bx["x"] + bx["width"] * x; y0 = bx["y"] + bx["height"] * y
        self.pg.mouse.move(x0, y0); self.pg.mouse.down()
        if hold: self.pg.wait_for_timeout(hold)
        if dx or dy: self.pg.mouse.move(x0 + dx, y0 + dy, steps=6)
        self.pg.mouse.up()

    def wait(self, ms): self.pg.wait_for_timeout(ms)
    def text(self, sel): return self.pg.inner_text(sel).replace("\n", " ").strip()
    def vis(self, sel): return self.pg.is_visible(sel)
    def cls(self, sel): return self.pg.get_attribute(sel, "class") or ""
    def js(self, code): return self.pg.evaluate(code)
    def shot(self, name): self.pg.screenshot(path=f"{OUT}/{name}.png")

    def until(self, fn, ms=6000, step=100):
        end = time.time() + ms / 1000
        while time.time() < end:
            try:
                if fn(): return True
            except Exception:
                pass
            self.pg.wait_for_timeout(step)
        return False

    def close(self): self.ctx.close()


def part_flow(b):
    """Setup, one check, the talk."""
    fresh()
    ph = Phone(b).open(wait=300)
    ph.wait(900)
    check("first contact with no show running: Setup, and nothing else", ph.vis("#setup") and not ph.vis("#check") and ph.text("#su-go") == "Continue")
    lg = ph.js("(() => { const l = document.querySelector('#setup .mark .logo').getBoundingClientRect(), h = document.getElementById('su-h').getBoundingClientRect(); return [Math.round(l.height), Math.round(h.top - l.bottom), document.querySelector('#setup .mark .logo').getAttribute('aria-label')]; })()")
    check("the logo sits over Setup's heading: 22 px tall, 24 px above it, read as 'Cuewand'", lg == [22, 24, "Cuewand"], lg)
    check("Setup asks only what a talk needs first: the clock, length, alerts; the rest is folded away", ph.vis("#t-starts") and ph.vis("#t-len") and ph.vis("#t-marks") and not ph.vis("#p-pic") and not ph.vis("#m-pics") and ph.pg.get_attribute("#su-more", "aria-expanded") == "false")
    go, skip, ft = ph.pg.locator("#su-go").bounding_box(), ph.pg.locator("#su-skip").bounding_box(), ph.pg.locator("#setup .foot").bounding_box()
    check("its two buttons share one row, the main one on the right", abs(go["y"] + go["height"] / 2 - skip["y"] - skip["height"] / 2) < 3 and go["x"] > skip["x"] and ft["height"] < 90, ft)
    check("setup knows the deck and the talk length", "Demo deck.pptx, 8 slides" in ph.text("#su-deck") and ph.text("#su-len") == "15:00" and ph.text("#t-len button.sel") == "15")
    check("the talk view under Setup cannot be reached (inert)", ph.js("document.getElementById('app').inert === true"))
    ph.pg.locator("#t-len button", has_text="12").click(); ph.wait(300)
    check("talk length set in Setup", state()["timer"]["dur"] == 720 and ph.text("#su-len") == "12:00" and ph.pg.locator("#t-len button", has_text="12").get_attribute("aria-pressed") == "true")
    check("Setup asks when the clock starts, three ways, and says what the chosen one means",
          ph.js("[...document.querySelectorAll('#t-starts button')].map(b => b.textContent)") == ["When the slide show starts", "With my first Next", "No clock"]
          and ph.pg.get_attribute("#t-starts button[data-starts=next]", "aria-pressed") == "true" and "first Next" in ph.text("#t-starts-how"))
    post("/api/timer", {"dur": 900})
    ph.pg.click("#su-more"); ph.wait(350)
    check("'More options' unfolds what this phone shows, the buttons and the slide pictures", ph.vis("#p-pic") and ph.vis("#p-left") and ph.pg.get_attribute("#su-more", "aria-expanded") == "true")
    foot = ph.pg.locator("#setup .foot").bounding_box(); last = ph.pg.locator("#m-pics")
    last.scroll_into_view_if_needed(); ph.wait(150); lb = last.bounding_box()
    check("Setup: the button bar is its own strip; the last option scrolls clear of it", lb["y"] + lb["height"] <= foot["y"] + 1 and foot["y"] + foot["height"] <= ph.h + 1, (lb, foot))
    ph.pg.click("#su-go")
    ph.until(lambda: ph.text("#ck-go") != "Checking", 15000)
    ph.pg.click("#ck-go"); ph.wait(250)       # at once: as the second tap of a double tap on Continue would
    check("a tap in the first second after the check (the second tap of a double tap on Continue) does nothing", state()["show"] == "idle")
    lines = [(li.get_attribute("class"), li.inner_text().replace("\n", " / ")) for li in ph.pg.locator("#ck-list li").all()]
    check("one tap ran the check: a verdict and its lines, notes, click marks and sections included before the show starts", ph.text("#ck-h").startswith("Ready") and len(lines) >= 9 and any("Notes follow the clicks on 1 slide" in t for _, t in lines) and any("Sections found: Opening, The idea, Closing" in t for _, t in lines) and any("Speaker notes found on 6 of 7" in t for _, t in lines), (ph.text("#ck-h"), lines))
    check("the screen-awake line is not a warning on the plain link", any(c == "ok" and "screen" in t for c, t in lines), lines)
    check("the check's button starts the slide show", ph.text("#ck-go") == "Start the slide show" and ph.text("#ck-skip") == "Not yet")
    ph.shot("flow_check")
    ph.wait(1000); ph.pg.click("#ck-go"); ph.until(lambda: state()["show"] == "running")
    ph.wait(500); s = state()
    check("two taps from Setup to the first slide", s["show"] == "running" and s["slide"] == 1 and not ph.vis("#check") and not ph.vis("#setup") and ph.vis("#surface"))
    ph.wait(1000)
    check("the button shows the talk length, and says when the clock will start, on one line", ph.text("#s-main") == "15:00" and ph.text("#s-sub") == "Starts on first Next" and ph.js("document.getElementById('s-sub').getClientRects().length") == 1, (ph.text("#s-main"), ph.text("#s-sub")))
    check("the top row offers Menu and Slides", ph.text("#b-menu") == "Menu" and ph.text("#b-slides") == "Slides")
    ph.tap("#surface"); ph.wait(350)
    check("first Next: slide 2, named on the button, clock running", state()["slide"] == 2 and ph.text("#s-main") == "Slide 2" and state()["timer"]["running"], ph.text("#s-main"))
    ph.wait(900); check("then the button is the clock again", ph.text("#s-main").startswith("14:5") and ph.text("#s-hint") == "Next", ph.text("#s-main"))
    ph.pg.reload(); ph.wait(900)
    check("a reload mid-talk lands in the talk, not in Setup", not ph.vis("#setup") and not ph.vis("#check") and ph.text("#cur") == "2")
    ph2 = Phone(b).open(wait=1200)
    check("a second phone joining mid-talk lands in the talk too", not ph2.vis("#setup") and ph2.text("#cur") == "2" and ph2.vis("#surface"))
    ph2.close()
    ph.pg.click("#b-menu"); ph.wait(400)
    heads = [h.inner_text() for h in ph.pg.locator("#s-menu h3").all() if h.is_visible()]
    check("the Menu is grouped by what you act on, with what ends things apart and in red", heads == ["The clock", "The slide show", "Rehearsal", "This phone", "Ending"] and ph.js("getComputedStyle(document.getElementById('m-over-t')).color") == "rgb(255, 148, 148)", heads)
    check("with the Menu open, nothing behind it can be reached", ph.js("document.getElementById('app').inert === true"))
    ph.pg.click("#m-setup"); ph.wait(300)
    check("Setup from the Menu: the phone's options are unfolded, and there is one button, Done", ph.vis("#setup") and ph.vis("#p-pic") and ph.text("#su-go") == "Done" and not ph.vis("#su-skip"))
    ph.pg.click("#su-go"); ph.wait(200); check("Done returns to the talk", not ph.vis("#setup") and ph.vis("#surface"))
    ph.pg.click("#b-menu"); ph.wait(400); ph.pg.click("#m-check")
    ph.until(lambda: ph.text("#ck-go") != "Checking", 15000)
    check("the check run again mid-talk ends with the way back to the talk", ph.text("#ck-h").startswith("Ready") and ph.text("#ck-go") == "Go to my talk", (ph.text("#ck-h"), ph.text("#ck-go")))
    ph.wait(1050); ph.pg.click("#ck-go"); ph.wait(200); check("and returns there", not ph.vis("#check") and ph.vis("#surface") and ph.js("document.getElementById('app').inert === false"))
    # start over
    ph.wait(600); ph.pg.click("#b-menu"); ph.wait(400); ph.pg.locator("#m-over").scroll_into_view_if_needed(); ph.pg.click("#m-over"); ph.wait(200)
    check("Start over says what it will do and asks for a second tap", "Ends the slide show, clears the clock and goes back to Setup" in ph.text("#m-over") and "arm" in ph.cls("#m-over") and ph.text("#m-over-t") == "Tap again to start over" and state()["show"] == "running")
    ph.pg.click("#m-over"); ph.until(lambda: ph.vis("#setup"), 8000); ph.wait(300); s = state()
    check("Start over: the slide show is ended, the clock cleared, and Setup is where it begins again", s["show"] == "idle" and s["timer"]["elapsed"] == 0 and not s["timer"]["running"] and ph.text("#su-go") == "Continue" and ph.vis("#su-skip") and not ph.vis("#p-pic"), (s["show"], s["timer"]))
    ph.pg.click("#su-skip"); ph.wait(1400)
    check("the start screen offers the show, the show from the selected slide, and a rehearsal", [ph.text("#rest-start"), ph.text("#rest-cur"), ph.text("#rest-reh")] == ["Start the slide show", "Start from the selected slide", "Start a rehearsal"] and not ph.vis("#b-slides"))
    ph.pg.click("#rest-reh"); ph.until(lambda: state()["timer"]["rehearsing"], 8000); ph.wait(400); s = state()
    check("'Start a rehearsal' starts the slide show and the rehearsal together", s["show"] == "running" and s["slide"] == 1 and s["timer"]["rehearsing"] and ph.vis("#rehbar") and ph.vis("#surface"), (s["show"], s["timer"]))
    post("/api/rehearsal", {"action": "discard"})
    ph.close()


def part_press(b):
    """What a press does, and what it cannot do by accident."""
    fresh(show=True)
    ph = Phone(b, seen=True).open()
    ph.tap("#surface"); ph.wait(300)
    ph.tap("#surface"); ph.wait(300)
    check("a step on the same slide: named, counted in the header, ring flash", state()["click"] == 1 and ph.text("#s-main") == "Step 1 of 3" and ph.cls("#pads") == "fx-build" and ph.pg.locator("#pips i.done").count() == 1, (ph.text("#s-main"), ph.cls("#pads")))
    ph.tap("#back"); ph.wait(300)
    check("Back to no steps: says so plainly, and the Back button is what lights", state()["click"] == 0 and ph.text("#s-main") == "No steps shown" and ph.cls("#pads") == "fx-back", ph.text("#s-main"))
    ph.wait(700)
    # thumbs drift
    ph.tap("#back", dx=75); ph.wait(350); s = state()
    check("a press that starts on Back and drifts right is still Back", s["slide"] == 1, (s["slide"], s["click"]))
    ph.wait(600); ph.tap("#surface", x=0.3, dx=-75); ph.wait(350); s = state()
    check("a press that starts on Next and drifts left is still Next", s["slide"] == 2 and s["click"] == 0, (s["slide"], s["click"]))
    ph.wait(600); ph.tap("#surface", y=0.3, dy=66); ph.wait(350); s = state()
    check("a press that drifts down the button still counts", s["click"] == 1, s["click"])
    ph.wait(600); ph.tap("#surface", y=0.3, dy=-330); ph.wait(300); s = state()
    check("sliding right off the buttons cancels, and says so", s["click"] == 1 and ph.text("#s-main") == "Cancelled", ph.text("#s-main"))
    ph.wait(1200)
    # swipe is a choice
    ph.js("localStorage.setItem('cuewand.prefs', JSON.stringify({pic:true,next:true,left:false,swipe:true}))"); ph.pg.reload(); ph.wait(800)
    ph.tap("#back", dx=90); ph.wait(350); s1 = state(); ph.wait(500)
    ph.tap("#surface", x=0.7, dx=-90); ph.wait(350); s2 = state()
    check("with 'Swipe as well as press' on: right is Next, left is Back", s1["click"] == 2 and s2["click"] == 1, (s1["click"], s2["click"]))
    ph.js("localStorage.setItem('cuewand.prefs', JSON.stringify({pic:true,next:true,left:true,swipe:false}))"); ph.pg.reload(); ph.wait(800)
    bx, sx = ph.pg.locator("#back").bounding_box(), ph.pg.locator("#surface").bounding_box()
    check("left-handed: Next on the left, Back on the right", sx["x"] < bx["x"] and sx["width"] > bx["width"] * 2)
    ph.shot("press_left")
    ph.js("localStorage.removeItem('cuewand.prefs')"); ph.pg.reload(); ph.wait(800)

    # the last slide
    cmd("goto", n=8); ph.wait(500)
    check("on the last slide the button says so before any press", ph.text("#s-hint") == "Last slide", ph.text("#s-hint"))
    ph.tap("#surface"); ph.wait(350); ph.tap("#surface"); ph.wait(350); s = state()
    check("a nervous double-tap on the last slide does nothing but say 'Last slide'", s["show"] == "running" and s["slide"] == 8 and not s["black"] and ph.vis("#surface") and not ph.vis("#qbar") and ph.text("#s-main") == "Last slide" and not ph.pg.locator(".arm").count(), (s["show"], ph.text("#s-main")))
    for spot in ((0.2, 0.9), (0.5, 0.9), (0.9, 0.9)):       # where Back, Black out and End show used to appear under the thumb
        ph.tap("#surface", *spot)
    ph.wait(200); s = state()
    check("nor do three more taps in the same second", s["show"] == "running" and s["slide"] == 8 and not s["black"] and not ph.vis("#qbar"))
    ph.wait(900)
    for gap in (1100, 400, 900, 1300):                   # the "nothing happened, press again" reflex, with a pause
        ph.tap("#surface", 0.5, 0.9); ph.wait(gap)
    s = state()
    check("however often Next is pressed on the last slide, the show stays put and the phone stays on the talk", s["show"] == "running" and s["slide"] == 8 and not s["black"] and ph.vis("#surface") and not ph.vis("#qbar") and not ph.pg.locator(".arm").count(), (s["show"], s["black"]))
    check("it points at Slides instead", "nudge" in ph.cls("#b-slides") and (ph.text("#s-hint") in ("Last slide", "") or ph.text("#s-hint").endswith(" left")), ph.cls("#b-slides"))
    ph.pg.click("#b-slides"); ph.wait(150)
    check("Slides opens the grid, and the button now leads back", ph.vis("#qbar") and "cool" in ph.cls("#qbar") and ph.text("#b-slides") == "Back to talk")
    ph.pg.click("#q-black", force=True); ph.pg.click("#q-next", force=True); ph.wait(250); s = state()
    check("its buttons ignore the first second, so a late tap cannot black out or leave the deck", s["show"] == "running" and s["slide"] == 8 and not s["black"], (s["show"], s["black"]))
    ph.shot("press_slides")
    check("Slides: three columns of slides, the current one marked", ph.pg.locator("#grid button").count() == 8 and ph.pg.locator("#grid button.cur").count() == 1 and ph.js("getComputedStyle(document.getElementById('grid')).gridTemplateColumns.split(' ').length") == 3)
    check("its bar is Black out, Back and Next (Next where the big one is); Next carries the time; nothing there ends the show", [b.inner_text().split("\n")[0] for b in ph.pg.locator("#qbar button").all()] == ["Black out", "Back", "Next"] and " left" in ph.text("#q-clock") and ph.text("#b-menu") == "Menu", ph.text("#q-clock"))
    ph.wait(1100)
    ph.pg.locator("#grid button").nth(4).click(); ph.wait(400); check("a slide in the grid is one tap away", state()["slide"] == 5)
    ph.pg.click("#q-black"); ph.wait(400); check("black out", state()["black"] is True and ph.text("#q-black") == "Show slides" and ph.pg.get_attribute("#q-black", "aria-pressed") == "true")
    ph.pg.click("#q-black"); ph.wait(400)
    cmd("goto", n=8); ph.wait(300); ph.pg.click("#q-next"); ph.wait(500); s = state()
    check("the small Next in Slides is not guarded: it can leave the deck on purpose (custom shows need that)", s["show"] == "ended")
    check("the view did not change by itself when the show ended", ph.vis("#qbar") and "ended" in ph.text("#tot"), ph.text("#tot"))
    ph.pg.click("#b-slides"); ph.wait(300); ph.tap("#surface"); ph.wait(300)
    check("at the end screen the Next button says where you are instead of doing nothing", ph.text("#s-main") == "End of show" and state()["show"] == "ended", ph.text("#s-main"))
    ph.wait(1500); ph.tap("#back"); ph.wait(400); check("Back returns to the last slide", state()["show"] == "running" and state()["slide"] == 8)
    ph.pg.click("#b-menu"); ph.wait(400)
    ph.pg.click("#m-black"); ph.wait(500)
    check("Black out is in the Menu too, and closes it", state()["black"] is True and not ph.js("document.querySelector('.sheet.on')"))
    ph.pg.click("#b-menu"); ph.wait(400); check("where the same row then brings the slides back", ph.text("#m-black-t") == "Show the slides again")
    ph.pg.click("#m-black"); ph.wait(500); ph.pg.click("#b-menu"); ph.wait(400)
    ph.pg.click("#m-end"); ph.wait(200)
    check("End the slide show lives in the Menu, asks for a second tap and looks different while it waits", state()["show"] == "running" and "arm" in ph.cls("#m-end") and ph.text("#m-end-t") == "Tap again to end the slide show")
    ph.shot("press_end_armed")
    ph.pg.click("#m-end"); ph.wait(600)
    check("second tap ends the show; the phone shows the start screen", state()["show"] == "idle" and ph.vis("#rest-start") and not ph.vis("#qbar") and not ph.js("document.querySelector('.sheet.on')"))
    ph.pg.click("#rest-start", force=True); ph.wait(300)
    check("the start button ignores the first second too", state()["show"] == "idle")
    ph.wait(1000); ph.pg.click("#rest-start"); ph.wait(500); check("then it starts the show", state()["show"] == "running")
    ph.close()


def part_trouble(b):
    """Slow, busy, stale, lost and offline: said on the button, and never a doubled press."""
    fresh(show=True)
    ph = Phone(b, seen=True).open()
    # slow link / slow PowerPoint: one press may wait its turn
    post("/api/demo", {"delay": 1.2})
    ph.tap("#surface"); ph.wait(550)
    check("a press that takes a while says 'Sending' on the button", ph.text("#s-main") == "Sending", ph.text("#s-main"))
    ph.tap("#surface"); ph.wait(120)
    check("a second press meanwhile waits its turn, and shows it", ph.vis("#s-plus"))
    ph.tap("#surface"); ph.wait(200)
    check("a third is refused out loud", ph.text("#s-main") == "Still sending", ph.text("#s-main"))
    ph.until(lambda: state()["slide"] == 2 and state()["click"] == 1, 6000); ph.wait(1500); s = state()
    check("exactly two presses landed, in order", (s["slide"], s["click"]) == (2, 1) and not ph.vis("#s-plus"), (s["slide"], s["click"]))
    post("/api/demo", {"delay": 3.0}); ph.wait(300)
    ph.tap("#surface"); ph.wait(1400); ph.tap("#surface"); ph.wait(200)
    check("a second press more than a second into a slow one is refused, not queued to land late", ph.text("#s-main") == "Still sending" and not ph.vis("#s-plus"), ph.text("#s-main"))
    ph.until(lambda: state()["click"] == 2, 5000); ph.wait(3600); s = state()
    check("so only the first one lands", (s["slide"], s["click"]) == (2, 2), (s["slide"], s["click"]))
    cmd("prev"); ph.wait(300)
    # PowerPoint slower than the phone will wait
    post("/api/demo", {"delay": 5.5}); ph.wait(300)
    ph.tap("#surface"); ph.wait(4600)
    check("PowerPoint very slow: the button says 'On its way', not 'failed'", ph.text("#s-main") == "On its way" and "slow to answer" in ph.text("#s-sub") and state()["click"] == 1, (ph.text("#s-main"), ph.text("#s-sub")))
    ph.shot("trouble_pending")
    ph.tap("#surface"); ph.wait(200)
    check("pressing again meanwhile sends nothing", ph.text("#s-main") == "Still sending", ph.text("#s-main"))
    ph.until(lambda: state()["click"] == 2, 4000); ph.wait(400)
    check("it lands once, and the button reports it", state()["click"] == 2 and ph.text("#s-main") == "Step 2 of 3", ph.text("#s-main"))
    post("/api/demo", {"delay": 0}); ph.wait(1200); s = state()
    check("nothing else arrived afterwards", (s["slide"], s["click"]) == (2, 2))
    # the show moved while this phone was not looking (a clicker, a second phone)
    ph.js("window.__hold = true"); ph.wait(3600)
    cmd("goto", n=5); ph.wait(200)
    check("(the phone has not heard about the jump yet)", ph.text("#cur") == "2")
    ph.tap("#surface"); ph.wait(400); s = state()
    check("a press made from a slide the show has left is refused; nothing is skipped", s["slide"] == 5 and ph.text("#s-main") == "Slide had moved" and ph.text("#cur") == "5", (s["slide"], ph.text("#s-main"), ph.text("#cur")))
    ph.js("window.__hold = false"); ph.wait(1800)
    # PowerPoint takes a press but uses it to finish a slide that is still coming up
    post("/api/demo", {"absorb": 30}); here = state()
    ph.tap("#surface"); ph.wait(400); s = state()
    check("a press PowerPoint takes without moving: 'Nothing moved, press again' on the button; not red; nothing skipped", (s["slide"], s["click"]) == (here["slide"], here["click"]) and ph.text("#s-main") == "Nothing moved" and "Press again" in ph.text("#s-sub") and "bad" not in ph.cls("#surface") and ph.cls("#pads") == "fx-none", (ph.text("#s-main"), ph.text("#s-sub"), ph.cls("#surface"), ph.cls("#pads")))
    ph.shot("trouble_absorbed")
    post("/api/demo", {"mislead": True}); ph.wait(2600); here = state()
    ph.tap("#surface"); ph.wait(300); first = (ph.text("#s-main"), ph.text("#cur"))
    ph.wait(1200); s = state()
    check("told it moved, then PowerPoint did not move after all: the phone puts the slide back and says so", first[0] != "Nothing moved" and (s["slide"], s["click"]) == (here["slide"], here["click"]) and ph.text("#s-main") == "Nothing moved" and ph.text("#cur") == str(here["slide"]), (first, ph.text("#s-main"), ph.text("#cur"), s["slide"]))
    post("/api/demo", {"delay": 0}); ph.wait(2600)
    # PowerPoint busy
    ph.pg.route("**/api/cmd", lambda r: r.fulfill(status=504, content_type="application/json", body='{"error":"PowerPoint did not answer in time"}'))
    ph.tap("#surface"); ph.wait(350)
    check("PowerPoint busy: said in red on the button, with what to do", ph.text("#s-main") == "PowerPoint is busy" and "Try again" in ph.text("#s-sub") and "bad" in ph.cls("#surface") and ph.cls("#pads") == "fx-fail", (ph.text("#s-main"), ph.cls("#surface")))
    red = ph.js("""(() => { const lum = c => { const v = c.match(/[\\d.]+/g).slice(0, 3).map(x => { x /= 255; return x <= .03928 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); }); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
      const a = lum(getComputedStyle(document.getElementById('s-main')).color), b = lum(getComputedStyle(document.getElementById('surface')).backgroundColor);
      return [(Math.max(a, b) + .05) / (Math.min(a, b) + .05), document.getElementById('fill').getBoundingClientRect().height]; })()""")
    check("the red words sit on a dark red button with no blue behind them (at least 4.5:1)", red[0] >= 4.5 and red[1] < 1, red)
    ph.shot("trouble_busy")
    ph.pg.unroute("**/api/cmd"); ph.wait(2700)
    check("and the button is itself again afterwards", "bad" not in ph.cls("#surface") and ph.text("#s-hint") in ("Next", ""))
    # the answer is lost on the way back
    n = {"calls": 0}

    def lose(route):
        n["calls"] += 1
        if n["calls"] == 1:
            route.fetch(); route.abort()         # the computer got the press; the phone never hears
        else:
            route.continue_()
    ph.pg.route("**/api/cmd", lose)
    before = state(); ph.tap("#surface"); ph.wait(1500); s = state()
    check("answer lost on the way back: the phone asks again with the same name tag, and the show moved once", n["calls"] >= 2 and (s["slide"], s["click"]) == (before["next"], 0) and ph.text("#cur") == str(s["slide"]), (n, before["slide"], s["slide"]))
    ph.pg.unroute("**/api/cmd"); ph.wait(600)
    # the press arrives and is carried out, but its answer hangs for longer than the phone waits
    cmd("goto", n=1); ph.wait(700); ph.js("window.__slowCmd = 9000")
    ph.tap("#surface"); ph.wait(5000)
    check("answer hanging while the regular updates arrive: after 3 s 'Still on its way' (the link is fine), the time in sight", ph.text("#s-main") == "Still on its way" and " left" in ph.text("#s-hint") and state()["slide"] == 2, (ph.text("#s-main"), state()["slide"]))
    ph.until(lambda: "did arrive" in ph.text("#snack-t"), 5000); s = state()
    check("then it asks the computer what became of the press, and reports that it did arrive, just above the buttons", "did arrive" in ph.text("#snack-t") and ph.pg.locator("#snack").bounding_box()["y"] + ph.pg.locator("#snack").bounding_box()["height"] <= ph.pg.locator("#pads").bounding_box()["y"] + 1 and ph.text("#s-main") not in ("Not done", "No answer") and (s["slide"], s["click"]) == (2, 0) and "ok" in ph.cls("#where"), (ph.text("#toast"), ph.text("#s-main"), s["slide"]))
    ph.js("window.__slowCmd = 0"); ph.wait(3600)
    cmd("goto", n=1); ph.wait(700); ph.js("window.__slowCmd = 9000; window.__hold = true")
    ph.tap("#surface"); ph.wait(5200)
    check("with the regular updates stalled as well, it says it is checking the link", ph.text("#s-main") == "Checking the link", ph.text("#s-main"))
    ph.js("window.__slowCmd = 0; window.__hold = false"); ph.until(lambda: "ok" in ph.cls("#where"), 9000); ph.wait(5500)
    # no connection at all
    here = state()
    ph.ctx.set_offline(True)
    t0 = time.time(); ph.until(lambda: "down" in ph.cls("#where"), 14000); dt = time.time() - t0
    check("connection lost: the phone knows within ten seconds", "down" in ph.cls("#where") and dt < 10.5, f"{dt:.1f}s")
    ph.wait(300)
    check("and says so on the Next button itself, with a dashed red edge; the time stays in sight", ph.text("#s-main") == "No connection" and "cut" in ph.cls("#surface") and ph.text("#tot") == "No connection" and (" left" in ph.text("#s-sub") or "not getting through" in ph.text("#s-sub")), (ph.text("#s-main"), ph.cls("#surface"), ph.text("#s-sub")))
    ph.shot("trouble_offline")
    ph.tap("#surface"); ph.wait(3200)
    check("a press while offline is not left hanging", ph.text("#s-main") in ("No answer", "No connection") and state()["slide"] == here["slide"], ph.text("#s-main"))
    ph.ctx.set_offline(False)
    t0 = time.time(); ph.until(lambda: "ok" in ph.cls("#where"), 8000); dt = time.time() - t0
    check("connection back: the phone knows within three seconds", "ok" in ph.cls("#where") and dt < 3.5, f"{dt:.1f}s")
    ph.wait(700)
    check("and it reports what became of the press it never heard about", "did not arrive" in ph.text("#snack-t") and state()["slide"] == here["slide"], ph.text("#toast"))
    ph.wait(600); ph.tap("#surface"); ph.wait(400); check("presses work again at once", state()["slide"] != here["slide"] or state()["click"] != here["click"])
    # the press arrives, then the connection dies before the answer and stays dead for a while
    cmd("goto", n=1); ph.wait(600); n2 = {"cmd": 0}

    def cut(route):
        if "/api/cmd" in route.request.url:
            n2["cmd"] += 1
            if n2["cmd"] == 1:
                route.fetch()                   # the computer carries the press out
        route.abort()
    ph.pg.route("**/api/**", cut)
    ph.tap("#surface"); ph.wait(3600); s = state()
    check("press arrived, answer and connection lost: the show moved once however often the phone retried", s["slide"] == 2 and s["click"] == 0 and n2["cmd"] >= 2 and ph.text("#s-main") in ("No answer", "No connection"), (s["slide"], s["click"], n2, ph.text("#s-main")))
    ph.pg.unroute("**/api/**"); ph.until(lambda: "ok" in ph.cls("#where"), 8000); ph.wait(800); s = state()
    check("when the connection returns the phone finds out the press did arrive, and does not send it again", "did arrive" in ph.text("#snack-t") and (s["slide"], s["click"]) == (2, 0) and ph.text("#cur") == "2", (ph.text("#snack-t"), s["slide"], s["click"]))
    ph.wait(500)
    # the helper is restarted mid-talk
    post("/api/timer", {"action": "start"}); cmd("goto", n=3); ph.wait(1600)
    kill(); ph.wait(1200); server(keep=True)
    ph.until(lambda: "ok" in ph.cls("#where"), 9000); ph.wait(500)
    check("Cuewand restarted on the computer: this phone carries on with the same link, clock still running", "ok" in ph.cls("#where") and not ph.vis("#pairing") and state()["timer"]["running"] and state()["timer"]["elapsed"] > 2, (ph.cls("#where"), state()["timer"]))
    # new codes
    urllib.request.urlopen(urllib.request.Request(B + f"/api/host/rotate?h={H}", data=b"{}", method="POST"), timeout=5).read()
    ph.until(lambda: ph.vis("#pairing"), 9000)
    check("new codes made on the computer: this phone is asked for the new one", ph.vis("#pairing") and "new code" in ph.text("#pair-h").lower(), ph.text("#pair-h"))
    d = json.load(open(DATA + "/cuewand_session.json"))
    ph.pg.fill("#pin", "123"); ph.pg.click("#pin-go"); ph.wait(200)
    check("a short number is caught on the phone", "six digits" in ph.text("#pin-err"), ph.text("#pin-err"))
    wrong = "000000" if d["pin"] != "000000" else "111111"
    ph.pg.fill("#pin", wrong); ph.wait(600)
    check("the sixth digit sends it; a wrong number gets a plain answer", "not the number" in ph.text("#pin-err"), ph.text("#pin-err"))
    ph.shot("trouble_pin")
    ph.pg.fill("#pin", d["pin"][:5]); ph.wait(100)
    check("the number is shown in two groups of three", ph.pg.input_value("#pin") == d["pin"][:3] + " " + d["pin"][3:5])
    ph.pg.locator("#pin").press_sequentially(d["pin"][5]); ph.wait(2200)
    global K
    K = d["key"]
    check("the right number connects this phone", not ph.vis("#pairing") and "ok" in ph.cls("#where"), ph.cls("#where"))
    ph.close()
    ph3 = Phone(b); ph3.pg.goto(B + "/"); ph3.wait(600)
    check("a phone that opens the bare address is asked for the number, with a way to type it", ph3.vis("#pin") and ph3.text("#pair-h") == "Connect this phone" and ph3.js("document.activeElement.id") == "pin")
    ph3.close()


def part_clock(b):
    """The clock on the button, alerts, pause, reset, rehearsal, recap."""
    fresh(show=True, slide=3)
    ph = Phone(b, seen=True).open()
    post("/api/timer", {"action": "start"}); ph.wait(700)
    fill = lambda: ph.js("(() => { const f = document.getElementById('fill').getBoundingClientRect(), s = document.getElementById('surface').getBoundingClientRect(); return f.height / s.height; })()")
    col = lambda sel, prop="color": ph.js(f"getComputedStyle(document.querySelector('{sel}')).{prop}")
    check("calm: the button is the clock, nearly full", "calm" in ph.cls("#surface") and ph.text("#s-main") in ("15:00", "14:59", "14:58") and fill() > 0.95, (ph.cls("#surface"), fill()))
    post("/api/timer", {"dur": 61, "marks": [60]}); ph.wait(900)
    f1 = fill()
    check("short of time: the whole button turns amber, digits and edge too, whatever the level", "warn" in ph.cls("#surface") and col("#s-main") == "rgb(242, 181, 68)" and col("#surface", "borderTopColor") == "rgb(242, 181, 68)" and col("#surface", "backgroundColor") == "rgb(26, 18, 4)" and 0.6 < f1 < 1, (ph.cls("#surface"), col("#s-main"), f1))
    ph.shot("clock_warn")
    post("/api/timer", {"dur": 30}); ph.until(lambda: state()["timer"]["elapsed"] > 30.6, 40000, 500); ph.wait(400)
    check("over time: red edge, light red digits counting up, no level left", "over" in ph.cls("#surface") and ph.text("#s-main").startswith("+") and col("#s-main") == "rgb(255, 148, 148)" and col("#surface", "borderTopColor") == "rgb(255, 77, 77)" and fill() < 0.02 and ph.text("#s-sub") == "Over time", (ph.cls("#surface"), ph.text("#s-main")))
    ph.shot("clock_over")
    check("running out of time flashed 'Time is up'", ph.text("#flash") == "Time is up")
    ph.wait(2700)
    post("/api/timer", {"action": "reset", "dur": 64, "marks": [60]}); post("/api/timer", {"action": "start"})
    ph.until(lambda: "on" in ph.cls("#flash"), 8000)
    check("an alert flashes the whole screen", "on" in ph.cls("#flash") and ph.text("#flash") == "1 min left", ph.text("#flash"))
    ph.wait(2600)
    post("/api/timer", {"action": "pause", "dur": 900, "marks": [300, 60]}); ph.wait(500)
    check("paused is unmistakable: a framed word, and the digits keep full contrast", ph.text("#s-sub") == "Paused" and "framed" in ph.cls("#s-sub") and float(col("#s-main", "opacity")) == 1, ph.cls("#s-sub"))
    ph.pg.click("#b-menu"); ph.wait(400)
    check("the Menu opens with focus inside it, and names the clock's buttons by what they do", ph.js("document.activeElement.closest('#s-menu') !== null") and ph.js("document.getElementById('s-menu').inert === false") and ph.text("#t-go") == "Resume the clock")
    ph.pg.click("#t-reset"); ph.wait(200)
    check("Reset asks for a second tap", state()["timer"]["elapsed"] > 0 and "arm" in ph.cls("#t-reset") and ph.text("#t-reset") == "Tap again")
    ph.pg.click("#t-reset"); ph.wait(400); check("second tap resets", state()["timer"]["elapsed"] == 0 and "arm" not in ph.cls("#t-reset") and ph.text("#t-reset") == "Reset")
    ph.pg.keyboard.press("Escape"); ph.wait(350)
    check("Escape closes the sheet, which then cannot be reached", ph.js("document.getElementById('s-menu').inert === true") and ph.js("getComputedStyle(document.getElementById('s-menu')).visibility") == "hidden")
    # pace: nothing precise without a rehearsal
    cmd("goto", n=2); post("/api/timer", {"action": "start"}); ph.wait(1500)
    check("no rehearsal: no made-up 'ahead' or 'behind' figure", ph.text("#s-sub") == "", ph.text("#s-sub"))
    # rehearse the whole deck
    ph.pg.click("#b-menu"); ph.wait(300); ph.pg.click("#r-start"); ph.wait(250)
    check("'Rehearse now' in the middle of a talk asks first, and says what it will do", not state()["timer"]["rehearsing"] and "arm" in ph.cls("#r-start") and ph.text("#r-start-t") == "Tap again: back to slide 1, the clock restarts", ph.text("#r-start-t"))
    ph.pg.click("#r-start")
    ph.until(lambda: state()["timer"]["rehearsing"], 5000); ph.wait(1100)
    check("and offers to undo it", ph.vis("#snack") and ph.text("#snack-b") == "Undo" and "clock restarted" in ph.text("#snack-t"), ph.text("#snack-t"))
    check("rehearsal: starts from slide 1 and counts up on the button", state()["slide"] == 1 and "reh" in ph.cls("#surface") and ph.text("#s-sub") == "so far" and not ph.js("document.querySelector('.sheet.on')"), (state()["slide"], ph.cls("#surface")))
    check("a band with a red dot says 'Rehearsing' for as long as it runs, with Stop beside it; the band itself is not red", ph.js("getComputedStyle(document.getElementById('rehbar')).backgroundColor") == "rgb(29, 37, 52)" and ph.vis("#rehbar") and ph.text("#reh-t").startswith("Rehearsing, 0:0") and ph.text("#reh-stop") == "Stop", ph.text("#reh-t"))
    tb, sb = ph.pg.locator("#toast").bounding_box(), ph.pg.locator("#reh-stop").bounding_box()
    check("the message that mentions Stop does not cover it", tb["y"] >= sb["y"] + sb["height"], (tb, sb))
    ph.shot("clock_rehearsing")
    ph.pg.click("#b-slides"); ph.wait(1300)
    check("the bar and its Stop are there in Slides too", ph.vis("#rehbar") and ph.vis("#reh-stop") and ph.vis("#qbar"))
    ph.pg.click("#b-slides"); ph.wait(300)
    for slide in (2, 3, 4, 5, 7, 8):
        ph.wait(750); cmd("goto", n=slide)
    ph.wait(900); ph.tap("#surface"); ph.wait(300)
    check("last slide while rehearsing: no view change; Stop is pointed out", ph.vis("#surface") and not ph.vis("#qbar") and ph.text("#s-main") == "Last slide" and "nudge" in ph.cls("#reh-stop"))
    ph.pg.click("#b-menu"); ph.wait(350)
    check("the Menu while rehearsing: one 'Stop the rehearsal'; no greyed-out Pause or Reset, no second 'Rehearse'", ph.vis("#m-stop") and not ph.vis("#t-go") and not ph.vis("#t-reset") and not ph.vis("#r-start"))
    ph.pg.click("#m-stop"); ph.wait(700)
    check("Stop asks what to do with the rehearsal, in the words of each action", ph.text("#ss-h") == "Stop the rehearsal" and ph.text("#r-save") == "Save this rehearsal" and ph.text("#r-discard") == "Discard it" and ph.text("#s-stop [data-close]") == "Keep rehearsing" and "on 7 of the 7 slides" in ph.text("#stop-sum") and ph.text("#stop-note") == "", (ph.text("#stop-sum"), ph.text("#stop-note")))
    ph.shot("clock_stop")
    ph.pg.click("#s-stop [data-close]"); ph.wait(350)
    check("'Keep rehearsing' goes on", state()["timer"]["rehearsing"] and ph.vis("#rehbar") and not ph.js("document.querySelector('.sheet.on')"))
    ph.pg.click("#reh-stop"); ph.wait(600)
    ph.pg.click("#r-discard"); ph.wait(200); check("Discard asks for a second tap", state()["timer"]["rehearsing"] and "arm" in ph.cls("#r-discard"))
    ph.wait(3700); check("and forgets it was asked after a few seconds", "arm" not in ph.cls("#r-discard") and ph.text("#r-discard") == "Discard it")
    ph.pg.click("#r-save"); ph.wait(900)
    s = state()
    check("saved: the recap opens, the bar goes, the clock is cleared for the real talk", s["plan"] and s["plan"]["match"] and ph.vis("#recap-rows") and not ph.vis("#rehbar") and not s["timer"]["rehearsing"] and s["timer"]["elapsed"] == 0, s["plan"])
    check("recap of a rehearsal: one row per shown slide, no comparison key", ph.pg.locator("#recap-rows .n").count() == 7 and not ph.vis("#recap-key"), ph.pg.locator("#recap-rows .n").count())
    ph.pg.click("#s-recap [data-close]"); ph.wait(300)
    # the real talk against it
    post("/api/timer", {"dur": 60}); cmd("first"); ph.wait(300); ph.tap("#surface"); ph.wait(1500)
    check("with a rehearsal the button says where you stand", ph.text("#s-sub") in ("On pace",) or "ahead" in ph.text("#s-sub") or "behind" in ph.text("#s-sub"), ph.text("#s-sub"))
    ph.wait(1200); post("/api/timer", {"action": "pause"})
    ph.pg.click("#b-menu"); ph.wait(300)
    check("the sheet reads like a sentence, with a readable date", "Rehearsed in 0:" in ph.text("#r-text") and "fitted to your 1:00 talk" in ph.text("#r-text") and "2026," in ph.text("#r-text"), ph.text("#r-text"))
    ph.pg.click("#r-recap"); ph.wait(700)
    plan_total = state()["plan"]["total"]
    check("recap of a run: bars for this run, ticks for the rehearsal fitted to the talk length, and the key says so", ph.vis("#recap-key") and "fitted to 1:00" in ph.text("#recap-plan") and ph.pg.locator("#recap-rows .tick").count() == 7, ph.text("#recap-key"))
    ticks = ph.js("[...document.querySelectorAll('#recap-rows .tick')].map(t => parseFloat(t.style.left))")
    check("the ticks are the fitted plan (the longest is the widest thing in the chart)", max(ticks) > 99 and plan_total < 20, (ticks, plan_total))
    ph.shot("clock_recap")
    ph.pg.click("#s-recap [data-close]"); ph.wait(300); ph.pg.click("#b-menu"); ph.wait(300)
    ph.pg.click("#r-forget"); ph.wait(200); check("forgetting a rehearsal asks twice", state()["plan"] is not None and "arm" in ph.cls("#r-forget"))
    ph.pg.click("#r-forget"); ph.wait(400); check("then forgets", state()["plan"] is None)
    # the show ends while a rehearsal is open
    ph.pg.click("#s-menu [data-close]"); ph.wait(300)
    post("/api/rehearsal", {"action": "start"}); ph.wait(900); cmd("end"); ph.wait(700)
    check("show ended mid-rehearsal: no sheet jumps up; the bar stays, now 'paused', and Stop is pointed out", not ph.js("document.querySelector('.sheet.on')") and "save this rehearsal" in ph.text("#toast").lower() and ph.vis("#rehbar") and ph.text("#reh-t").startswith("Rehearsal paused at") and "nudge" in ph.cls("#reh-stop") and not state()["timer"]["running"], (ph.text("#toast"), ph.text("#reh-t")))
    ph.pg.click("#reh-stop"); ph.wait(600)
    check("a rehearsal of a second or two cannot be saved, and says why", ph.pg.is_disabled("#r-save") and "Too short to save" in ph.text("#stop-note"), ph.text("#stop-note"))
    ph.pg.click("#r-discard"); ph.wait(150); ph.pg.click("#r-discard"); ph.wait(600)
    check("discarding from there ends it, says so, and offers Undo", not state()["timer"]["rehearsing"] and not ph.vis("#rehbar") and "discarded" in ph.text("#snack-t").lower() and ph.text("#snack-b") == "Undo", ph.text("#snack-t"))
    ph.close()


def part_picture(b):
    """Pictures, the laser, and what this phone shows."""
    fresh(show=True, slide=2)
    ph = Phone(b, seen=True)
    lasers = []
    ph.pg.on("request", lambda r: lasers.append(json.loads(r.post_data)) if "/api/laser" in r.url else None)
    ph.open()
    box = lambda sel: ph.pg.locator(sel).bounding_box()
    p = box("#pic"); nb = box("#nextbox"); cue = box("#cuetext")
    check("tall phone: the slide uses the full width; the next slide sits beside the notes", abs(p["width"] - 390) < 2 and abs(p["width"] / p["height"] - 16 / 9) < 0.02 and nb["y"] > p["y"] + p["height"] and nb["x"] > cue["x"] + cue["width"] - 2, (p, nb))
    ph.tap("#pic", 0.5, 0.5); ph.wait(300)
    check("a brush of the picture does not fire the laser", not any(l["on"] for l in lasers), lasers)
    ph.pg.mouse.move(p["x"] + p["width"] * 0.25, p["y"] + p["height"] * 0.75); ph.pg.mouse.down(); ph.wait(450)
    on = [l for l in lasers if l["on"]]
    check("holding it does, at the place held", on and abs(on[-1]["x"] - 0.25) < 0.02 and abs(on[-1]["y"] - 0.75) < 0.03 and ph.vis("#dot"), on[-1:] )
    ph.pg.mouse.move(p["x"] + p["width"] * 0.9, p["y"] + p["height"] * 0.1, steps=4); ph.wait(250); on = [l for l in lasers if l["on"]]
    check("and the dot follows the finger", abs(on[-1]["x"] - 0.9) < 0.02 and abs(on[-1]["y"] - 0.1) < 0.03, on[-1:])
    ph.pg.mouse.up(); ph.wait(300); check("lifting the finger turns it off", lasers[-1]["on"] is False and not ph.vis("#dot"))
    # a picture that cannot be fetched
    ph.pg.route("**/api/slide/3.jpg*", lambda r: r.abort())
    cmd("goto", n=3); ph.wait(900)
    check("a picture that fails to load is not replaced by the previous slide's: the phone says there is none", not ph.vis("#curimg") and "No picture of this slide" in ph.text("#veil") and ph.text("#cur") == "3", ph.text("#veil"))
    ph.shot("picture_missing")
    ph.pg.unroute("**/api/slide/3.jpg*"); ph.until(lambda: ph.vis("#curimg"), 6000)
    check("and it is fetched again by itself", ph.vis("#curimg") and not ph.vis("#veil") and "/api/slide/3.jpg" in ph.pg.get_attribute("#curimg", "src"))
    # options
    ph.pg.click("#b-menu"); ph.wait(300); ph.pg.click("#m-setup"); ph.wait(300)
    ph.pg.click("#p-pic"); ph.wait(200)
    check("switches say what they do, and tell assistive tech their state", ph.pg.get_attribute("#p-pic", "aria-checked") == "false" and "more room for notes" in ph.text("#p-pic") and ph.pg.get_attribute("#p-pic", "role") == "switch")
    ph.pg.click("#m-bigger"); ph.pg.click("#m-bigger"); ph.wait(100)
    check("'Make the slide pictures again' is only offered when no show runs", ph.pg.is_disabled("#m-pics") and "no slide show" in ph.text("#m-pics-t"), ph.text("#m-pics-t"))
    ph.pg.click("#su-go"); ph.wait(300)
    nb = box("#nextbox"); cue = box("#cuetext")
    check("slide picture off: no stage, notes get the room, next slide beside them", not ph.vis("#stage") and ph.vis("#nextbox") and cue["height"] > 380 and nb["x"] > cue["x"] + cue["width"] - 2, cue)
    check("notes size follows the A+ button", ph.js("getComputedStyle(document.getElementById('cue1')).fontSize") == "27.6px", ph.js("getComputedStyle(document.getElementById('cue1')).fontSize"))
    ph.shot("picture_off")
    cmd("black"); ph.wait(400); check("blacked out: the stage comes back to say so", ph.vis("#stage") and "blacked out" in ph.text("#veil"))
    cmd("black")
    ph.js("localStorage.removeItem('cuewand.prefs'); localStorage.removeItem('cuewand.scale')")
    ph.close()
    # remaking pictures while idle
    fresh()
    ph = Phone(b, seen=True).open()
    ph.pg.click("#b-menu"); ph.wait(300); ph.pg.click("#m-setup"); ph.wait(300)
    ph.pg.locator("#m-pics").scroll_into_view_if_needed(); ph.pg.click("#m-pics"); ph.wait(300)
    check("with the deck open and no show, the pictures can be made again from the phone", "Making the slide pictures again" in ph.text("#toast") and not ph.pg.is_disabled("#m-pics"), ph.text("#toast"))
    ph.close()


def part_small(b):
    """Small phones, landscape, and an iPhone-like browser that cannot vibrate."""
    for (w, h) in ((360, 560), (320, 568), (390, 664)):
        fresh()
        ph = Phone(b, w, h).open(wait=300); ph.wait(1000); tag = f"{w}x{h}"
        inside = lambda sel: (lambda r: r is not None and r["x"] >= -0.5 and r["y"] >= -0.5 and r["x"] + r["width"] <= w + 0.5 and r["y"] + r["height"] <= h + 0.5)(ph.pg.locator(sel).bounding_box())
        check(f"{tag} Setup: heading and both buttons on screen", inside("#su-h") and inside("#su-go") and inside("#su-skip")); ph.shot(f"small_{tag}_setup")
        ph.pg.click("#su-go"); ph.until(lambda: ph.text("#ck-go") != "Checking", 15000); ph.wait(200)
        check(f"{tag} check: the verdict is on screen, not cut off, and so is its button", inside("#ck-h") and inside("#ck-go") and inside("#ck-skip"), ph.pg.locator("#ck-h").bounding_box()); ph.shot(f"small_{tag}_check")
        sc = ph.js("(() => { const e = document.querySelector('#check .scroll'); e.scrollTop = e.scrollHeight; return [e.scrollHeight, e.clientHeight, document.querySelector('#ck-list li:last-child').getBoundingClientRect().bottom, document.querySelector('#check .foot').getBoundingClientRect().top]; })()")
        check(f"{tag} check: the last line scrolls clear of the button bar", sc[2] <= sc[3] + 1, sc)
        ph.wait(800); ph.pg.click("#ck-skip"); ph.wait(400)
        check(f"{tag} deck open: name and all three start buttons fully on screen", inside("#rest-h") and inside("#rest-start") and inside("#rest-cur") and inside("#rest-reh") and ph.text("#rest-h") == "Demo deck.pptx is open"); ph.shot(f"small_{tag}_rest")
        ph.wait(900); ph.pg.click("#rest-start"); ph.wait(700); cmd("goto", n=2); cmd("next"); ph.wait(500)
        a, t = ph.pg.locator("#where").bounding_box(), ph.pg.locator("#tools").bounding_box()
        pips = ph.pg.locator("#pips").bounding_box()
        check(f"{tag} talk: step dots and the two pills do not collide", pips["x"] + pips["width"] <= t["x"] + 0.5 and a["x"] + a["width"] <= t["x"] + 0.5, (pips, t))
        tb, mb = ph.pg.locator("#b-menu").bounding_box(), ph.pg.locator("#b-slides").bounding_box()
        check(f"{tag} talk: pills are at least 44 px tall, and all of the page fits", tb["height"] >= 44 and mb["height"] >= 44 and inside("#surface") and inside("#back") and inside("#b-slides"), (tb, mb))
        cue = ph.pg.locator("#cuetext").bounding_box(); pb = ph.pg.locator("#pads").bounding_box()
        check(f"{tag} talk: notes keep real room above the buttons", cue["height"] >= 80 and cue["y"] + cue["height"] <= pb["y"] + 1, cue)
        ph.shot(f"small_{tag}_talk")
        ph.pg.click("#b-slides"); ph.wait(300)
        a2, t2 = ph.pg.locator("#where").bounding_box(), ph.pg.locator("#tools").bounding_box()
        check(f"{tag} Slides: the status, Menu and 'Back to talk' fit in the top row", a2["x"] + a2["width"] <= t2["x"] + 0.5 and t2["x"] + t2["width"] <= w + 0.5 and inside("#qbar"), (a2, t2))
        ph.pg.click("#b-slides"); ph.wait(200)
        if (w, h) == (360, 560):
            p, nb = ph.pg.locator("#pic").bounding_box(), ph.pg.locator("#nextbox").bounding_box()
            check(f"{tag} talk: short phone, so the next slide sits beside the picture instead of black bars", nb["x"] >= p["x"] + p["width"] and nb["y"] < p["y"] + p["height"], (p, nb))
        ph.close()
    # long notes
    fresh(show=True, slide=1)
    ph = Phone(b, 360, 560, seen=True, ts=2).open()
    check("notes longer than their space fade out at the bottom and say there is more", "more" in ph.cls("#cuetext") and ph.vis("#more"), ph.cls("#cuetext")); ph.shot("small_long_notes")
    ph.js("document.getElementById('cuetext').scrollTop = 9999"); ph.wait(200)
    check("and stop saying so at the end", "more" not in ph.cls("#cuetext") and not ph.vis("#more"))
    ph.close()
    # landscape
    fresh(show=True, slide=4)
    ph = Phone(b, 844, 390, seen=True).open()
    p, s, c = ph.pg.locator("#pic").bounding_box(), ph.pg.locator("#surface").bounding_box(), ph.pg.locator("#cuetext").bounding_box()
    check("landscape: picture left, notes and buttons right, nothing off screen", p["x"] + p["width"] <= s["x"] and s["y"] + s["height"] <= 390 and c["height"] > 50 and abs(p["width"] / p["height"] - 16 / 9) < 0.03, (p, s, c)); ph.shot("small_landscape")
    ph.pg.click("#b-menu"); ph.wait(300); ph.pg.click("#m-setup"); ph.wait(300)
    r = ph.pg.locator("#su-go").bounding_box(); check("landscape Setup: its button is on screen", r["y"] + r["height"] <= 390)
    ph.close()
    # a browser that cannot vibrate (every iPhone)
    fresh()
    ph = Phone(b, 390, 844, vibrate=False).open(wait=300); ph.wait(1000)
    check("no vibration: Setup says alerts are seen, not felt", "cannot vibrate" in ph.text("#t-how"), ph.text("#t-how"))
    ph.pg.click("#su-go"); ph.until(lambda: ph.text("#ck-go") != "Checking", 15000)
    lines = [(li.get_attribute("class"), li.inner_text().replace("\n", " / ")) for li in ph.pg.locator("#ck-list li").all()]
    check("no vibration: the check explains the flashes, and can still say 'Ready to present'", ph.text("#ck-h") == "Ready to present" and any(c == "note" and "cannot vibrate" in t and "flash" in t for c, t in lines), (ph.text("#ck-h"), lines))
    ph.shot("small_iphone_check")
    ph.wait(1050); ph.pg.click("#ck-go"); ph.wait(900); ph.tap("#surface"); ph.wait(120)
    check("each outcome has its own flash: new slide", ph.cls("#pads") == "fx-slide"); ph.shot("small_fx_slide")
    ph.wait(900); ph.tap("#surface"); ph.wait(120); check("... a step on the same slide", ph.cls("#pads") == "fx-build"); ph.shot("small_fx_build")
    ph.wait(900); cmd("first"); ph.wait(300); ph.tap("#back"); ph.wait(150); check("... nothing moved", ph.cls("#pads") == "fx-none" and ph.text("#s-main") == "At the start", ph.text("#s-main")); ph.shot("small_fx_none")
    ph.close()


def part_access(b):
    """Keyboard, focus, zoom, names."""
    fresh(show=True, slide=3)
    ph = Phone(b, seen=True).open()
    check("pinch-zoom is not switched off", "user-scalable" not in ph.js("document.querySelector('meta[name=viewport]').content"))
    seen = []
    for _ in range(14):
        ph.pg.keyboard.press("Tab"); seen.append(ph.js("(() => { const e = document.activeElement; return (e.closest('.sheet') ? 'SHEET:' : '') + (e.closest('.full') ? 'FULL:' : '') + (e.id || e.tagName); })()"))
    check("Tab never lands in a closed sheet or a hidden screen", not any(x.startswith(("SHEET", "FULL")) for x in seen) and "surface" in seen and "back" in seen, seen)
    ph.pg.focus("#surface"); ph.pg.keyboard.press("Enter"); ph.wait(350); check("Enter on Next presses it", state()["slide"] == 4)
    ph.pg.focus("#b-slides"); ph.pg.keyboard.press("Space"); ph.wait(400)
    check("Space on another button presses that button, not Next", state()["slide"] == 4 and ph.vis("#qbar"))
    ph.pg.keyboard.press("Space"); ph.wait(300)
    ph.js("document.activeElement.blur()"); ph.pg.keyboard.press("ArrowRight"); ph.wait(350)
    check("with nothing focused, the arrow keys work as a clicker", (state()["slide"], state()["click"]) == (4, 1), (state()["slide"], state()["click"]))
    names = ph.js("[...document.querySelectorAll('[role=dialog]')].map(d => [d.id, d.getAttribute('aria-modal'), !!document.getElementById(d.getAttribute('aria-labelledby'))])")
    check("every sheet and full screen is a named dialog", len(names) == 6 and all(m == "true" and lab for _, m, lab in names), names)
    check("the Next button's name carries the clock for a screen reader", ph.pg.get_attribute("#surface", "aria-label").startswith("Next"))
    check("press results are announced politely, the ticking clock is not", ph.pg.get_attribute("#say", "aria-live") == "polite" and ph.pg.get_attribute("#s-sub", "aria-live") is None)
    ph.pg.click("#b-slides") if ph.vis("#qbar") else None
    con = ph.js("""(() => { const lum = c => { const v = c.match(/[\\d.]+/g).slice(0, 3).map(x => { x /= 255; return x <= .03928 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); }); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
      const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
      const cs = id => getComputedStyle(document.getElementById(id));
      return {edge: ratio(cs('back').borderTopColor, 'rgb(0,0,0)'), pill: ratio(cs('b-menu').borderTopColor, 'rgb(0,0,0)'),
              tank: ratio(getComputedStyle(document.documentElement).getPropertyValue('--level').trim().replace(/^#(..)(..)(..)$/, (m, r, g, b) => `rgb(${parseInt(r, 16)},${parseInt(g, 16)},${parseInt(b, 16)})`), 'rgb(10,13,19)'),
              dim: ratio(cs('tot').color, 'rgb(0,0,0)')}; })()""")
    check("outlines of controls, and the clock level against its empty part, are at least 3:1", con["edge"] >= 3 and con["pill"] >= 3 and con["tank"] >= 3 and con["dim"] >= 4.5, con)
    ph.close()


def fake_state(ph, change):
    """Rewrite what the computer says, inside this test browser only."""
    def handle(route):
        try:
            r = route.fetch(); s = json.loads(r.text())
            if s.get("show") == "running": change(s)
            route.fulfill(response=r, body=json.dumps(s))
        except Exception:
            pass        # the phone gave up on that request meanwhile
    ph.pg.route("**/api/state*", handle)


def part_v23(b):
    """2.3: notes per click, text size, layouts, find a slide, back-to, co-presenters, undo, every kind of press, contrast."""
    # ---- notes that follow the clicks ----
    fresh(show=True, slide=2)
    ph = Phone(b, seen=True).open()
    meta = lambda: ph.text("#metaline").lower()
    check("notes with [click] marks: only what to say now, labelled, with the next click under it", "before step 1" in meta() and ph.text("#cue1") == "Three reasons, one per click." and ph.text("#nextclick").startswith("Next click: Too many slides"), (meta(), ph.text("#cue1"), ph.text("#nextclick")))
    ph.tap("#surface"); ph.wait(400)
    check("a click moves the notes on: step 1 of 3", "step 1 of 3" in meta() and ph.text("#cue1").startswith("Too many slides") and "No rehearsal" in ph.text("#nextclick"), (meta(), ph.text("#cue1")))
    ph.tap("#surface"); ph.wait(900); ph.tap("#surface"); ph.wait(400)
    check("on the last step it previews the next slide's first line", "step 3 of 3" in meta() and ph.text("#nextclick").startswith("Next slide: If a slide needs the word"), ph.text("#nextclick"))
    ph.pg.click("#wholebtn"); ph.wait(200)
    paras = ph.js("[...document.querySelectorAll('#cueall p')].map(p => p.className)")
    check("'Whole note' shows every step, the current one marked", ph.vis("#cueall") and paras == ["", "", "", "now"] and ph.pg.get_attribute("#wholebtn", "aria-pressed") == "true" and not ph.vis("#cue1"), paras)
    ph.pg.click("#wholebtn"); ph.wait(200); check("and goes back to the step", ph.vis("#cue1") and not ph.vis("#cueall"))
    ph.shot("v23_notes_steps")
    fake_state(ph, lambda s: s.update(notes="One[click]Two[click]Three", clicks=3, clicksOk=True))
    ph.until(lambda: ph.vis("#notsplit"), 9000)
    check("marks that do not match PowerPoint's steps: the whole note, and a line saying why", ph.vis("#notsplit") and "2 click marks, 3 steps" in ph.text("#notsplit") and "step" not in meta(), (ph.text("#notsplit"), meta()))
    ph.pg.unroute("**/api/state*"); fake_state(ph, lambda s: s.update(notes="One[click]Two", clicksOk=False))
    ph.until(lambda: "did not say" in ph.text("#notsplit"), 9000)
    check("PowerPoint not saying how many steps: the whole note, and why", "did not say how many steps" in ph.text("#notsplit"), ph.text("#notsplit"))
    ph.pg.unroute("**/api/state*"); ph.wait(3800)
    ph.close()

    # ---- text size: one number, changed mid-talk without leaving the talk ----
    fresh(show=True, slide=5)
    ph = Phone(b, seen=True).open()
    ph.pg.click("#b-menu"); ph.wait(350); ph.pg.click("#m-size"); ph.wait(300)
    check("Menu › Text size: the Menu closes to a bar over Back/Next; the notes stay in view", ph.vis("#sizebar") and not ph.vis("#pads") and ph.vis("#cue1") and ph.text("#sb-val") == "100 %", ph.text("#sb-val"))
    ph.pg.click("#sb-plus"); ph.pg.click("#sb-plus"); ph.wait(150)
    check("A+ grows the notes there and then", ph.text("#sb-val") == "120 %" and ph.js("getComputedStyle(document.getElementById('cue1')).fontSize") == "27.6px")
    ph.shot("v23_sizebar")
    ph.pg.click("#sb-done"); ph.wait(200); check("Done brings Back and Next back", ph.vis("#pads") and not ph.vis("#sizebar"))
    ph.js("localStorage.removeItem('cuewand.ts')"); ph.close()
    def readable(ph, tag):
        r = ph.js("""(() => { const m = document.getElementById('s-main'), s = document.getElementById('surface').getBoundingClientRect(), mr = m.getBoundingClientRect(),
            c = document.getElementById('cuetext'), c1 = document.getElementById('cue1'), lh = parseFloat(getComputedStyle(c1).fontSize) * 1.24;
            return {cur: document.getElementById('cur').textContent, curVis: document.getElementById('cur').getBoundingClientRect().width > 0,
                    clockIn: mr.left >= s.left - 1 && mr.right <= s.right + 1 && m.scrollWidth <= m.clientWidth + 1, lines: (c.clientHeight - 30) / lh,
                    pic: getComputedStyle(document.getElementById('stage')).display}; })()""")
        check(f"{tag}: slide number, an unclipped clock and at least 4 lines of notes in view", r["curVis"] and r["cur"] == "5" and r["clockIn"] and r["lines"] >= 4, r)
        return r
    ph = Phone(b, 360, 640, seen=True, ts=2).open()
    r = readable(ph, "360×640 at 200 %")
    check("at 200 % the slide picture steps aside and the top buttons become icons, still named", r["pic"] == "none" and ph.text("#b-menu") == "" and ph.pg.get_attribute("#b-menu", "aria-label") == "Menu", r["pic"])
    ph.shot("v23_200pc"); ph.close()
    ph = Phone(b, 195, 422, seen=True).open(); readable(ph, "195×422 (a phone at 200 % zoom)"); ph.shot("v23_195"); ph.close()

    # ---- layouts, and a rotation that cannot move a button under a finger ----
    fresh(show=True, slide=2)
    ph = Phone(b, 844, 390, seen=True).open()
    tk, pd, cu = ph.pg.locator("#talk").bounding_box(), ph.pg.locator("#pads").bounding_box(), ph.pg.locator("#cue").bounding_box()
    check("phone landscape: picture column on the left; Back/Next at most 45 % of the right column, notes at least half", "lay-land" in ph.cls("#app") and pd["height"] <= 0.45 * tk["height"] + 2 and pd["y"] - cu["y"] >= 0.5 * tk["height"] - 2 and tk["x"] > 300, (tk, pd, cu))
    ph.shot("v23_land"); ph.close()
    ph = Phone(b, 820, 1180, seen=True).open()
    sf, bk = ph.pg.locator("#surface").bounding_box(), ph.pg.locator("#back").bounding_box()
    check("tablet: Next at most 520 px and Back at most 200 px, on the hand's side; notes 30 px", "lay-tab" in ph.cls("#app") and sf["width"] <= 521 and bk["width"] <= 201 and sf["x"] + sf["width"] > 790 and ph.js("getComputedStyle(document.getElementById('cue1')).fontSize") == "30px", (sf, bk))
    ph.shot("v23_tablet"); ph.close()
    ph = Phone(b, 1180, 820, seen=True).open()
    st, tk = ph.pg.locator("#stage").bounding_box(), ph.pg.locator("#talk").bounding_box()
    check("tablet landscape: a presenter view, slides on the left, notes and buttons on the right", "lay-desk" in ph.cls("#app") and tk["x"] >= st["x"] + st["width"] - 1, (st, tk))
    ph.pg.click("#b-slides"); ph.wait(300)
    check("and five columns of slides", ph.js("getComputedStyle(document.getElementById('grid')).gridTemplateColumns.split(' ').length") == 5)
    ph.shot("v23_desk"); ph.close()
    ph = Phone(b, seen=True).open(); here = state()["slide"]
    ph.pg.set_viewport_size({"width": 844, "height": 390}); ph.wait(250)
    check("turning the phone: the layout waits a moment", "lay-phone" in ph.cls("#app"))
    ph.wait(700)
    check("then changes, and Back/Next ignore presses for a second", "lay-land" in ph.cls("#app") and "cool" in ph.cls("#pads"))
    ph.tap("#surface"); ph.wait(300)
    check("so a press made as the buttons moved does nothing", state()["slide"] == here)
    check("and the button says why: 'Layout changed · Press again'", ph.text("#s-main") == "Layout changed" and ph.text("#s-sub") == "Press again", (ph.text("#s-main"), ph.text("#s-sub")))
    ph.close()

    # ---- find a slide, jump, come back ----
    fresh(show=True, slide=2)
    ph = Phone(b, seen=True).open()
    ph.pg.click("#b-slides"); ph.wait(1300)
    check("Slides: no slide picture above the grid, sections as headers, 'Hidden' as a badge", not ph.vis("#stage") and ph.pg.locator("#grid h2").count() == 3 and ph.text("#grid h2:first-child").lower() == "opening · slides 1–2" and ph.pg.locator("#grid .cap .badge").count() == 1)
    ph.pg.click("#q-q"); ph.wait(300)
    check("searching hides the bar and lists slides in one column", "finding" in ph.cls("#ques") and not ph.vis("#qbar") and ph.pg.locator("#q-list button").count() == 8)
    ph.pg.keyboard.type("third"); ph.wait(300)
    rows = [x.inner_text().split("\n")[0] for x in ph.pg.locator("#q-list button").all()]
    check("a word from the notes or the slide finds it, hidden backups too", len(rows) == 2 and rows[0].startswith("5") and "Hidden" in ph.text("#q-list button:nth-child(2)") and ph.pg.locator("#q-list mark").count() == 2, rows)
    ph.shot("v23_search")
    ph.pg.locator("#q-list button").first.dispatch_event("pointerdown"); ph.pg.locator("#q-list button").first.click(); ph.wait(400)
    check("with the keyboard open, the first tap only closes the keyboard", state()["slide"] == 2 and ph.js("document.activeElement.id") != "q-q", state()["slide"])
    ph.pg.locator("#q-list button").first.click(); ph.wait(500)
    check("the second goes there", state()["slide"] == 5)
    ph.pg.click("#b-slides"); ph.wait(300)
    check("a jump to an ordinary slide: Back stays plain Back (the way back is for backup slides)", ph.text("#back") == "Back" and "ret" not in ph.cls("#back"), ph.text("#back"))
    ph.pg.click("#b-slides"); ph.wait(1300); ph.pg.locator("#grid button[data-n='6']").click(); ph.wait(700)
    check("a jump to a hidden backup slide: the Slides view's Back offers the way back", state()["slide"] == 6 and ph.text("#q-prev") == "Back to 5" and ph.pg.get_attribute("#q-prev", "aria-label") == "Back to slide 5", ph.text("#q-prev"))
    ph.pg.click("#b-slides"); ph.wait(300)
    check("so does the talk's Back", ph.text("#back") == "Back to slide 5" and ph.pg.get_attribute("#back", "aria-label") == "Back to slide 5" and "ret" in ph.cls("#back"), ph.text("#back"))
    ph.shot("v23_backto")
    ph.tap("#back"); ph.wait(500)
    check("and takes you there", state()["slide"] == 5 and ph.text("#back") == "Back", ph.text("#back"))
    ph.pg.click("#b-slides"); ph.wait(1300); ph.pg.locator("#grid button[data-n='6']").click(); ph.wait(700); ph.pg.click("#b-slides"); ph.wait(1100)
    ph.tap("#surface"); ph.wait(700)
    check("Next from the backup slide lands on an ordinary one: the way back ends there", state()["slide"] == 7 and ph.text("#back") == "Back", (state()["slide"], ph.text("#back")))
    cmd("goto", n=1); ph.wait(1200)
    ph.pg.click("#b-slides"); ph.wait(1300); ph.pg.locator("#grid button[data-n='4']").click(); ph.wait(700); ph.pg.click("#b-slides"); ph.wait(1100)
    for _ in range(12):
        if state()["slide"] == 8: break
        ph.tap("#surface"); ph.wait(750)
    ph.wait(900); ph.tap("#surface"); ph.wait(250)
    check("skip ahead to an ordinary slide, then Next to the end: 'Last slide', never 'Backup slide'", state()["slide"] == 8 and ph.text("#s-main") == "Last slide" and ph.text("#back") == "Back", (state()["slide"], ph.text("#s-main"), ph.text("#back")))
    ph.wait(1500); ph.tap("#back"); ph.wait(700)
    check("and Back goes to the slide before, not to where the skip started", state()["slide"] == 7, state()["slide"])
    ph.pg.click("#b-slides"); ph.wait(1300); ph.pg.click("#q-q"); ph.pg.keyboard.type("6"); ph.wait(300)
    check("a number puts that slide first", ph.pg.locator("#q-list button").first.inner_text().startswith("6"))
    ph.pg.fill("#q-q", "zzzq"); ph.pg.dispatch_event("#q-q", "input"); ph.wait(300)
    check("nothing found says so, with a way to clear", "No slide matches" in ph.text("#q-list") and ph.vis("#q-list .none button"), ph.text("#q-list"))
    ph.pg.click("#q-x"); ph.wait(200); ph.pg.keyboard.press("Escape"); ph.js("document.activeElement.blur()"); ph.wait(300)
    fake_state(ph, lambda s: s.update(next=None, click=s["clicks"], backup=True))       # a deck whose backups sit after the last shown slide
    cmd("goto", n=3); ph.wait(900)
    ph.pg.locator("#grid button[data-n='6']").click(); ph.wait(900)
    ph.pg.click("#b-slides"); ph.wait(1100); ph.tap("#surface"); ph.wait(250)
    check("on a backup slide at the end, Next says it is a backup, and where Back goes", ph.text("#s-main") == "Backup slide" and ph.text("#s-sub") == "Back returns to 3", (ph.text("#s-main"), ph.text("#s-sub")))
    ph.pg.unroute("**/api/state*")
    Z = Phone(b, seen=True); fake_state(Z, lambda s: s.update(next=None, click=s["clicks"], backup=True)); Z.open(wait=1500)
    Z.wait(1100); Z.tap("#surface"); Z.wait(250)
    check("a phone that did not make the jump (a co-presenter's) still calls it a backup, and says how to get back", Z.text("#s-main") == "Backup slide" and Z.text("#s-sub") == "Slides to go back", (Z.text("#s-main"), Z.text("#s-sub")))
    Z.pg.unroute("**/api/state*"); Z.close()
    ph.close()

    # ---- co-presenters ----
    fresh(show=True, slide=2)
    A = Phone(b, seen=True, name="Tomer").open(); A.wait(1200); B2 = Phone(b, seen=True, name="Ana").open(wait=300)
    check("mid-talk, a phone joining is a quiet word above the notes, not a message over the slide", A.until(lambda: "ana joined" in A.text("#metaline").lower(), 5000) and "on" not in A.cls("#toast"), (A.text("#metaline"), A.cls("#toast")))
    B2.wait(1200)
    a_cid, b_cid = A.js("localStorage.getItem('cuewand.cid')"), B2.js("localStorage.getItem('cuewand.cid')")
    A.wait(3500); A.pg.click("#b-menu"); A.wait(400)
    check("two phones: the Menu offers to pass the slides, by name", A.vis("#mh-co") and "Pass the slides to Ana" in A.text("#co-list") and "Every phone can press Next" in A.text("#co-text") and "this one is Tomer" in A.text("#co-text"), A.text("#co-list"))
    A.shot("v23_menu_co")
    row = A.pg.locator("#co-list button", has_text="Ana").first
    row.click(); A.wait(200)
    check("passing asks for a second tap", "Tap again to pass to Ana" in A.text("#co-list"))
    row.click(); A.wait(900)
    check("then Ana's phone has the slides", state()["control"]["holder"] == b_cid)
    check("this phone follows: a band says so, and the buttons are hatched", A.vis("#folbar") and A.text("#fol-t") == "Following Ana" and "follow" in A.cls("#pads"), A.text("#fol-t"))
    A.wait(2600)
    check("and Next says how to take them back", A.text("#s-hint") == "Hold to take the slides", A.text("#s-hint"))
    A.shot("v23_following"); here = state()["slide"]; A.tap("#surface"); A.wait(400)
    check("a press on the following phone sends nothing and says who has the slides", state()["slide"] == here and A.text("#s-main") == "Ana has the slides" and A.text("#s-sub") == "Hold to take", (A.text("#s-main"), A.text("#s-sub")))
    r = post("/api/cmd", {"cmd": "next", "id": "copres-1", "cid": a_cid})
    check("the computer refuses it too ('not-yours'), whatever the phone sends", r["press"]["result"] == "not-yours" and state()["slide"] == here, r["press"])
    B2.wait(1200)
    check("Ana's phone was told on its own Next button", B2.text("#s-main") in ("You have the slides",) or "You have the slides" in B2.text("#say"), (B2.text("#s-main"), B2.text("#say")))
    B2.wait(2000); B2.tap("#surface"); B2.wait(400); check("and its presses work", state()["slide"] == here + 0 or (state()["click"] > 0 or state()["slide"] > here))
    A.wait(1500)
    box = A.pg.locator("#surface").bounding_box(); A.pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); A.pg.mouse.down(); A.wait(450)
    check("holding Next fills a ring", "on" in A.cls("#holdring"))
    A.wait(650); A.pg.mouse.up(); A.wait(700)
    check("held 0.8 s, it takes the slides back", state()["control"]["holder"] == a_cid and not A.vis("#folbar"))
    B2.wait(3800)
    check("and the other phone is told on its button and in its band", B2.vis("#folbar") and B2.text("#fol-t") == "Following Tomer", B2.text("#fol-t"))
    info = json.loads(urllib.request.urlopen(B + f"/api/host/info?h={H}", timeout=5).read())
    check("the pairing page lists the phones by name, and which has the slides", {p["name"] for p in info["phoneList"]} >= {"Tomer", "Ana"} and any(p["holder"] and p["name"] == "Tomer" for p in info["phoneList"]), info["phoneList"])
    A.pg.goto("about:blank"); B2.wait(3800)
    check("the phone with the slides closes its page: the other is offered them at once", B2.text("#fol-t") == "Tomer is not connected", B2.text("#fol-t"))
    B2.pg.click("#fol-take"); B2.wait(150); B2.pg.click("#fol-take"); B2.wait(800)
    check("'Take' in the band (two taps) takes them", state()["control"]["holder"] == b_cid and not B2.vis("#folbar"))
    B2.pg.click("#b-menu"); B2.wait(400)
    B2.pg.locator("#co-list button", has_text="Let every phone press").click(); B2.wait(150)
    B2.pg.locator("#co-list button", has_text="Tap again").click(); B2.wait(600)
    check("'Let every phone press' goes back to how it was", state()["control"]["holder"] is None)
    C = Phone(b, seen=True).open(wait=2500)
    check("a phone with no name that joins during a show is not interrupted: nothing pops up over its notes or near Next", "on" not in C.cls("#snack"), C.text("#snack-t"))
    c_cid = C.js("localStorage.getItem('cuewand.cid')")
    nm = next((p["name"] for p in state()["control"]["phones"] if p["cid"] == c_cid), "")
    check("its stand-in name has no look-alike characters (no 0/O, no 1/I)", re.fullmatch(r"(Phone|Android phone|iPhone|iPad) [ACDEFGHJKMNPQRTVWXY34679]{2}", nm) is not None, nm)
    C.pg.click("#b-menu"); C.wait(400)
    check("Menu › Co-presenters offers 'Name this phone', saying how the others see it now", "Name this phone" in C.text("#co-list") and nm in C.text("#co-name"), C.text("#co-list"))
    C.pg.click("#co-name"); C.wait(500)
    check("and it opens Setup at the name", C.vis("#setup") and C.js("document.activeElement.id") == "su-name", C.js("document.activeElement.id"))
    C.close(); cmd("end"); B2.wait(1500)
    D = Phone(b, seen=True).open(wait=2500)
    check("before a show, a phone with no name is asked for one when another phone is there", "on" in D.cls("#snack") and "is connected too" in D.text("#snack-t") and "Give this phone a name" in D.text("#snack-t") and D.text("#snack-b") == "Name it", D.text("#snack-t"))
    cmd("start"); D.wait(1500)
    check("and the question goes away when the show starts, so the talk opens clear", "on" not in D.cls("#snack"), D.cls("#snack"))
    D.close(); A.close(); B2.close()

    # ---- undo, and every kind of press counting once ----
    fresh(show=True, slide=2)
    ph = Phone(b, seen=True).open(); post("/api/timer", {"action": "start"}); ph.wait(2200)
    ph.pg.click("#b-menu"); ph.wait(350); ph.pg.click("#t-reset"); ph.pg.click("#t-reset"); ph.wait(400)
    check("a reset clock offers Undo for a few seconds", state()["timer"]["elapsed"] == 0 and ph.vis("#snack") and ph.text("#snack-b") == "Undo", ph.text("#snack-t"))
    ph.pg.keyboard.press("Escape"); ph.wait(300); ph.pg.click("#snack-b"); ph.wait(500)
    check("Undo brings the clock back", state()["timer"]["elapsed"] > 1.5 and state()["timer"]["running"], state()["timer"])
    def one(how, act):
        s0 = state(); act(); ph.wait(600); s1 = state()
        steps = (s1["slide"] - s0["slide"]) * 10 + (s1["click"] - s0["click"])
        check(f"{how}: exactly one press", steps in (1, 10 - s0["click"]) and (s1["slide"], s1["click"]) != (s0["slide"], s0["click"]), (s0["slide"], s0["click"], s1["slide"], s1["click"]))
        ph.wait(900)
    cmd("goto", n=3); ph.wait(1500)
    one("a screen reader's or Voice Access's plain click", lambda: ph.js("document.getElementById('surface').click()"))
    one("a mouse click (press plus its trailing click)", lambda: ph.pg.click("#surface"))
    one("a touch", lambda: ph.tap("#surface"))
    def key(k):
        ph.pg.focus("#surface"); ph.pg.keyboard.press(k)
    one("Enter on the focused button", lambda: key("Enter"))
    cmd("goto", n=3); ph.wait(1200)
    one("Space on the focused button", lambda: key(" "))
    ph.js("document.activeElement.blur()")
    # feedback within 0.1 s of the finger lifting
    cmd("goto", n=3); ph.wait(1500)
    ph.js("""window.__lat = null; (() => { const s = document.getElementById('surface'), m = document.getElementById('s-main'); let t0 = 0;
      document.getElementById('pads').addEventListener('pointerup', () => { t0 = performance.now(); }, {capture: true, once: true});
      new MutationObserver((ms, o) => { if (t0) { window.__lat = performance.now() - t0; o.disconnect(); } }).observe(m, {childList: true, characterData: true, subtree: true}); })()""")
    ph.tap("#surface"); ph.wait(500); lat = ph.js("window.__lat")
    check("the outcome is named on the button within 0.1 s of the finger lifting (local network)", lat is not None and lat < 100, lat)
    ph.close()

    # ---- the Next button's words are readable in every state ----
    fresh(show=True, slide=3)
    ph = Phone(b, seen=True).open()
    CON = """(() => { const lum = c => { const v = c.match(/[\\d.]+/g).slice(0, 3).map(x => { x /= 255; return x <= .03928 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); }); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
      const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
      const s = document.getElementById('surface'), bg = getComputedStyle(s).backgroundColor, fillc = getComputedStyle(document.getElementById('fill')).backgroundColor;
      const lvl = parseFloat(getComputedStyle(s).getPropertyValue('--lvl')) || 0;
      const [light, ink] = [...s.querySelectorAll('.face')].map(f => getComputedStyle(f.querySelector('.f-main')).color);
      const out = {state: s.className, digits: ratio(light, bg), labels: ratio(getComputedStyle(s.querySelector('.face .f-hint')).color, bg)};
      if (lvl > 0) { out.digitsOnFill = ratio(ink, fillc); out.fillVsEmpty = ratio(fillc, bg); }
      return out; })()"""
    def contrast(tag):
        c = ph.js(CON)
        ok = c["digits"] >= 7 and c["labels"] >= 4.5 and c.get("digitsOnFill", 7) >= 7 and c.get("fillVsEmpty", 3) >= 3
        check(f"contrast on the Next button, {tag}: digits at least 7:1 and labels 4.5:1 on what they sit on", ok, c)
    contrast("not started")
    post("/api/timer", {"action": "start"}); ph.wait(600); contrast("calm")
    post("/api/timer", {"dur": 75, "marks": [60]}); ph.wait(600); contrast("short of time")
    post("/api/timer", {"action": "pause"}); ph.wait(600); contrast("paused")
    post("/api/timer", {"action": "start", "dur": 30}); ph.until(lambda: state()["timer"]["elapsed"] > 30.5, 40000, 500); ph.wait(400); contrast("over time")
    post("/api/timer", {"action": "reset", "dur": 900}); post("/api/timer", {"action": "start"}); ph.wait(600)
    def busy(r):
        try: r.fulfill(status=504, content_type="application/json", body='{"error":"x"}')
        except Exception: pass
    ph.pg.route("**/api/cmd", busy)
    ph.tap("#surface"); ph.wait(300); contrast("a press not done"); ph.pg.unroute("**/api/cmd"); ph.wait(2800)
    ph.ctx.set_offline(True); ph.until(lambda: "cut" in ph.cls("#surface"), 14000); ph.wait(300); contrast("no connection"); ph.ctx.set_offline(False); ph.wait(3000)
    ph.close()

    # ---- sections, pace per section, and the rest of the small things ----
    fresh(show=True, slide=2)
    post("/api/rehearsal", {"action": "start"})
    for n in (1, 2, 3, 4, 5, 7, 8):
        cmd("goto", n=n); time.sleep(0.9)
    post("/api/rehearsal", {"action": "save"}); post("/api/timer", {"action": "reset", "dur": 600}); cmd("goto", n=2); post("/api/timer", {"action": "start"})
    ph = Phone(b, seen=True).open(); ph.wait(300)
    cmd("goto", n=3); ph.wait(700)
    check("a new section is named above the notes for a moment", "the idea · 1/3" in ph.text("#metaline").lower(), ph.text("#metaline"))
    check("and an amber notch on Next marks where the section should end, from the rehearsal", ph.js("!document.getElementById('notch').hidden") and 0 < float(ph.js("parseFloat(document.getElementById('notch').style.bottom)")) < 100, ph.js("document.getElementById('notch').style.bottom"))
    ph.shot("v23_section")
    ph.wait(3300); check("the name goes again after 3 s", "the idea" not in ph.text("#metaline").lower(), ph.text("#metaline"))
    fake_state(ph, lambda s: (s["timer"].update(elapsed=400, running=True), s["section"].update(end=300)))
    ph.until(lambda: "move on" in ph.text("#metaline").lower(), 9000)
    check("more than 30 s past the section's planned end, the line above the notes says what to do; the only number is on Next", "the idea · move on" in ph.text("#metaline").lower() and not re.search(r"\d", ph.text("#metaline")), ph.text("#metaline"))
    ph.pg.unroute("**/api/state*"); ph.wait(3800)
    cmd("goto", n=2); cmd("next"); ph.wait(700)
    check("the top row's name includes the step, for a screen reader", ph.pg.get_attribute("#where", "aria-label") == "Slide 2 of 8, step 1 of 3", ph.pg.get_attribute("#where", "aria-label"))
    cmd("prev"); ph.wait(700)
    check("and before the first step it says so, not 'step 0'", ph.pg.get_attribute("#where", "aria-label") == "Slide 2 of 8, before step 1 of 3", ph.pg.get_attribute("#where", "aria-label"))
    cmd("next"); ph.wait(700)
    check("the picture is described by its slide and title", ph.pg.get_attribute("#curimg", "alt") == "Slide 2: Why most talks run over" and ph.vis("#allsteps"))
    check("the Next button's spoken name says minutes, not ticking seconds", re.fullmatch(r"Next, \d+ minutes? left", ph.pg.get_attribute("#surface", "aria-label") or "") is not None, ph.pg.get_attribute("#surface", "aria-label"))
    ph.pg.click("#b-menu"); ph.wait(300); ph.pg.click("#m-setup"); ph.wait(300)
    check("switches: the explanation is their description, not part of their name", ph.js("document.getElementById(document.getElementById('p-left').getAttribute('aria-describedby')).tagName") == "SMALL" and ph.js("document.getElementById(document.getElementById('p-left').getAttribute('aria-labelledby')).textContent") == "Left-handed")
    ph.pg.click("[data-motion=less]"); ph.wait(150)
    check("Motion › Less: no rippling or sliding", "still" in ph.cls("html") and ph.js("getComputedStyle(document.querySelector('.sheet')).transitionDuration") == "0s")
    ph.pg.click("[data-motion=phone]"); ph.wait(150)
    check("and back to the phone's own setting", "still" not in ph.cls("html"))
    ph.close()


def part_v23b(b):
    """Round-3 fixes: a lost answer settled from the show, Rehearse now from the middle, undo back to the slide."""
    fresh(show=True, slide=2)
    ph = Phone(b, 390, 844, seen=True).open()
    ph.ctx.set_offline(True); ph.until(lambda: "down" in ph.cls("#where"), 14000)
    ph.ctx.set_offline(False); ph.until(lambda: "ok" in ph.cls("#where"), 9000); ph.wait(800)
    check("after a lost connection the top buttons have their words back", ph.vis("#b-menu .lbl") and "compact" not in ph.cls("#app"), ph.cls("#app"))
    ph.close()
    fresh(show=True, slide=2)
    ph = Phone(b, seen=True).open(); ph.wait(600)
    def lost_answer(route):
        try:
            route.fetch(); route.abort()            # the computer carries the press out; its answer never comes back
        except Exception:
            pass
    def unknown(route):
        try: route.fulfill(status=200, content_type="application/json", body='{"result": "unknown"}')
        except Exception: pass
    ph.pg.route("**/api/cmd", lost_answer); ph.pg.route("**/api/press*", unknown)
    s0 = state(); ph.tap("#surface")
    ph.until(lambda: "arrive" in ph.text("#snack-t"), 9000); s1 = state()
    check("an answer lost, and the computer no longer knows the press: the show moved its way, so the phone says it arrived",
          "did arrive" in ph.text("#snack-t") and (s1["slide"], s1["click"]) == (2, 1) and (s0["slide"], s0["click"]) == (2, 0), (ph.text("#snack-t"), s1["slide"], s1["click"]))
    ph.pg.unroute("**/api/cmd"); ph.wait(5600)
    ph.pg.route("**/api/cmd", lambda r: r.abort())
    s0 = state(); ph.tap("#surface")
    ph.until(lambda: "did not arrive" in ph.text("#snack-t"), 9000); s1 = state()
    check("and when the show did not move, that it did not arrive: nothing was skipped", "did not arrive" in ph.text("#snack-t") and (s1["slide"], s1["click"]) == (s0["slide"], s0["click"]), ph.text("#snack-t"))
    ph.pg.unroute("**/api/cmd"); ph.pg.unroute("**/api/press*"); ph.close()

    fresh(show=True, slide=3)
    ph = Phone(b, seen=True).open()
    ph.pg.click("#b-menu"); ph.wait(300)
    check("the rehearsal actions are rows like the rest of the Menu, each saying what it does", "line" in ph.cls("#r-start") and "Goes to slide 1" in ph.text("#r-start") and "line" in ph.cls("#r-recap"))
    ph.pg.click("#r-start"); ph.wait(250)
    check("'Rehearse now' on slide 3 before the talk has started still asks first, as it moves the show", not state()["timer"]["rehearsing"] and ph.text("#r-start-t") == "Tap again: back to slide 1", ph.text("#r-start-t"))
    ph.pg.click("#r-start"); ph.until(lambda: state()["timer"]["rehearsing"], 5000); ph.wait(1100)
    check("then it offers Undo, saying where Undo goes", ph.text("#snack-b") == "Undo" and "slide 3" in ph.text("#snack-t") and state()["slide"] == 1, ph.text("#snack-t"))
    ph.pg.click("#snack-b"); ph.wait(1000)
    check("Undo: no rehearsal, and back on slide 3", not state()["timer"]["rehearsing"] and state()["slide"] == 3, (state()["timer"]["rehearsing"], state()["slide"]))
    ph.close()


FIT = r"""(() => {
  const out = [], vis = el => el && el.offsetParent !== null && el.getBoundingClientRect().height > 0;
  const sf = document.getElementById('surface'), s = sf.getBoundingClientRect();
  const m = document.getElementById('s-main').getBoundingClientRect(), u = document.getElementById('s-sub').getBoundingClientRect();
  const h = document.getElementById('s-hint'), hr = h.getBoundingClientRect();
  if (vis(sf)) {
    if (m.top < s.top + 6 || m.bottom > s.bottom - 2 || m.left < s.left + 1 || m.right > s.right - 1) out.push('time outside Next, or crowding its top edge');
    if (h.textContent && hr.height && Math.max(m.bottom, u.bottom) > hr.top + 1) out.push('time over the bottom line');
    if (m.height < 14) out.push('time tiny');
  }
  for (const id of ['tot', 'cur', 'back-t', 'back-s', 'wholebtn', 'metaline', 's-sub', 'nextclick']) {
    const el = document.getElementById(id); if (!vis(el)) continue;
    if (el.scrollWidth > el.clientWidth + 1) out.push(id + ' cut');
    const r = el.getBoundingClientRect(); if (r.right > innerWidth + 1 || r.left < -1) out.push(id + ' off screen');
  }
  const c1 = document.getElementById('cue1');
  if (vis(c1) && c1.textContent) { const fs = parseFloat(getComputedStyle(c1).fontSize); if (c1.getBoundingClientRect().width < fs * 4) out.push('notes column too narrow for its text'); }
  if (document.documentElement.scrollWidth > innerWidth + 1) out.push('page scrolls sideways');
  const c = document.getElementById('cuetext'), c2 = document.getElementById('cue2'), ml = document.getElementById('metaline');
  if (vis(c1) && c1.textContent) {                  // the note you are on: at least two whole lines clear of the fade (or all of it)
    const cr = c.getBoundingClientRect(), a = c1.getBoundingClientRect(), z = vis(c2) && c2.textContent ? c2.getBoundingClientRect() : a;
    const lh = parseFloat(getComputedStyle(c1).fontSize) * 1.24, fade = c.classList.contains('more') ? Math.min(54, 0.2 * cr.height) : 0;
    const top = Math.max(a.top, vis(ml) ? ml.getBoundingClientRect().bottom : cr.top), bottom = Math.min(z.bottom, cr.bottom - fade);
    if ((bottom - top) / lh < Math.min(2, (z.bottom - a.top) / lh) - 0.05) out.push('current note: ' + ((bottom - top) / lh).toFixed(1) + ' clear lines');
  }
  return out; })()"""


def part_fit(b):
    """Every layout at every text size, and the places where room runs short."""
    fresh(show=True, slide=2); post("/api/timer", {"action": "start", "dur": 1500})
    fails = []
    for (w, h) in ((390, 844), (360, 640), (195, 422), (667, 375), (844, 390), (820, 1180), (1180, 820)):
        for t in (0.9, 1.0, 1.25, 1.5, 1.75, 2.0):
            ph = Phone(b, w, h, seen=True, ts=t).open(wait=1100)
            r = ph.js(FIT)
            cmd("next"); ph.wait(900); r += ph.js(FIT); cmd("prev"); ph.wait(300)
            if r: fails.append((f"{w}x{h} at {int(t * 100)} %", r))
            ph.close()
    check("7 layouts x 6 text sizes (90-200 %), two steps each: the time inside Next and clear of its bottom line, at least two clear lines of the current note, no text block cut, no sideways scroll", not fails, fails[:4])
    ph = Phone(b, 360, 640, seen=True).open(wait=1100)
    check("a 360x640 phone at 100 %: the word 'Next' stays on the button", ph.vis("#s-hint") and ph.text("#s-hint") == "Next", ph.text("#s-hint"))
    hb, pb = ph.pg.locator("#hint").bounding_box(), ph.pg.locator("#pic").bounding_box()
    ph.pg.reload(); ph.wait(1500)
    check("the pointing hint sits at the picture's foot, and shows once per phone", hb is not None and hb["y"] + hb["height"] >= pb["y"] + pb["height"] - 12 and not ph.vis("#hint"), (hb, pb))
    ph.close()
    ph = Phone(b, 195, 422, seen=True, ts=2).open(wait=1100)
    wb = ph.pg.locator("#wholebtn").bounding_box()
    check("195x422 at 200 %: the top row says '2 /8', no step dots; 'Whole note' is a 44 px icon with its name", ph.text("#cur") == "2" and ph.text("#tot") == "/8" and not ph.vis("#pips") and wb["width"] >= 44 and wb["height"] >= 44 and ph.pg.get_attribute("#wholebtn", "aria-label") == "Whole note" and not ph.vis("#wholebtn span"), (ph.text("#tot"), wb))
    ph.shot("fit_195_200"); ph.close()
    ph = Phone(b, 844, 390, seen=True, ts=1.5).open(wait=1100)
    sb, mb = ph.pg.locator("#surface").bounding_box(), ph.pg.locator("#s-main").bounding_box()
    check("a short Next (844x390 at 150 %): the word 'Next' gives way, the time sits in the middle", not ph.vis("#s-hint") and abs((mb["y"] + mb["height"] / 2) - (sb["y"] + sb["height"] / 2)) < sb["height"] * 0.12, (sb, mb))
    ph.shot("fit_land_150"); ph.close()
    ph = Phone(b, 360, 560, seen=True).open()
    ph.pg.click("#b-menu"); ph.wait(350); ph.pg.click("#m-setup"); ph.wait(600)
    mh = ph.pg.locator("#setup .morehint"); ft = ph.pg.locator("#setup .foot").bounding_box()
    r = mh.bounding_box() if mh.count() and mh.is_visible() else None
    check("a full screen that goes on below its button says 'more below' just above that button, never at the top", r is not None and r["y"] + r["height"] <= ft["y"] and r["y"] > ft["y"] - 60, (r, ft))
    ph.close()
    ph = Phone(b, 1180, 820, seen=True).open()
    ph.pg.click("#b-menu"); ph.wait(350); ph.pg.click("#t-reset"); ph.pg.click("#t-reset"); ph.wait(500); ph.pg.keyboard.press("Escape"); ph.wait(400)
    sn, pd = ph.pg.locator("#snack").bounding_box(), ph.pg.locator("#pads").bounding_box()
    check("presenter view: the strip with Undo lines up with Back/Next, not the middle of the screen", abs(sn["x"] - pd["x"]) < 2 and abs(sn["width"] - pd["width"]) < 2, (sn, pd))
    ph.pg.click("#b-slides"); ph.wait(1300)
    y = lambda n: ph.pg.locator(f"#grid button[data-n='{n}']").bounding_box()["y"]
    check("a hidden slide's title has its own lines on a tablet too", ph.pg.locator("#grid button[data-n='6'] .tl span").bounding_box()["width"] > 100)
    check("Slides on a wide screen: one even grid, the section's name on its first slide, headings kept for screen readers", y(1) == y(3) and ph.text("#grid button[data-n='3'] .sl") == "The idea" and not ph.vis("#grid button[data-n='4'] .sl") and ph.pg.locator("#grid h2").count() == 3, (y(1), y(3)))
    ph.shot("fit_desk_slides"); ph.close()
    for w in (360, 390):
        ph = Phone(b, w, 800, seen=True).open(); ph.pg.click("#b-slides"); ph.wait(1300)
        t = ph.pg.locator("#grid button[data-n='6'] .tl span"); bx = t.bounding_box(); cap = ph.pg.locator("#grid button[data-n='6'] .cap").bounding_box()
        check(f"{w} px phone grid: a hidden slide's title gets the caption's width, with 'Hidden' on the line under it", bx["width"] >= cap["width"] - 30 and ph.text("#grid button[data-n='6'] .badge") == "Hidden" and ph.pg.locator("#grid button[data-n='6'] .badge").bounding_box()["y"] >= bx["y"] + bx["height"] - 1, (bx, cap))
        ph.close()


def part_v26(b):
    """2.6: when the clock starts (or no clock at all), and zoom on the big screen (a trial)."""
    fresh()
    ph = Phone(b).open(wait=300); ph.wait(900)
    ph.pg.click("#t-starts button[data-starts=off]"); ph.wait(500)
    check("'No clock' in Setup: the computer takes it, and talk length and alerts step aside",
          state()["timer"]["starts"] == "off" and not ph.vis("#t-len") and not ph.vis("#t-marks") and "lesson" in ph.text("#t-starts-how")
          and ph.pg.get_attribute("#t-starts button[data-starts=off]", "aria-pressed") == "true", ph.text("#t-starts-how"))
    ph.pg.click("#su-skip"); ph.wait(500)
    check("no clock: the start screen offers no rehearsal", ph.vis("#rest-start") and not ph.vis("#rest-reh"))
    cmd("start"); ph.wait(900); cmd("next"); ph.wait(700)
    check("no clock, in the talk: Next is just Next, with no time and no band", ph.text("#s-main") == "Next" and ph.text("#s-sub") == "" and not ph.vis("#waitbar") and not state()["timer"]["running"],
          (ph.text("#s-main"), ph.text("#s-sub")))
    ph.pg.click("#b-menu"); ph.wait(400)
    check("and the Menu has no clock and no rehearsal", not ph.vis("#readout") and not ph.vis("#t-go") and not ph.vis("#r-start") and ph.vis("#m-setup"))
    ph.shot("v26_noclock_menu")
    ph.pg.click("#m-setup"); ph.wait(400)
    ph.pg.click("#t-starts button[data-starts=show]"); ph.wait(600)
    check("'When the slide show starts' chosen during the show: the clock starts there and then", state()["timer"]["running"] and ph.vis("#t-len"))
    ph.pg.click("#su-go"); ph.wait(300)
    post("/api/timer", {"action": "reset", "starts": "next"}); ph.wait(900)
    check("'With my first Next', the show running, the clock not yet: a band says so and offers to start it",
          ph.vis("#waitbar") and ph.text("#wait-t") == "The clock starts with your first Next" and ph.text("#wait-go") == "Start it now")
    ph.shot("v26_waitbar")
    ph.pg.click("#wait-go"); ph.wait(800)
    check("'Start it now' starts it, and the band goes", state()["timer"]["running"] and not ph.vis("#waitbar"))
    cmd("end"); ph.wait(900)
    check("the start screen says when the clock starts", "The clock starts with your first Next." in ph.text("#rest-p"), ph.text("#rest-p"))
    post("/api/timer", {"action": "reset", "starts": "show"}); ph.wait(700)
    check("and says it for the other rule too", "The clock starts with the slide show." in ph.text("#rest-p"), ph.text("#rest-p"))
    ph.close()

    # zoom on the big screen, a trial: off unless switched on in Setup
    fresh(show=True, slide=2)
    ph = Phone(b, seen=True)
    pans, lasers = [], []
    ph.pg.on("request", lambda r: pans.append(json.loads(r.post_data)) if "/api/pan" in r.url else (lasers.append(json.loads(r.post_data)) if "/api/laser" in r.url else None))
    ph.open(); ph.wait(600)
    check("zoom is off unless switched on: nothing over the picture", not ph.vis("#zoombar"))
    ph.pg.click("#b-menu"); ph.wait(300); ph.pg.click("#m-setup"); ph.wait(300)     # from the Menu, Setup opens with More options unfolded
    ph.pg.locator("#p-zoom").scroll_into_view_if_needed(); ph.pg.click("#p-zoom"); ph.wait(200)
    check("the switch is under More options, says it is a trial and what it does", ph.pg.get_attribute("#p-zoom", "aria-checked") == "true" and "trial" in ph.text("#p-zoom").lower() and "hold and drag" in ph.text("#p-zoom"))
    ph.pg.click("#su-go"); ph.wait(400)
    check("switched on: + and − over the slide picture; − does nothing at normal size", ph.vis("#z-in") and ph.vis("#z-out") and ph.pg.is_disabled("#z-out") and not ph.vis("#z-fit"))
    ph.pg.click("#z-in"); ph.wait(600)
    check("+ zooms the big screen in, and Fit appears with a word on how to move around", state()["zoom"] == 1 and ph.vis("#z-fit") and ph.vis("#zoomtag") and not ph.pg.is_disabled("#z-out"), state()["zoom"])
    check("tapping + is not a laser press", not any(l["on"] for l in lasers), lasers)
    ph.shot("v26_zoomed")
    p = ph.pg.locator("#pic").bounding_box()
    ph.pg.mouse.move(p["x"] + p["width"] * 0.3, p["y"] + p["height"] * 0.6); ph.pg.mouse.down(); ph.wait(450)
    ph.pg.mouse.move(p["x"] + p["width"] * 0.7, p["y"] + p["height"] * 0.4, steps=5); ph.wait(300); ph.pg.mouse.up(); ph.wait(400)
    phases = [x["phase"] for x in pans]
    check("zoomed in, a held finger drags the slide: down, moves, up, and no laser", phases[:1] == ["down"] and phases[-1] == "up" and "move" in phases and not any(l["on"] for l in lasers), phases)
    check("it lets go where the finger lifted", abs(pans[-1]["x"] - 0.7) < 0.03 and abs(pans[-1]["y"] - 0.4) < 0.04, pans[-1])
    ph.pg.click("#z-fit"); ph.wait(600)
    check("Fit: back to the whole slide", state()["zoom"] == 0 and not ph.vis("#z-fit") and not ph.vis("#zoomtag"))
    ph.pg.click("#z-in"); ph.wait(500); cmd("goto", n=4); ph.wait(700)
    check("another slide comes up at its normal size", state()["zoom"] == 0 and state()["slide"] == 4 and not ph.vis("#z-fit"), (state()["zoom"], state()["slide"]))
    lasers.clear(); ph.pg.mouse.move(p["x"] + p["width"] * 0.5, p["y"] + p["height"] * 0.5); ph.pg.mouse.down(); ph.wait(450); ph.pg.mouse.up(); ph.wait(300)
    check("not zoomed in, holding the picture is the laser again", any(l["on"] for l in lasers), lasers[-2:])
    ph.js("localStorage.removeItem('cuewand.prefs')")
    ph.close()


PARTS = {"flow": part_flow, "press": part_press, "trouble": part_trouble, "clock": part_clock, "picture": part_picture, "small": part_small, "access": part_access, "v23": part_v23, "v23b": part_v23b, "fit": part_fit, "v26": part_v26}
want = sys.argv[1:] or list(PARTS)
server()
with sync_playwright() as p:
    b = p.chromium.launch()
    for name in want:
        print(f"--- {name}", flush=True)
        try:
            PARTS[name](b)
        except Exception as e:
            check(f"{name}: ran to the end", False, f"{type(e).__name__}: {e}"[:400])
    b.close()
check("no errors on the page console", not errs, errs[:6])
print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
