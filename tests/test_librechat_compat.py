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
print("test_librechat_compat OK")
