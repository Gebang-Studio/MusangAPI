"""Run: venv/bin/python tests/test_android_park.py — tab muse simpanan di Chrome Android (engine.close_current_page park).

Memuat muse di HP ~14 dtk, jadi tab yang selesai normal disimpan dan dipakai lagi oleh permintaan berikutnya
(akun sama). Chat di tab simpanan harus memulai thread baru (lewat router), kalau gagal memuat ulang halaman.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = tempfile.TemporaryDirectory(prefix="muse-park-test-")
os.environ.update(MUSE2API_HOME=HOME.name, MUSE2API_PROFILE_ROOT=HOME.name)
from config import Config  # noqa: E402
from engine import MuseEngine  # noqa: E402


class Browser:
    def __init__(self):
        self.sent = []

    def send(self, method, params=None, *a, **k):
        self.sent.append((method, params))
        return {"result": {}}


class Page:
    """Halaman muse palsu: jawaban js() menurut potongan ekspresi."""

    def __init__(self, bubbles=0, router=True):
        self.closed, self.bubbles, self.router, self.pushed, self.navigated = False, bubbles, router, 0, 0

    def close(self):
        self.closed = True

    def send(self, method, params=None, *a, **k):
        if method == "Page.navigate":
            self.navigated += 1
            self.bubbles = 0
        return {"result": {}}

    def js(self, expr, *a, **k):
        if "router.push" in expr:
            if not self.router:
                return False
            self.pushed += 1
            self.bubbles = 0
            return True
        if "forChat" in expr:  # keputusan reset_thread
            return "new" if self.bubbles else False
        if "location.pathname === '/thread/new'" in expr:
            return self.bubbles == 0
        if "readyState" in expr and "hydrat" in expr:  # _wait_ws_ready
            return "ready"
        if "querySelector('textarea')" in expr:
            return True
        return True


def engine(android=True):
    e = MuseEngine(Config())
    e.android, e.browser = android, Browser()
    return e


def hold(e, page, acc="a1", ctx="ctx1"):
    e.page, e.current_acc_id, e.current_context_id = page, acc, ctx
    e._active_contexts.add(ctx)


# 1. Android: tab disimpan, lalu dipakai lagi oleh akun yang sama tanpa membuka tab baru.
e, p = engine(), Page()
hold(e, p)
e.close_current_page(park=True)
assert not p.closed and e.page is None and e._parked["page"] is p
assert e.ensure_page({}, account_id="a1") is p and e.current_acc_id == "a1" and e._parked is None
assert not any(m == "Target.createTarget" for m, _ in e.browser.sent), e.browser.sent
print("ok: tab simpanan dipakai lagi oleh akun yang sama")

# 2. Akun lain: tab simpanan ditutup beserta konteksnya.
e, p = engine(), Page()
hold(e, p)
e.close_current_page(park=True)
e._adopt_parked("a2")
assert p.closed and e.page is None and ("Target.disposeBrowserContext", {"browserContextId": "ctx1"}) in e.browser.sent
assert "ctx1" not in e._active_contexts
print("ok: tab milik akun lain ditutup")

# 3. Bukan Android / tanpa park / tab berproxy: tetap ditutup seperti dulu.
for android, park, proxy in ((False, True, None), (True, False, None), (True, True, {"server": "x"})):
    e, p = engine(android), Page()
    hold(e, p)
    e._ensure_local().proxy_config = proxy
    e.close_current_page(park=park)
    assert p.closed and e._parked is None, (android, park, proxy)
print("ok: Mac, kegagalan/dihentikan, dan tab berproxy tetap ditutup")

# 4. Menyimpan tab kedua menutup tab simpanan sebelumnya (hanya satu tab muse tersimpan di HP).
e, p1, p2 = engine(), Page(), Page()
hold(e, p1, ctx="c1")
e.close_current_page(park=True)
hold(e, p2, ctx="c2")
e.close_current_page(park=True)
assert p1.closed and not p2.closed and e._parked["page"] is p2
print("ok: satu tab simpanan")

# 5. Chat di tab yang sudah berisi thread lama: thread baru lewat router, tanpa memuat ulang halaman.
e, p = engine(), Page(bubbles=4)
e.page = p
e.reset_thread(for_chat=True)
assert p.pushed == 1 and p.navigated == 0 and p.bubbles == 0, vars(p)
# Router gagal: cadangan muat ulang /thread/new.
e, p = engine(), Page(bubbles=4, router=False)
e.page = p
e.reset_thread(for_chat=True)
assert p.navigated == 1, vars(p)
# Tab baru (tanpa gelembung): tidak ada navigasi sama sekali.
e, p = engine(), Page(bubbles=0)
e.page = p
e.reset_thread(for_chat=True)
assert p.pushed == 0 and p.navigated == 0
print("ok: thread baru lewat router, cadangan reload")

# 6. stop(): tab simpanan ikut ditutup.
e, p = engine(), Page()
hold(e, p)
e.close_current_page(park=True)
e.stop()
assert p.closed and e._parked is None
print("test_android_park OK")
