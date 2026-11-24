"""Run: venv/bin/python tests/test_chat_flows_browser.py [--gif DIR]

Alur chat end-to-end di Chrome headless terhadap backend PALSU yang deterministik (tanpa kuota muse.ai):
chat multi-giliran, markdown, XSS, pesan panjang, Stop, Ulangi, Edit, kirim beruntun, stream putus,
gambar, video, /video, "lanjutkan", error 500/wilayah/401, refresh saat video diproses, riwayat, HP, keyboard.
/v1/intent memakai intent.classify asli.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cdp import CDP  # noqa: E402
from intent import classify  # noqa: E402

KEY = "test-key"
CHAT = Path(os.environ.get("CHAT_HTML") or ROOT / "chat.html")  # CHAT_HTML: uji versi lain (mis. sebelum perbaikan)
GIF = sys.argv[sys.argv.index("--gif") + 1] if "--gif" in sys.argv else None
TMP = tempfile.mkdtemp(prefix="m2a-flows-")
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
MP4 = os.path.join(TMP, "fake.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=8:duration=1",
                "-pix_fmt", "yuv420p", MP4], check=True)

LOG = {"chat": 0, "media": []}
TASKS = {}
ERR500 = "模型未生成媒体，仅返回文本: 生成失败了，没能做出这段视频。系统返回了一个内部错误（500），不是提示词或规格的问题。"
REGION = "没有可生成视频的账号：所有账号均被 Meta 拒绝视频 (video_not_available)"
OUTAGE = "MUSE_OUTAGE video 2 12:07 12:17：muse 媒体服务连续 2 次返回 5xx（最近 12:07），为免空等约 7 分钟，本次未发送；12:17 后自动恢复尝试"


class Fake(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def authed(self):
        if self.headers.get("Authorization") != "Bearer " + KEY:
            self.send_json({"detail": "bad key"}, 401)
            return False
        return True

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/chat"):
            return self.file(CHAT, "text/html")
        if p == "/theme.css":
            return self.file(ROOT / "theme.css", "text/css")
        if p.startswith("/v1/media/"):
            return self.file(Path(MP4), "video/mp4") if p.endswith(".mp4") else self.raw(PNG, "image/png")
        if not self.authed():
            return
        if p == "/v1/models":
            return self.send_json({"data": [{"id": "muse-spark"}]})
        tid = p.rsplit("/", 1)[-1]
        if tid in TASKS:
            t = TASKS[tid]
            t["polls"] += 1
            if t["polls"] < t["need"]:
                return self.send_json({"id": tid, "status": "processing"})
            if t["error"]:
                return self.send_json({"id": tid, "status": "failed", "error": t["error"]})
            url = "/v1/media/out.png" if t["kind"] == "image" else "/v1/media/out.mp4"
            return self.send_json({"id": tid, "status": "completed", "data": [{"url": url}], "result": {"url": url}})
        self.send_json({"detail": "not found"}, 404)

    def do_POST(self):
        p = self.path
        b = self.body()  # dibaca dulu: body yang tertinggal merusak request berikutnya di koneksi yang sama
        if not self.authed():
            return
        if p == "/v1/intent":
            time.sleep(0.15)
            return self.send_json(classify(b["text"], b.get("last_kind"), b.get("attachments", 0)))
        if p in ("/v1/images/tasks", "/v1/videos"):
            kind = "image" if "images" in p else "video"
            LOG["media"].append({"kind": kind, **b})
            pr = b["prompt"]
            tid = f"t{len(TASKS) + 1}"
            TASKS[tid] = {"kind": kind, "polls": 0, "need": 3 if "LAMA" in pr else 1,
                          "error": ERR500 if "ERR500" in pr else REGION if "WILAYAH" in pr else OUTAGE if "GANGGUAN" in pr else None}
            return self.send_json({"id": tid, "status": "queued"})
        if p == "/v1/chat/completions":
            LOG["chat"] += 1
            msgs = b["messages"]
            last = msgs[-1]["content"]
            imgs = []
            if isinstance(last, list):  # format OpenAI: teks + image_url
                imgs = [x["image_url"]["url"] for x in last if x.get("type") == "image_url"]
                last = " ".join(x.get("text", "") for x in last if x.get("type") == "text")
            LOG.setdefault("chat_images", []).append(imgs)
            n = sum(m["role"] == "user" for m in msgs)
            text = (f"Saya melihat {len(imgs)} gambar. " if imgs else "") + (f"Jawaban ke-{n}: **tebal**\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```js\nconsole.log('hi')\n```\n\n"
                    f"Anda menulis: {last[:60]}")
            slow, cut = "LAMBAT" in last, "PUTUS" in last
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            pieces = [text[i:i + 12] for i in range(0, len(text), 12)]
            for i, piece in enumerate(pieces):
                if cut and i == 3:
                    self.close_connection = True
                    return
                chunk = {"choices": [{"delta": {"content": piece}}]}
                try:
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.3 if slow else 0.02)
            self.wfile.write(b"data: [DONE]\n\n")
            self.close_connection = True
            return
        self.send_json({"detail": "not found"}, 404)

    def file(self, path, ctype):
        self.raw(Path(path).read_bytes(), ctype)

    def raw(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


srv = ThreadingHTTPServer(("127.0.0.1", free_port()), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"
chrome = (shutil.which("chromium") or shutil.which("google-chrome") or next(
    (p for p in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"] if Path(p).exists()), None))
assert chrome, "Chrome/Chromium tidak ditemukan"
dport = free_port()
proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={dport}", f"--user-data-dir={TMP}/prof",
                         "--no-first-run", "--autoplay-policy=no-user-gesture-required", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
results, frames = [], {}


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


try:
    import urllib.request
    for _ in range(100):
        try:
            pages = [t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{dport}/json", timeout=1)) if t["type"] == "page"]
            break
        except Exception:
            time.sleep(0.1)
    c = CDP(pages[0]["webSocketDebuggerUrl"])
    c.send("Page.enable")
    js = lambda e: c.js(e)
    J = lambda e: json.loads(c.js("JSON.stringify(" + e + ")"))

    def until(expr, timeout=15.0):
        end = time.time() + timeout
        while time.time() < end:
            if J(expr):
                return True
            time.sleep(0.05)
        return False

    def shot(flow):
        if GIF:
            frames.setdefault(flow, []).append(base64.b64decode(c.send("Page.captureScreenshot")["result"]["data"]))

    def size(w, h=900):
        c.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": w < 500})

    def boot(key=KEY, clear=True):
        c.send("Page.navigate", {"url": BASE + "/#/chat"})
        time.sleep(0.4)
        js(f"localStorage.setItem('muse2api_key',{json.dumps(key)});" + ("localStorage.removeItem('muse2api_chats');" if clear else "") + "location.reload()")
        until("document.readyState==='complete' && !!document.getElementById('input')")
        time.sleep(0.3)

    def say(text):
        js(f"(()=>{{const i=document.getElementById('input');i.value={json.dumps(text)};i.dispatchEvent(new Event('input'));document.getElementById('form').requestSubmit()}})()")

    idle = "!document.querySelector('#send[aria-label=\"Hentikan\"]')"
    last_bubble = "((document.querySelector('.msg.assistant:last-of-type .bubble')||{}).innerText||'')"
    last_note = "((document.querySelector('.msg.assistant:last-of-type .note')||{}).textContent||'')"
    last_err = "((document.querySelector('.msg.assistant:last-of-type .err')||{}).textContent||'')"
    n_asst = "document.querySelectorAll('.msg.assistant').length"

    size(1440)
    boot()
    shot("chat")
    # 1. Umpan balik < 1 dtk dan kata pertama
    t0 = time.time()
    say("halo, apa kabar?")
    until("document.getElementById('send').getAttribute('aria-label')==='Hentikan'", 2)
    fb = time.time() - t0
    until(last_bubble + ".length>3", 5)
    ttft = time.time() - t0
    ok("umpan balik setelah kirim <= 1 dtk", fb <= 1.0, f"{fb:.2f}s")
    ok("kata pertama tampil < 2 dtk (backend palsu)", ttft < 2.0, f"{ttft:.2f}s")
    until(idle)
    shot("chat")
    # 2. multi-giliran + markdown
    say("dan kota nomor 2?")
    until(idle + " && " + last_bubble + ".includes('Jawaban ke-2')", 8)
    ok("riwayat dikirim (giliran ke-2 tahu ada 2 pesan user)", J(last_bubble + ".includes('Jawaban ke-2')"))
    ok("markdown: tabel, kode, tombol salin kode",
       J("!!document.querySelector('.msg.assistant:last-of-type table') && !!document.querySelector('.msg.assistant:last-of-type pre code') && !!document.querySelector('.msg.assistant:last-of-type [data-copy-code]')"))
    shot("chat")
    # 3. XSS
    say('<img src=x onerror="window.__x=1"><script>window.__x=2</script> tolong ulangi teks ini')
    until(idle, 8)
    ok("XSS tidak dieksekusi dan tampil sebagai teks",
       J("window.__x===undefined && !document.querySelector('#log .bubble img:not(.media)') && [...document.querySelectorAll('.msg.user .bubble')].pop().textContent.includes('<img')"), J("[window.__x, document.querySelectorAll('#log .bubble img:not(.media)').length, [...document.querySelectorAll('.msg.user .bubble')].pop().textContent.slice(0,40)]"))
    # 4. pesan panjang
    say("panjang " + ("kata " * 2000))
    until(idle, 10)
    ok("pesan 10.000 karakter tanpa luapan horizontal", J("document.documentElement.scrollWidth<=innerWidth && document.getElementById('log').scrollWidth<=document.getElementById('log').clientWidth+1"))
    # 5. Stop
    say("ceritakan sesuatu LAMBAT")
    until(last_bubble + ".length>5", 5)
    time.sleep(0.4)
    js("document.getElementById('send').click()")
    until(idle, 5)
    ok("Stop menghentikan stream dan memberi catatan", J(last_note + "==='Dihentikan.'") and J(last_bubble + ".length>0"), J(last_note))
    # 6. Ulangi
    before = J(n_asst)
    js("[...document.querySelectorAll('.msg.assistant:last-of-type .tools button')].find(b=>b.textContent.includes('Ulangi')).click()")
    until(idle + " && " + last_note + "!=='Dihentikan.'", 10)
    until(idle, 10)
    ok("Ulangi mengganti jawaban terakhir (jumlah bubble tetap)", J(n_asst) == before and J(last_note) != 'Dihentikan.', f"{before}->{J(n_asst)}")
    # 7. Edit
    js("[...document.querySelectorAll('.msg.user .tools button')].pop().click()")
    ok("Edit mengembalikan pesan ke input dan membuang jawabannya",
       J("document.getElementById('input').value.includes('LAMBAT') && document.activeElement.id==='input'") and J(n_asst) == before - 1)
    js("document.getElementById('input').value='';document.getElementById('input').dispatchEvent(new Event('input'))")
    # 8. kirim beruntun
    chats_before = LOG["chat"]
    js("(()=>{const i=document.getElementById('input'),f=document.getElementById('form');i.value='satu';i.dispatchEvent(new Event('input'));f.requestSubmit();i.value='dua';i.dispatchEvent(new Event('input'));f.requestSubmit()})()")
    until(idle, 8)
    time.sleep(0.3)
    ok("kirim beruntun hanya memulai satu jawaban", LOG["chat"] - chats_before == 1, f"{LOG['chat'] - chats_before} request")
    # 9. stream putus
    say("tes PUTUS koneksi")
    until(idle, 8)
    ok("stream putus: jawaban parsial disimpan + catatan", J(last_note) == "Jawaban terputus sebelum selesai." and J(last_bubble + ".length>0"), J(last_note))
    shot("chat")

    # 10. gambar
    js("document.getElementById('newBtn').click()")
    shot("gambar")
    say("buatkan gambar logo kedai kopi minimalis")
    until(last_note + ".startsWith('Gambar')", 3)
    ok("jenis 'Gambar' tampil sebelum hasil", J(last_note + ".startsWith('Gambar')"), J(last_note))
    shot("gambar")
    until(idle + " && !!document.querySelector('.msg.assistant:last-of-type img.media')", 12)
    ok("gambar tampil + tautan Unduh",
       J("!!document.querySelector('.msg.assistant:last-of-type img.media') && !!document.querySelector('.msg.assistant:last-of-type a.mini[download]')"))
    ok("gambar: alt berisi prompt", J("document.querySelector('.msg.assistant:last-of-type img.media').alt.includes('logo kedai kopi')"))
    shot("gambar")
    # 11. /video + 12. lanjutkan
    say("/video kucing tidur di jendela, 5 detik")
    until(last_note + ".startsWith('Video · 5 dtk')", 3)
    ok("perintah /video: label 'Video · 5 dtk'", J(last_note + ".startsWith('Video · 5 dtk')"), J(last_note))
    until(idle + " && !!document.querySelector('.msg.assistant:last-of-type video.media')", 15)
    cid = J("JSON.parse(localStorage.getItem('muse2api_chats')).find(c=>c.messages.some(m=>m.kind==='video')).id")
    v = LOG["media"][-1]
    ok("video: prompt tanpa '/video', conversation_id terkirim", v["prompt"] == "kucing tidur di jendela, 5 detik" and v["conversation_id"] == cid, json.dumps(v))
    ok("video tampil dengan kontrol", J("document.querySelector('.msg.assistant:last-of-type video.media').controls"))
    say("lanjutkan, kucingnya bangun dan meregang")
    until(last_note + ".includes('lanjutan')", 3)
    ok("'lanjutkan' dikenali sebagai lanjutan video", J(last_note + ".startsWith('Video') && " + last_note + ".includes('lanjutan')"), J(last_note))
    until(idle, 15)
    ok("lanjutan memakai conversation_id yang sama", LOG["media"][-1]["conversation_id"] == cid)
    shot("video")
    # 13. error
    say("buatkan video ERR500 pantura pagi")
    until(idle, 15)
    ok("error 500 muse.ai -> pesan Indonesia + Coba lagi",
       J(last_err + ".includes('Server muse.ai gagal')") and J(last_err + ".includes('Coba lagi')") and not J(last_err + ".includes('模型')"), J(last_err))
    shot("error")
    say("buatkan video WILAYAH pantai")
    until(idle, 15)
    ok("penolakan wilayah -> pesan Indonesia", J(last_err + ".includes('tidak tersedia untuk akun di wilayah')"), J(last_err))
    say("buatkan video GANGGUAN pantai")
    until(idle, 15)
    ok("pemutus gangguan -> pesan jelas dengan jam coba lagi",
       J(last_err + ".includes('sedang gangguan: 2 percobaan terakhir gagal (terakhir 12:07)') && " + last_err + ".includes('Coba lagi setelah 12:17')"), J(last_err))
    shot("error")
    # 14. refresh saat video diproses
    say("buatkan video LAMA matahari terbit")
    until("JSON.parse(localStorage.getItem('muse2api_chats')).some(c=>c.messages.some(m=>m.task && m.pending))", 6)
    boot(clear=False)
    js("document.querySelector('.th .open').click()")
    shot("refresh")
    done = until("!!document.querySelector('.msg.assistant:last-of-type video.media')", 20)
    ok("refresh saat video diproses -> tetap dipantau sampai hasil tampil", done and not J(last_err), J(last_err))
    shot("refresh")
    # 15b. lampiran gambar acuan: tombol/berkas, tolak non-gambar, hapus, tempel, kirim, video, pertanyaan
    open(os.path.join(TMP, "ref.png"), "wb").write(PNG)
    open(os.path.join(TMP, "catatan.txt"), "w").write("bukan gambar")

    def attach(path):
        root = c.send("DOM.getDocument")["result"]["root"]["nodeId"]
        node = c.send("DOM.querySelector", {"nodeId": root, "selector": "#file"})["result"]["nodeId"]
        c.send("DOM.setFileInputFiles", {"nodeId": node, "files": [path]})
        time.sleep(0.4)

    js("document.getElementById('newBtn').click()")
    attach(os.path.join(TMP, "catatan.txt"))
    ok("lampiran: file bukan gambar ditolak dengan pesan", J("document.getElementById('attMsg').textContent.includes('Hanya gambar') && document.querySelectorAll('.att').length===0"))
    attach(os.path.join(TMP, "ref.png"))
    ok("lampiran: pratinjau muncul", J("document.querySelectorAll('.att img').length===1"))
    js("document.querySelector('.att button').click()")
    ok("lampiran: tombol hapus berfungsi", J("document.querySelectorAll('.att').length===0 && document.getElementById('atts').hidden"))
    attach(os.path.join(TMP, "ref.png"))
    js("(()=>{const b=Uint8Array.from(atob(%s),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([b],'tempel.png',{type:'image/png'}));"
       "document.getElementById('input').dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}))})()" % json.dumps(base64.b64encode(PNG).decode()))
    until("document.querySelectorAll('.att').length===2", 3)
    ok("lampiran: tempel (Ctrl+V) gambar menambah lampiran", J("document.querySelectorAll('.att').length===2"))
    shot("lampiran")
    say("ubah jadi gaya anime")
    until(last_note + ".startsWith('Gambar')", 3)
    until(idle, 12)
    sent = LOG["media"][-1]
    same = len(sent.get("images") or []) == 2 and base64.b64decode(sent["images"][0].split(",", 1)[1]) == PNG
    ok("lampiran: 2 gambar terkirim byte-identik sebagai images[] ke /v1/images/tasks", sent["kind"] == "image" and same, str(len(sent.get("images") or [])))
    ok("lampiran: thumbnail di pesan user, pratinjau dikosongkan",
       J("document.querySelectorAll('.msg.user:last-of-type .uimgs img, .msg.user .uimgs img').length>=2 && document.querySelectorAll('.att').length===0"))
    shot("lampiran")
    attach(os.path.join(TMP, "ref.png"))
    say("animasikan, daunnya berguguran pelan")
    until(idle, 15)
    ok("lampiran + 'animasikan' -> video dengan gambar acuan", LOG["media"][-1]["kind"] == "video" and len(LOG["media"][-1].get("images") or []) == 1)
    chats_before = LOG["chat"]
    attach(os.path.join(TMP, "ref.png"))
    say("apa isi gambar ini?")
    until(idle, 8)
    got = LOG["chat_images"][-1] if LOG["chat"] > chats_before else []
    ok("lampiran + pertanyaan -> dijawab chat dengan gambarnya (byte-identik)",
       LOG["chat"] == chats_before + 1 and len(got) == 1 and base64.b64decode(got[0].split(",", 1)[1]) == PNG
       and J(last_bubble + ".includes('Saya melihat 1 gambar')") and not J(last_err), J(last_err) or J(last_bubble)[:80])
    shot("lampiran")
    boot(clear=False)
    js("[...document.querySelectorAll('.th .open')].find(b=>b.textContent.includes('ubah jadi')).click()")
    ok("lampiran: thumbnail tetap ada setelah refresh", J("document.querySelectorAll('.msg.user .uimgs img').length>=2"))
    idb_count = lambda: c.js("new Promise(r=>{const q=indexedDB.open('muse2api');q.onsuccess=()=>{try{const t=q.result.transaction('att').objectStore('att').count();t.onsuccess=()=>r(t.result)}catch(e){r(-1)}};q.onerror=()=>r(-1)})", await_promise=True)
    ok("IndexedDB: 3 pesan berlampiran tersimpan penuh", idb_count() == 3, str(idb_count()))
    js("[...document.querySelectorAll('.msg.user .tools button')].pop().click()")
    until("document.querySelectorAll('.att').length===1", 3)
    ok("setelah refresh: Edit mengembalikan lampiran dari IndexedDB", J("document.querySelectorAll('.att').length===1"))
    say("ubah jadi hitam putih")
    until(idle, 12)
    sent = LOG["media"][-1]
    ok("setelah refresh: gambar penuh terkirim byte-identik", sent["kind"] == "image" and len(sent.get("images") or []) == 1
       and base64.b64decode(sent["images"][0].split(",", 1)[1]) == PNG, json.dumps({k: (v if k != "images" else len(v)) for k, v in sent.items()})[:200] + " err=" + J(last_err))
    ok("IndexedDB: Edit tidak meninggalkan salinan lama", idb_count() == 3, str(idb_count()))
    say("terima kasih")
    until(idle, 8)
    ok("pertanyaan lanjutan tanpa lampiran tidak mengirim ulang gambar", LOG["chat_images"][-1] == [])

    # 15. riwayat: cari + hapus dua klik
    js("(()=>{const q=document.getElementById('q');q.value='kopi';q.dispatchEvent(new Event('input'))})()")
    ok("cari riwayat menyaring percakapan", J("document.querySelectorAll('.th').length===1"))
    js("(()=>{const q=document.getElementById('q');q.value='';q.dispatchEvent(new Event('input'))})()")
    nth = J("document.querySelectorAll('.th').length")
    target = "[...document.querySelectorAll('.th')].find(t=>t.textContent.includes('ubah jadi')).querySelector('.del')"
    js(target + ".click()")
    armed = J(target + ".textContent==='Hapus?'")
    js(target + ".click()")
    ok("hapus percakapan butuh dua klik", armed and J("document.querySelectorAll('.th').length") == nth - 1)
    time.sleep(0.3)
    ok("IndexedDB: hapus percakapan ikut menghapus gambar penuhnya", idb_count() == 0, str(idb_count()) + " " + json.dumps(J("JSON.parse(localStorage.getItem('muse2api_chats')).map(c=>c.title)")))
    # 16. HP + keyboard
    size(390, 844)
    boot(clear=False)
    js("document.querySelector('.th .open') && document.querySelector('.th .open').click()")
    time.sleep(0.3)
    ok("HP 390: tanpa luapan horizontal", J("document.documentElement.scrollWidth<=innerWidth"))
    shot("hp")
    size(1440)
    boot(clear=False)
    js("document.activeElement.blur()")
    seen = []
    for _ in range(30):
        for t in ("keyDown", "keyUp"):
            c.send("Input.dispatchKeyEvent", {"type": t, "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
        seen.append(J("(()=>{const e=document.activeElement;const r=e.getBoundingClientRect();return {id:e.id,cls:e.className,vis:r.width>0&&r.height>0}})()"))
    ok("keyboard: Tab mencapai input pesan", any(s["id"] == "input" for s in seen))
    ok("keyboard: fokus tidak jatuh ke elemen tak terlihat", all(s["vis"] for s in seen), json.dumps([s for s in seen if not s["vis"]][:3]))
    # 16b. key dari link disimpan ke browser dan dihapus dari alamat
    js("localStorage.removeItem('muse2api_key')")
    c.send("Page.navigate", {"url": BASE + "/?key=" + KEY + "#/chat"})
    until("document.readyState==='complete' && !!document.getElementById('input')")
    ok("?key= tersimpan ke localStorage & hilang dari URL",
       J(f"localStorage.getItem('muse2api_key')==={json.dumps(KEY)} && !location.search.includes('key')"),
       json.dumps([J("location.href"), J("localStorage.getItem('muse2api_key')")]))
    # 17. key salah
    boot(key="salah", clear=True)
    say("halo")
    until(idle, 6)
    ok("key salah -> pesan jelas + dialog key terbuka", J(last_err + ".includes('API Key')") and J("document.getElementById('keyDlg').open"), json.dumps([J(last_err), J("document.getElementById('keyDlg').open"), J(n_asst), J("document.querySelectorAll('.msg').length")]))
finally:
    proc.terminate()
    proc.wait()
    srv.shutdown()
    if GIF:
        os.makedirs(GIF, exist_ok=True)
        for flow, imgs in frames.items():
            d = os.path.join(TMP, "f_" + flow)
            os.makedirs(d, exist_ok=True)
            for i, b in enumerate(imgs):
                open(os.path.join(d, f"{i:03d}.png"), "wb").write(b)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", os.path.join(d, "%03d.png"), "-vf",
                            "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
                            os.path.join(GIF, f"chat_{flow}.gif")], check=False)
    shutil.rmtree(TMP, ignore_errors=True)

failed = [r for r in results if not r[1]]
print(f"{len(results) - len(failed)}/{len(results)} lulus")
sys.exit(1 if failed else 0)
