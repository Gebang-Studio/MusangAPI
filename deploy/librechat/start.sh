#!/usr/bin/env bash
# Nyalakan LibreChat (UI chat alternatif) yang tersambung ke GemuseAPI di komputer ini.
#   deploy/librechat/start.sh          nyalakan / perbarui
#   deploy/librechat/start.sh stop     matikan (data percakapan tetap di deploy/librechat/data)
# Butuh Docker + docker compose. GemuseAPI harus sudah berjalan (port 18610).
set -euo pipefail
cd "$(dirname "$0")"

die() { printf '\033[1;31mGAGAL:\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }

command -v docker >/dev/null || die "Docker belum terpasang."
docker compose version >/dev/null 2>&1 || die "Plugin 'docker compose' tidak ada. Pasang docker-compose."

if [ "${1:-}" = "stop" ]; then
  docker compose down
  exit 0
fi

ROOT_ENV=../../.env
KEY=$(sed -n 's/^MUSE2API_KEY=//p' "$ROOT_ENV" 2>/dev/null | tail -1)
[ -n "$KEY" ] || die "MUSE2API_KEY tidak ditemukan di $ROOT_ENV. Jalankan GemuseAPI sekali dulu."
BASE="${GEMUSE_BASE_URL:-http://host.docker.internal:18610/v1}"

hex() { openssl rand -hex "$1"; }
if [ ! -f .env ]; then
  say "Membuat deploy/librechat/.env (rahasia acak, hanya untuk komputer ini)…"
  umask 077
  cat >.env <<EOF
DOMAIN_CLIENT=http://localhost:3080
DOMAIN_SERVER=http://localhost:3080
CREDS_KEY=$(hex 32)
CREDS_IV=$(hex 16)
JWT_SECRET=$(hex 32)
JWT_REFRESH_SECRET=$(hex 32)
ALLOW_EMAIL_LOGIN=true
ALLOW_REGISTRATION=true
ALLOW_SOCIAL_LOGIN=false
ALLOW_UNVERIFIED_EMAIL_LOGIN=true
GEMUSE_API_KEY=
GEMUSE_BASE_URL=
IMAGE_GEN_OAI_API_KEY=
IMAGE_GEN_OAI_BASEURL=
IMAGE_GEN_OAI_MODEL=muse-image
EOF
fi
# Kunci GemuseAPI bisa diganti dari admin; samakan setiap kali start.
for k in GEMUSE_API_KEY IMAGE_GEN_OAI_API_KEY; do sed -i.bak "s|^$k=.*|$k=$KEY|" .env; done
for k in GEMUSE_BASE_URL IMAGE_GEN_OAI_BASEURL; do sed -i.bak "s|^$k=.*|$k=$BASE|" .env; done
rm -f .env.bak
chmod 600 .env
mkdir -p data/mongo data/uploads data/images data/logs

say "Menyalakan LibreChat + MongoDB (unduhan pertama ~5 GB)…"
docker compose up -d

for _ in $(seq 1 90); do
  curl -fsm2 http://127.0.0.1:3080/health >/dev/null 2>&1 && break
  sleep 2
done
curl -fsm2 http://127.0.0.1:3080/health >/dev/null 2>&1 || die "LibreChat belum menjawab. Lihat: docker compose -f deploy/librechat/docker-compose.yml logs librechat"

cat <<EOF

LibreChat siap: http://localhost:3080
  1. Klik "Sign up". Akun PERTAMA otomatis menjadi admin.
  2. Pilih endpoint "GemuseAPI", model "muse-spark", lalu mulai chat.
  3. Setelah semua akun dibuat, tutup pendaftaran: ubah ALLOW_REGISTRATION=false di deploy/librechat/.env,
     lalu jalankan start.sh lagi.
UI bawaan GemuseAPI (gambar, video, batch) tetap di http://127.0.0.1:18610/chat
EOF
