"""The mockup (docs/index.html, also the live demo on tomeryona.com): it must carry
the current phone page, and its simulator must answer what that page asks."""
import base64, os, re, sys
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "index.html")   # or another copy: the website's demo
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    ok += bool(cond); bad += not cond; print(("PASS " if cond else "FAIL ") + name, extra if not cond else "", flush=True)

src = open(MOCK, encoding="utf-8").read()
inner = base64.b64decode(re.search(r"atob\('([A-Za-z0-9+/=]+)'\)", src).group(1)).decode("utf-8")
sys.path.insert(0, os.path.join(ROOT, "docs")); import make_mockup
check("the mockup carries the phone page exactly as remote.html builds it (run docs/make_mockup.py after changing remote.html)", inner == make_mockup.phone_page())
ver = re.search(r'^VERSION = "([\d.]+)"', open(os.path.join(ROOT, "cuewand.py"), encoding="utf-8").read(), re.M).group(1)
check(f"the mockup is labelled with this version ({ver})", f"Cuewand {ver} mockup" in src and f"version: '{ver}'" in src)

errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto("file://" + MOCK); pg.wait_for_timeout(2500)
    ph = pg.frame_locator("#dev-p1 iframe")
    main = lambda: ph.locator("#s-main").inner_text()
    check("the phone opens in the talk, on slide 2", ph.locator("#cur").inner_text() == "2")
    check("the clock runs from the start, as with 'When the slide show starts'", re.fullmatch(r"1[45]:\d\d", main()) is not None, main())
    pg.click("#d-starts button[data-s=off]"); pg.wait_for_timeout(1200)
    check("'No clock': Next is just Next", main() == "Next" and ph.locator("#s-sub").inner_text() == "", main())
    pg.click("#d-starts button[data-s=next]"); pg.wait_for_timeout(1200)
    check("'With my first Next': the band says the clock waits, with Start it now", ph.locator("#waitbar").is_visible() and "first Next" in ph.locator("#wait-t").inner_text())
    ph.locator("#wait-go").evaluate("e => e.click()"); pg.wait_for_timeout(800)
    check("and Start it now starts it", not ph.locator("#waitbar").is_visible() and re.fullmatch(r"1[45]:\d\d", main()) is not None, main())
    pg.click("#d-starts button[data-s=show]"); pg.wait_for_timeout(1200)
    check("'When the slide show starts': running again from slide 1", re.fullmatch(r"1[45]:\d\d", main()) is not None and ph.locator("#cur").inner_text() == "1", main())
    pg.click("#d-zoom"); pg.wait_for_timeout(1500)
    ph = pg.frame_locator("#dev-p1 iframe")
    check("zoom switched on: + and − over the slide picture", ph.locator("#z-in").is_visible() and ph.locator("#z-out").is_visible())
    ph.locator("#z-in").evaluate("e => e.click()"); pg.wait_for_timeout(700)
    tr = pg.evaluate("getComputedStyle(document.getElementById('simg')).transform")
    check("+ zooms the room's screen, and the phone offers Fit", tr not in ("none", "") and ph.locator("#z-fit").is_visible() and "zoomed in" in pg.inner_text("#scap"), tr)
    ph.locator("#z-fit").evaluate("e => e.click()"); pg.wait_for_timeout(700)
    check("Fit: the whole slide again", pg.evaluate("getComputedStyle(document.getElementById('simg')).transform") == "none" and not ph.locator("#z-fit").is_visible())
    pg.click("#tab4"); pg.wait_for_timeout(200)
    check("Less motion: two choices of the phone's own setting, none in Cuewand", pg.locator("#d-motion button").count() == 2 and "nothing to choose" in pg.inner_text("#part4"))
    pg.click("#d-motion button[data-m=less]"); pg.wait_for_timeout(1500)
    ph = pg.frame_locator("#dev-p1 iframe")
    still = lambda: ph.locator("html").get_attribute("class") or ""
    check("phone set to reduce motion: steady marks", "still" in still(), still())
    pg.click("#d-motion button[data-m=full]"); pg.wait_for_timeout(1500)
    ph = pg.frame_locator("#dev-p1 iframe")
    check("and back to full motion", "still" not in still(), still())
    ph.locator("#b-menu").evaluate("e => e.click()"); pg.wait_for_timeout(400); ph.locator("#m-setup").evaluate("e => e.click()"); pg.wait_for_timeout(500)
    check("the phone's Setup has the clock question and no Motion choice", ph.locator("#t-starts").is_visible() and ph.locator("[data-motion]").count() == 0)
    b.close()
check("no errors in the mockup or its phones", not errs, errs[:5])
print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
