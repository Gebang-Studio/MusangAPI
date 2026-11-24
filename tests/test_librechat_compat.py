"""Run: venv/bin/python tests/test_librechat_compat.py — GemuseAPI sebagai backend LibreChat (deploy/librechat).

1. Tool gambar LibreChat (image_gen_oai) mengirim parameter gaya gpt-image (output_format, quality, background)
   tanpa response_format dan hanya membaca data[0].b64_json. Model gpt-image di OpenAI selalu menjawab b64_json.
2. deploy/librechat/librechat.yaml: versi skema, endpoint GemuseAPI, kunci dari env (bukan ditulis di file).
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = tempfile.TemporaryDirectory(prefix="muse-librechat-test-")
os.environ.update(MUSE2API_HOME=HOME.name, MUSE2API_PROFILE_ROOT=HOME.name, MUSE2API_KEY="test-only")
import app  # noqa: E402

# ---- 1. response_format ----
libre = app.ImageRequest(prompt="kucing", model="muse-image", n=1, size="1024x1024",
                         quality="auto", background="auto", output_format="png", output_compression=100)
assert libre.response_format == "b64_json", libre.response_format
assert app.ImageRequest(prompt="x").response_format == "url"  # klien OpenAI lama (dall-e): default tetap url
assert app.ImageRequest(prompt="x", output_format="png", response_format="url").response_format == "url"  # eksplisit menang
print("ok: permintaan gaya gpt-image dijawab b64_json, selain itu tetap url")

# ---- 2. librechat.yaml ----
cfg = (ROOT / "deploy" / "librechat" / "librechat.yaml").read_text()
import yaml  # noqa: E402

data = yaml.safe_load(cfg)
assert str(data["version"]).count(".") == 2, data["version"]
ep = next(e for e in data["endpoints"]["custom"] if e["name"] == "GemuseAPI")
assert ep["apiKey"] == "${GEMUSE_API_KEY}" and ep["baseURL"] == "${GEMUSE_BASE_URL}", ep
assert "muse-spark" in ep["models"]["default"], ep["models"]
assert "sk-" not in cfg, "API key tidak boleh ditulis di librechat.yaml"
compose = (ROOT / "deploy" / "librechat" / "docker-compose.yml").read_text()
assert "127.0.0.1:3080:3080" in compose, "LibreChat hanya boleh dibuka dari komputer ini"
assert ":latest" not in compose, "versi image harus dipatok"
print("ok: librechat.yaml dan docker-compose.yml")

# ---- 3. muse-image / muse-video lewat /v1/chat/completions (klien chat seperti LibreChat) ----
import asyncio  # noqa: E402
import json  # noqa: E402
from unittest.mock import patch  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")  # cukup untuk data URI
os.makedirs(app.CFG.media_dir, exist_ok=True)
open(os.path.join(app.CFG.media_dir, "uji.png"), "wb").write(PNG)
calls = []


def fake_run(prompt, kind, timeout, **kw):
    calls.append((prompt, kind, kw.get("reference_images")))
    return {"filename": "uji.png" if kind == "image" else "uji.mp4", "kind": kind, "size": len(PNG)}, {"id": "a"}


async def call(body):
    payload = json.dumps(body).encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": "/v1/chat/completions", "raw_path": b"/v1/chat/completions", "query_string": b"",
             "root_path": "", "server": ("t", 80), "client": ("t", 1),
             "headers": [(b"authorization", b"Bearer test-only"), (b"content-type", b"application/json"),
                         (b"content-length", str(len(payload)).encode())]}
    sent, out = [], []

    async def receive():
        if not sent:
            sent.append(1)
            return {"type": "http.request", "body": payload, "more_body": False}
        await asyncio.sleep(3600)

    async def send(m):
        out.append(m)
    await asyncio.wait_for(app.app(scope, receive, send), timeout=15)
    status = next(m["status"] for m in out if m["type"] == "http.response.start")
    return status, b"".join(m.get("body", b"") for m in out).decode()


msgs = [{"role": "user", "content": "halo"}, {"role": "assistant", "content": "hai"},
        {"role": "user", "content": "kucing oranye di atap"}]
with patch.object(app, "_run_generation", fake_run), patch.object(app, "_public_base", lambda: ""):
    st, body = asyncio.run(call({"model": "muse-image", "messages": msgs}))
    content = json.loads(body)["choices"][0]["message"]["content"]
    assert st == 200 and content.startswith("![kucing oranye di atap](data:image/png;base64,"), (st, content[:120])
    assert calls[-1][1] == "image" and "kucing oranye di atap" in calls[-1][0] and "halo" not in calls[-1][0], calls[-1]
    st, body = asyncio.run(call({"model": "muse-image", "stream": True, "messages": msgs}))
    assert st == 200 and "data:image/png;base64," in body and body.rstrip().endswith("data: [DONE]"), body[-200:]
    st, body = asyncio.run(call({"model": "muse-image", "messages": [{"role": "user", "content": "  "}]}))
    assert st == 400, (st, body)  # prompt kosong tanpa acuan: kuota tidak dipakai
    st, body = asyncio.run(call({"model": "muse-video", "messages": msgs}))
    assert st == 200 and "MUSE2API_PUBLIC_BASE" in json.loads(body)["choices"][0]["message"]["content"], body
with patch.object(app, "_run_generation", fake_run), patch.object(app, "_public_base", lambda: "http://127.0.0.1:18610"):
    st, body = asyncio.run(call({"model": "muse-video", "messages": msgs}))
    assert "(http://127.0.0.1:18610/v1/media/uji.mp4)" in json.loads(body)["choices"][0]["message"]["content"], body
print("ok: muse-image/muse-video lewat chat completions (markdown, stream, prompt kosong, public_base)")
print("test_librechat_compat OK")
