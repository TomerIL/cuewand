"""Shared by the test files: where Cuewand is, and a demo server to run it against.
Nothing here needs Windows or PowerPoint."""
import atexit, json, os, shutil, signal, subprocess, sys, tempfile, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("CUEWAND_TEST_PORT", "8765"))
B = f"http://127.0.0.1:{PORT}"
DATA = os.environ.get("CUEWAND_TEST_DATA") or tempfile.mkdtemp(prefix="cuewand_test_")
SHOTS = os.path.join(DATA, "shots")
os.makedirs(SHOTS, exist_ok=True)
_proc = None


def kill(hard=True):
    """Stop the demo server; hard = as if its window was closed without warning."""
    global _proc
    if _proc and _proc.poll() is None:
        _proc.send_signal(signal.SIGKILL if hard and hasattr(signal, "SIGKILL") else signal.SIGTERM)
        try:
            _proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
    _proc = None
    time.sleep(0.3)


def server(*args, keep=False):
    """(Re)start Cuewand with its demo deck. keep=True leaves the saved session in place.
    Returns the saved session: key, host_key, pin."""
    global _proc
    kill()
    if not keep:
        for name in os.listdir(DATA):
            path = os.path.join(DATA, name)
            if os.path.isfile(path):
                os.remove(path)
    out = open(os.path.join(DATA, "server.out"), "w")
    _proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "cuewand.py"), "--demo", "--no-browser",
                              "--port", str(PORT), *args],
                             # unbuffered, so the file shows each line at once, as a console window does
                             env=dict(os.environ, CUEWAND_DATA=DATA, PYTHONUNBUFFERED="1"), stdout=out, stderr=subprocess.STDOUT)
    for _ in range(80):
        try:
            with urllib.request.urlopen(B + "/api/ping", timeout=0.5) as r:
                if b"cuewand" in r.read():
                    break
        except Exception:
            time.sleep(0.1)
    else:
        raise SystemExit("the demo server did not start; see " + os.path.join(DATA, "server.out"))
    time.sleep(0.3)
    if _proc.poll() is not None:
        raise SystemExit(f"could not start the demo server: is another Cuewand already running on port {PORT}?")
    return json.load(open(os.path.join(DATA, "cuewand_session.json")))


atexit.register(lambda: kill(hard=False))


class Tally:
    def __init__(self):
        self.ok = self.bad = 0

    def __call__(self, name, cond, extra=""):
        self.ok += bool(cond)
        self.bad += not cond
        print(("PASS " if cond else "FAIL ") + name, extra if not cond else "", flush=True)

    def done(self):
        print(f"\n{self.ok} passed, {self.bad} failed")
        sys.exit(1 if self.bad else 0)
