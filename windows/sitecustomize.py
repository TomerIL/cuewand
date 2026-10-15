"""Starts Cuewand when one of its .exe files is double-clicked.

In Cuewand-for-Windows.zip, "Start Cuewand.exe", "Test Cuewand.exe" and
"Get the internet link ready.exe" are copies of Python's own python.exe, as
signed by the Python Software Foundation. Windows Smart App Control blocks
.bat files that came from the internet, and unsigned programs, but lets a
signed program run; the signature does not cover the file name, so the copies
keep it.

Python imports this file every time it starts (it sits in the app folder, which
python313._pth puts on the path). It acts only when the program was started
with nothing after its name, which is what a double-click does: it then runs
app\\cuewand.py with the options that belong to that name, in a second copy of
the same program, waits for it, and keeps the window open when there is
something to read. Started with anything on its command line, it does nothing
and Python carries on as usual.
"""
import os
import sys

# the .exe name, without .exe, in lower case -> what to run
LAUNCHERS = {
    "start cuewand": [],
    "test cuewand": ["--selftest"],
    "get the internet link ready": ["--prepare"],
}
# these always end with something to read; Start Cuewand only when it failed
ALWAYS_PAUSE = {"test cuewand", "get the internet link ready"}


def _writable(folder):
    probe = os.path.join(folder, ".cuewand_write_test")
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def _pause():
    try:
        input("\n  Press Enter to close this window.")
    except (EOFError, KeyboardInterrupt):
        pass


def _launch(name):
    import subprocess
    app = os.path.dirname(os.path.abspath(__file__))
    top = os.path.dirname(os.path.abspath(sys.executable))
    script = os.path.join(app, "cuewand.py")
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("Cuewand")
    except Exception:
        pass
    if not os.path.isfile(script):
        print("\n  Cuewand's files are not next to this program. Extract the whole")
        print("  Cuewand folder from the zip (right-click the zip, Extract All), then")
        print("  double-click this program in the extracted folder.")
        _pause()
        return 1
    env = dict(os.environ)
    if _writable(top):      # the log and the session sit beside the .exe files
        env["CUEWAND_DATA"] = top
    child = subprocess.Popen([sys.executable, script] + LAUNCHERS[name], cwd=app, env=env)
    while True:
        try:
            rc = child.wait()
            break
        except KeyboardInterrupt:   # Ctrl+C reaches Cuewand too; wait for it to finish
            continue
    if rc or name in ALWAYS_PAUSE:
        _pause()
    return rc


def _main():
    if len(getattr(sys, "orig_argv", ())) != 1:     # something on the command line
        return
    name = os.path.splitext(os.path.basename(sys.executable))[0].lower()
    if name not in LAUNCHERS:
        return
    rc = _launch(name)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc or 0)       # not sys.exit: this runs while Python is still starting up


_main()
