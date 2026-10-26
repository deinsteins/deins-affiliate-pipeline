"""Persistent server browser for Google Flow, remote-controlled from
the dashboard.

Why this exists: the dashboard runs on the server but the owner opens
it on their phone — typing Google credentials into a dashboard form
would NOT log the server browser in (different browser), and this
project never captures Google credentials. So instead the dashboard
serves a remote-control page: a live screenshot of the server's own
Chromium plus click/key forwarding. The owner logs into Google's real
page with their own hands (2FA etc. all work); the session then lives
in a persistent profile (storage/flow-profile) that the Flow
automation reuses.

Security notes:
- All endpoints using this module sit behind the dashboard's basic
  auth, same as every other dashboard route.
- Typed text is forwarded to the browser and NEVER logged or stored
  anywhere in this module.
- goto() is restricted to Google hosts (Flow + accounts) so the panel
  cannot be used as a general-purpose browser.

Threading: Playwright's sync API is owned by one dedicated daemon
thread; every operation is submitted to it and blocks for its result.
"""

import os
import queue
import threading
from concurrent.futures import Future
from pathlib import Path
from urllib.parse import urlparse

FLOW_URL = "https://labs.google/fx/tools/flow"
PROFILE_DIR = Path(__file__).resolve().parent.parent / "storage" / "flow-profile"
PROXY = "http://127.0.0.1:18080"  # social-agent-proxy relay (Chromium
# can't answer the egress proxy's credential demand directly)
VIEWPORT = {"width": 1280, "height": 800}
ALLOWED_HOSTS = {"labs.google", "flow.google.com", "flow.google",
                 "accounts.google.com", "accounts.google.co.id",
                 "myaccount.google.com", "google.com", "www.google.com"}


def _ensure_xvfb():
    """Run a virtual display for HEADED Chromium (Xvfb :99).

    Headless browsers fail Google's sign-in integrity check at auth
    time ("This browser or app may not be secure") even when the
    sign-in form itself loads. A headed browser on a virtual display
    looks like a normal desktop Chrome. Reused across restarts; the
    dashboard service runs as root, so the socket dir is writable."""
    import glob as _glob
    import subprocess
    # A lock file alone proves nothing: Xvfb killed ungracefully
    # leaves a stale lock (and socket) behind, and reusing a dead
    # display makes every browser launch fail with "cannot open
    # display" — the login screen never appears. Trust only a live
    # Xvfb process; otherwise clear the stale files and start fresh.
    running = False
    for _pid in _glob.glob("/proc/[0-9]*"):
        try:
            _cmd = open(_pid + "/cmdline", "rb").read().decode(
                errors="ignore")
            if "Xvfb" in _cmd and ":99" in _cmd:
                running = True
                break
        except Exception:  # noqa: BLE001 - proc entry vanished
            pass
    if running:
        os.environ["DISPLAY"] = ":99"
        return
    for _stale in ("/tmp/.X99-lock", "/tmp/.X11-unix/X99"):
        try:
            os.remove(_stale)
        except OSError:  # noqa: BLE001 - already gone
            pass
    subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import time
    for _ in range(20):
        if os.path.exists("/tmp/.X99-lock"):
            break
        time.sleep(0.5)
    os.environ["DISPLAY"] = ":99"


class _BrowserThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.q: queue.Queue = queue.Queue()
        self.page = None
        self.ctx = None

    def run(self):
        from playwright.sync_api import sync_playwright
        import os
        _ensure_xvfb()
        exe = _browser_exe()
        with sync_playwright() as pw:
            kwargs = dict(headless=False, proxy={"server": PROXY},
                          ignore_https_errors=True, viewport=VIEWPORT,
                          # Hide the automation flag: Google sign-in
                          # rejects browsers that advertise automation
                          # (its generic symptom is the "Cookies are
                          # disabled" page). The owner still logs in
                          # with their own hands; this only makes the
                          # browser look like a normal Chrome.
                          args=["--disable-blink-features="
                                "AutomationControlled"])
            if exe:
                kwargs["executable_path"] = exe
            self.ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), **kwargs)
            # Same reason as above: navigator.webdriver is the
            # clearest automation tell. Applied before any page
            # navigation, so every sign-in page load sees a normal
            # browser.
            self.ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', "
                "{get: () => undefined});")
            # playwright-stealth: patches the remaining fingerprint
            # tells (plugins, chrome runtime, permissions, languages).
            # Applied to the main page and any page opened later.
            try:
                from playwright_stealth import Stealth
                _stealth = Stealth()
                for _pg in self.ctx.pages:
                    _stealth.apply_stealth_sync(_pg)
                self.ctx.on("page",
                            lambda _pg: _stealth.apply_stealth_sync(_pg))
            except Exception:  # noqa: BLE001 - stealth is best-effort
                pass
            self.page = self.ctx.pages[0] if self.ctx.pages \
                else self.ctx.new_page()
            while True:
                fn, fut = self.q.get()
                if fn is None:
                    break
                try:
                    fut.set_result(fn(self.page))
                except Exception as e:  # noqa: BLE001 - to caller
                    fut.set_exception(e)

    def submit(self, fn):
        fut: Future = Future()
        self.q.put((fn, fut))
        return fut.result(timeout=120)


def stop():
    """Close the browser cleanly so the dashboard service can stop.

    Must be called on shutdown: without it, systemd's SIGTERM leaves
    the process stuck stopping (Playwright driver never exits)."""
    global _THREAD
    with _LOCK:
        t, _THREAD = _THREAD, None
    if t and t.is_alive():
        try:
            t.submit(lambda page: t.ctx.close())
        except Exception:  # noqa: BLE001 - already going away
            pass
        t.q.put((None, Future()))
        t.join(timeout=15)


_THREAD: _BrowserThread | None = None
_LOCK = threading.Lock()


def _thread() -> _BrowserThread:
    global _THREAD
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = _BrowserThread()
            _THREAD.start()
        return _THREAD


def _on_google_host(page) -> bool:
    host = urlparse(page.url).netloc
    return host in ALLOWED_HOSTS or host.endswith(".google.com")


def _go_flow(page):
    # Navigate ONLY from a blank/non-Google page. Never yank the user
    # off accounts.google.com mid-login — that would break their login.
    if page.url in ("about:blank", "") or not _on_google_host(page):
        page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)


def status() -> dict:
    def _fn(page):
        _go_flow(page)
        url = page.url
        # /about is Flow's PUBLIC marketing page — it proves nothing
        # about login. Real proof is the workspace UI (New project).
        # accounts.google.com in the URL means definitely logged out.
        if "accounts.google.com" in url or "/about" in url:
            logged_in, note = False, (
                "halaman login Google" if "accounts.google" in url
                else "halaman about Flow (bukan workspace)")
        else:
            body = page.locator("body").inner_text(timeout=10000)
            logged_in = "New project" in body or "Create new" in body
            note = "workspace terlihat" if logged_in else (
                "workspace belum terkonfirmasi")
        return {"running": True, "url": url, "title": page.title(),
                "logged_in": logged_in, "note": note}
    return _thread().submit(_fn)


def _browser_exe():
    """Find a usable Chromium binary in any likely home dir.

    Prefer Playwright's FULL chromium: the minimal headless_shell
    build gets Google sign-in's generic "Cookies are disabled"
    rejection (it fails Google's browser checks), while the full
    build passes as a normal browser. Fall back to headless_shell
    if the full build was never downloaded. The dashboard service
    may run under a different HOME than the interactive shell, so
    check both."""
    import glob
    # The Muse browser's own full Chromium: verified 2026-10-26 to
    # reach Google's real sign-in page (headless_shell gets rejected).
    import os as _os
    if _os.path.exists("/opt/meta-chromium/chrome"):
        return "/opt/meta-chromium/chrome"
    for home in (os.path.expanduser("~"), "/home/hatch"):
        hits = sorted(glob.glob(
            home + "/.cache/ms-playwright/chromium-*/chrome-linux/chrome"))
        if hits:
            return hits[-1]
        hits = sorted(glob.glob(
            home + "/.cache/ms-playwright/chromium_headless_shell-*/"
            "chrome-linux/headless_shell"))
        if hits:
            return hits[-1]
    return None


def screenshot() -> bytes:
    def _fn(page):
        _go_flow(page)
        return page.screenshot()
    return _thread().submit(_fn)


def click(x: int, y: int) -> dict:
    def _fn(page):
        page.mouse.click(max(0, x), max(0, y))
        page.wait_for_timeout(800)
        return {"ok": True, "url": page.url}
    return _thread().submit(_fn)


def type_text(text: str) -> dict:
    # NOTE: text is forwarded to the browser only — never logged.
    def _fn(page):
        page.keyboard.type(text)
        page.wait_for_timeout(500)
        return {"ok": True}
    return _thread().submit(_fn)


def press(key: str) -> dict:
    allowed = {"Enter", "Tab", "Escape", "Backspace", "ArrowDown",
               "ArrowUp", "ArrowLeft", "ArrowRight"}
    if key not in allowed:
        raise ValueError(f"key tidak diizinkan: {key}")
    def _fn(page):
        page.keyboard.press(key)
        page.wait_for_timeout(500)
        return {"ok": True}
    return _thread().submit(_fn)


def goto(url: str) -> dict:
    host = urlparse(url).netloc
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host tidak diizinkan: {host}")
    def _fn(page):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        return {"ok": True, "url": page.url}
    return _thread().submit(_fn)
