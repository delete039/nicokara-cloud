#!/usr/bin/env bash

set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 用户执行此脚本。" >&2
  exit 1
fi

PUBLIC_ORIGIN="${1:-}"
RELEASE_ID="${2:-20260731-01}"

if [[ ! "$PUBLIC_ORIGIN" =~ ^http://[A-Za-z0-9._-]+$ ]]; then
  echo "用法: $0 http://服务器IP [发布编号]" >&2
  echo "示例: $0 http://192.0.2.10 20260731-01" >&2
  exit 1
fi

SERVER_NAME="${PUBLIC_ORIGIN#http://}"
APP_ARCHIVE="/data/nicokara-app-20260731.tar.gz"
WHISPER_ARCHIVE="/data/faster-whisper-small.tar.gz"
MDX_ARCHIVE="/data/audio-separator-UVR_MDXNET_KARA_2.tar.gz"
APP_ROOT="/data/nicokara"
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
SHARED_DIR="$APP_ROOT/shared"

for command_name in sha256sum tar python3 node ffmpeg nginx curl systemctl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "缺少运行环境命令: $command_name，请先完成部署步骤 2。" >&2
    exit 1
  fi
done

python3 -c \
  'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11+"'

if ! node -e \
  'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 13) ? 0 : 1)'; then
  echo "Node.js 版本过低，需要 >=22.13.0，推荐 24.x。" >&2
  exit 1
fi

if ! id www-data >/dev/null 2>&1; then
  echo "缺少 www-data 系统用户，请确认 Nginx 已正确安装。" >&2
  exit 1
fi

echo "校验部署包..."
(
  cd /data
  printf '%s  %s\n' \
    "4b0e359c808aeebd072e77e6c89c258937f39d6590e15f1145d7eb5fbef188bc" \
    "nicokara-app-20260731.tar.gz" \
    "eed6bf573d4b0f26265f0496512b927206d570ac2545b0a1df3f1e9a53a32a90" \
    "faster-whisper-small.tar.gz" \
    "cfbf3e7818851a142aaf085237a918fbf8b14d2e3fd92c94739e17f752d0b415" \
    "audio-separator-UVR_MDXNET_KARA_2.tar.gz" |
    sha256sum -c -
)

mkdir -p \
  "$RELEASE_DIR" \
  "$SHARED_DIR/data" \
  "$SHARED_DIR/storage/jobs" \
  "$SHARED_DIR/models"

if find "$RELEASE_DIR" -mindepth 1 -print -quit | grep -q .; then
  echo "发布目录非空，拒绝覆盖: $RELEASE_DIR" >&2
  echo "请指定新的发布编号，例如: $0 $PUBLIC_ORIGIN 20260731-02" >&2
  exit 1
fi

echo "解压应用..."
tar -xzf "$APP_ARCHIVE" -C "$RELEASE_DIR" --strip-components=1

WHISPER_MODEL="$SHARED_DIR/models/faster-whisper-small/model.bin"
if [[ ! -f "$WHISPER_MODEL" ]]; then
  echo "解压 Whisper 模型..."
  tar -xzf "$WHISPER_ARCHIVE" -C "$SHARED_DIR/models"
fi

MDX_MODEL="$SHARED_DIR/models/audio-separator/UVR_MDXNET_KARA_2.onnx"
if [[ ! -f "$MDX_MODEL" ]]; then
  echo "解压 MDX 人声分离模型..."
  tar -xzf "$MDX_ARCHIVE" -C "$SHARED_DIR/models"
fi

printf '%s  %s\n' \
  "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671" \
  "$WHISPER_MODEL" \
  "bf32e15105a09c0f7dddd2b67346146334d6f3ecb399ed7638eba2ab07cbf5f4" \
  "$MDX_MODEL" |
  sha256sum -c -

echo "安装后端 Python 依赖..."
python3 -m venv "$RELEASE_DIR/backend/.venv"
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install --upgrade pip
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install \
  -e "$RELEASE_DIR/backend[ai]"

ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

cat >"$SHARED_DIR/nicokara.env" <<EOF
NICOKARA_DATA_DIR=$SHARED_DIR/data
NICOKARA_STORAGE_DIR=$SHARED_DIR/storage/jobs
NICOKARA_ALLOWED_ORIGINS=$PUBLIC_ORIGIN
NICOKARA_TRUSTED_PROXY_HOSTS=127.0.0.1,::1
NICOKARA_MAX_PENDING_JOBS=4
NICOKARA_MAX_ACTIVE_JOBS_PER_CLIENT=2
NICOKARA_MAX_UPLOAD_SLOTS=1
NICOKARA_UPLOAD_TICKET_TIMEOUT_SECONDS=120
NICOKARA_UPLOAD_TICKET_UPLOAD_TIMEOUT_SECONDS=3600
NICOKARA_PROCESSING_WORKER_COUNT=1
NICOKARA_WORKER_HEARTBEAT_INTERVAL_SECONDS=5
NICOKARA_PROCESSING_ENABLED=true
NICOKARA_FFMPEG_PATH=ffmpeg
NICOKARA_WHISPER_MODEL=$SHARED_DIR/models/faster-whisper-small
NICOKARA_WHISPER_DEVICE=cpu
NICOKARA_WHISPER_COMPUTE_TYPE=int8
NICOKARA_VOCAL_REMOVAL_BACKEND=mdx
NICOKARA_VOCAL_REMOVAL_MODEL=UVR_MDXNET_KARA_2.onnx
NICOKARA_VOCAL_REMOVAL_MODEL_DIR=$SHARED_DIR/models/audio-separator
NICOKARA_DEEPSEEK_API_KEY=
NICOKARA_ADMIN_TOKEN=$ADMIN_TOKEN
EOF

chown -R www-data:www-data "$SHARED_DIR"
chmod 640 "$SHARED_DIR/nicokara.env"
ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"

cat >/etc/systemd/system/nicokara-backend.service <<EOF
[Unit]
Description=Nicokara FastAPI Backend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$APP_ROOT/current/backend
EnvironmentFile=$SHARED_DIR/nicokara.env
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=HOME=$SHARED_DIR
ExecStart=$APP_ROOT/current/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/nicokara-frontend.service <<EOF
[Unit]
Description=Nicokara Frontend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$APP_ROOT/current/frontend
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT=3000
ExecStart=$(command -v node) $APP_ROOT/current/frontend/server.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/nginx/sites-available/nicokara <<EOF
server {
    listen 80;
    server_name $SERVER_NAME;

    client_max_body_size 1024m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_read_timeout 7200s;
        proxy_send_timeout 7200s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sfn \
  /etc/nginx/sites-available/nicokara \
  /etc/nginx/sites-enabled/nicokara

nginx -t
systemctl daemon-reload
systemctl enable --now nicokara-backend nicokara-frontend nginx
systemctl restart nicokara-backend nicokara-frontend
systemctl reload nginx

echo "检查服务..."
BACKEND_READY=false
for _ in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null; then
    BACKEND_READY=true
    break
  fi
  sleep 1
done

if [[ "$BACKEND_READY" != "true" ]]; then
  echo "后端未在 30 秒内就绪。" >&2
  journalctl -u nicokara-backend -n 100 --no-pager >&2
  exit 1
fi

curl --fail --silent --show-error http://127.0.0.1:8000/health
echo
curl --fail --silent --show-error --head http://127.0.0.1:3000/ |
  sed -n '1p'

echo
echo "部署完成: $PUBLIC_ORIGIN"
echo "发布目录: $RELEASE_DIR"
echo "查看日志:"
echo "  journalctl -u nicokara-backend -n 100 --no-pager"
echo "  journalctl -u nicokara-frontend -n 100 --no-pager"
