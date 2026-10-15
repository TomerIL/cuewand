"""Run every test file and add up. The phone, pairing-page and mockup tests need Playwright
(pip install playwright, then: playwright install chromium); the others need nothing."""
import os, re, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
files = ["test_powerpoint_standin.py", "test_api.py", "test_helper.py", "test_pairing_page.py", "test_phone.py", "test_mockup.py"]
try:
    import playwright  # noqa: F401
except ImportError:
    files = files[:3]
    print("Playwright is not installed: skipping the three browser test files.\n")
total_ok = total_bad = 0
for f in files:
    p = subprocess.run([sys.executable, os.path.join(here, f)], capture_output=True, text=True)
    m = re.search(r"(\d+) passed, (\d+) failed", p.stdout)
    ok, bad = (int(m.group(1)), int(m.group(2))) if m else (0, 1)
    total_ok += ok; total_bad += bad
    print(f"{f:32} {ok:4} passed {bad:3} failed")
    for line in p.stdout.splitlines():
        if line.startswith("FAIL"):
            print("    " + line)
    if not m:
        print("    did not finish:", (p.stderr or p.stdout)[-400:])
print(f"\n{'all files':32} {total_ok:4} passed {total_bad:3} failed")
sys.exit(1 if total_bad else 0)
