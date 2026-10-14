"""The pairing page on the computer."""
import json, os, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright
import common
from common import B, DATA, PORT
OUT = common.SHOTS
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    ok += bool(cond); bad += not cond; print(("PASS " if cond else "FAIL ") + name, extra if not cond else "", flush=True)
d = common.server(); K, H, PIN = d["key"], d["host_key"], d["pin"]
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for (w, h) in ((1366, 768), (1920, 1080), (700, 900)):
        pg = b.new_page(viewport={"width": w, "height": h})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{B}/host?h={H}"); pg.wait_for_timeout(900)
        q = pg.locator("#lan-qr").bounding_box()
        check(f"{w}x{h}: the code is large and fully on screen", q["width"] >= min(0.5 * h, 500) - 12 and q["y"] + q["height"] <= h and q["x"] >= 0 and q["x"] + q["width"] <= w, q)
        sv = pg.locator("#lan-qr svg").bounding_box()
        check(f"{w}x{h}: the drawing fills its white tile", pg.get_attribute("#lan-qr svg", "viewBox") and sv["width"] >= q["width"] - 24 and abs(sv["width"] - sv["height"]) < 2, sv)
        pg.screenshot(path=f"{OUT}/host_{w}x{h}.png"); pg.close()
    pg = b.new_page(viewport={"width": 1366, "height": 768}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{B}/host?h={H}"); pg.wait_for_timeout(900)
    t = lambda sel: pg.inner_text(sel).replace("\n", " ").strip()
    check("headline asks for the scan; the number and the short address are there for phones without a camera", t("#head") == "Point your phone’s camera at the code" and t("#pin") == PIN[:3] + " " + PIN[3:] and t("#lan-short").endswith(f":{PORT}"), (t("#head"), t("#pin")))
    logo = pg.evaluate("""() => { const s = document.querySelector('.mark svg.logo'), r = s.getBoundingClientRect(), u = s.querySelector('use');
      return [s.getAttribute('role'), s.getAttribute('aria-label'), u && u.getAttribute('href'), !!document.getElementById('cw-logo'), Math.round(r.width), Math.round(r.height)]; }""")
    check("the page is black like the phone, with the same logo: one picture named Cuewand, 30 px tall", pg.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(0, 0, 0)" and logo == ["img", "Cuewand", "#cw-logo", True, 171, 30], logo)
    chev = lambda pg2: pg2.evaluate("getComputedStyle(document.querySelector('#cw-logo .cw-chev')).display")
    hi = b.new_page(viewport={"width": 1366, "height": 768}, device_scale_factor=2); hi.goto(f"{B}/host?h={H}"); hi.wait_for_timeout(500)
    check("the chevron in the logo's cue shows only where it is big enough: hidden at 1x, shown at 2x", chev(pg) == "none" and chev(hi) == "inline", (chev(pg), chev(hi))); hi.close()
    icons = pg.evaluate("[...document.querySelectorAll('link[rel~=icon], link[rel=apple-touch-icon]')].map(l => l.getAttribute('href'))")
    check("the tab and home-screen icons are linked", icons == ["/favicon.ico", "/favicon.svg", "/icon-192.png", "/apple-touch-icon.png"], icons)
    check("the primary button is not amber (amber is for attention only)", pg.evaluate("getComputedStyle(document.getElementById('net-go')).backgroundColor") == "rgb(237, 239, 243)")
    check("help is folded away at first", not pg.is_visible("#help"))
    links = pg.evaluate("[...document.querySelectorAll('.credit a')].map(a => [a.textContent, a.href, a.target, a.rel])")
    check("the footer says who made Cuewand, with links to the website and GitHub that open in a new tab",
          t(".credit").startswith("Made by Tomer Yona") and links == [["tomeryona.com", "https://www.tomeryona.com/", "_blank", "noopener noreferrer"], ["GitHub", "https://github.com/TomerIL", "_blank", "noopener noreferrer"]], links)
    pg.wait_for_timeout(21000)
    check("twenty seconds with no phone: the ways round a blocked network open by themselves", pg.is_visible("#help") and "hotspot" in t("#help").lower() and pg.get_attribute("#help-open", "aria-expanded") == "true")
    pg.screenshot(path=f"{OUT}/host_help.png")
    urllib.request.urlopen(urllib.request.Request(B + "/api/state?since=0&c=testphone", headers={"X-Cuewand-Key": K})).read(); pg.wait_for_timeout(1800)
    check("a phone connects: the headline says so in green, and the help folds away", t("#head") == "Your phone is connected" and "ok" in pg.get_attribute("#head", "class") and not pg.is_visible("#help") and "ok" in pg.get_attribute("#st-phone", "class"), t("#head"))
    pg.screenshot(path=f"{OUT}/host_connected.png")
    pg.click("#tab-net"); pg.wait_for_timeout(200)
    check("the internet tab explains itself before anything is downloaded", pg.is_visible("#net-go") and "55 MB" in t("#net-have") and not pg.is_visible("#lan-qr"), t("#net-have"))
    pg.screenshot(path=f"{OUT}/host_net.png")
    pg.click("#tab-lan"); pg.click("#rotate"); pg.wait_for_timeout(200)
    check("new codes ask twice", "arm" in pg.get_attribute("#rotate", "class") and json.load(open(DATA + "/cuewand_session.json"))["key"] == K)
    pg.click("#rotate"); pg.wait_for_timeout(1900)
    d2 = json.load(open(DATA + "/cuewand_session.json"))
    check("then the code and the number on the page change", d2["key"] != K and t("#pin") == d2["pin"][:3] + " " + d2["pin"][3:] and t("#pin") != PIN[:3] + " " + PIN[3:], t("#pin"))
    r = pg.request.get(f"{B}/host?h=wrong")
    check("the pairing page with a wrong address is a styled, plain-words page", r.status == 403 and "This page has moved on" in r.text() and "<pre" not in r.text())
    b.close()
check("no page errors", not errs, errs)
print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
