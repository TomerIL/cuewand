"""Rebuild the phone page inside the mockup (docs/index.html) from the real one.

The mockup runs the real remote.html in an iframe, with a few lines changed so
that it talks to the PowerPoint simulator in the page around it instead of a
computer (docs/mockup-shim.html, and the replacements below). Run this after
every change to remote.html, so the mockup never shows an old phone:

    python docs/make_mockup.py                 # rewrites docs/index.html
    python docs/make_mockup.py path/demo.html  # also another copy (the website's demo)

It stops with an error if any spot it changes is no longer in remote.html.
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def phone_page() -> str:
    s = open(os.path.join(ROOT, "remote.html"), encoding="utf-8").read()
    shim = open(os.path.join(HERE, "mockup-shim.html"), encoding="utf-8").read()

    def swap(old, new, count=1):
        nonlocal s
        n = s.count(old)
        if n != count:
            sys.exit(f"make_mockup: expected {count} of {old[:60]!r} in remote.html, found {n}")
        s = s.replace(old, new)

    swap("<title>Cuewand</title>", "<title>Cuewand (mockup)</title>")
    # the shim runs before the page's own script
    swap("</div>\n<script>\n(() => {\n'use strict';", "</div>\n" + shim.rstrip("\n") + "\n<script>\n(() => {\n'use strict';")
    swap("localStorage.getItem(k)", "__ls.getItem(k)")
    swap("localStorage.setItem(k, v)", "__ls.setItem(k, v)")
    swap("localStorage.removeItem(k)", "__ls.removeItem(k)")
    swap("const fromLink = new URLSearchParams(location.hash.slice(1)).get('k') || '';\n"
         "const KEY = fromLink || store.get('cuewand.key') || '';\n"
         "if (fromLink) store.set('cuewand.key', fromLink);", "const KEY = 'mockup';")
    swap("try { history.pushState(null, '', location.href); addEventListener('popstate', () => history.pushState(null, '', location.href)); } catch (e) {}", "")
    swap("const slideUrl = n => `/api/slide/${n}.jpg?d=${S.deckId}&k=${encodeURIComponent(KEY)}`;",
         "const slideUrl = n => window.__mockSlide(n);")
    n = s.count("sessionStorage.")
    if n < 4:
        sys.exit(f"make_mockup: expected the page's sessionStorage uses, found {n}")
    s = s.replace("sessionStorage.", "__ss.")
    s, k = re.subn(r"const AWAKE = \[.*?\];\n", "const AWAKE = [];\n", s, count=1, flags=re.S)
    if k != 1:
        sys.exit("make_mockup: the keep-awake video list was not found")
    swap("async function keepAwake(gesture) {\n",
         "async function keepAwake(gesture) {\n  if (window.__mockPhone) { awakeBy = 'lock'; return awakeBy; }\n")
    return s


def write_into(path: str, page: str):
    s = open(path, encoding="utf-8").read()
    b64 = base64.b64encode(page.encode("utf-8")).decode("ascii")
    s, k = re.subn(r"(const INNER = new TextDecoder\(\)\.decode\(Uint8Array\.from\(atob\(')[A-Za-z0-9+/=]+('\))",
                   lambda m: m.group(1) + b64 + m.group(2), s, count=1)
    if k != 1:
        sys.exit(f"make_mockup: no embedded phone page in {path}")
    open(path, "w", encoding="utf-8", newline="").write(s)
    print(f"{path}: phone page rebuilt from remote.html ({len(page) // 1024} KB)")


if __name__ == "__main__":
    page = phone_page()
    for target in [os.path.join(HERE, "index.html")] + sys.argv[1:]:
        write_into(target, page)
