#!/usr/bin/env bash

set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 用户执行此脚本。" >&2
  exit 1
fi

PUBLIC_ORIGIN="${1:-}"
RELEASE_ID="${2:-}"

if [[ "$PUBLIC_ORIGIN" =~ ^http://([A-Za-z0-9._-]+)(:([0-9]{1,5}))?$ ]]; then
  SERVER_NAME="${BASH_REMATCH[1]}"
  LISTEN_PORT="${BASH_REMATCH[3]:-80}"
else
  echo "公开地址格式错误: $PUBLIC_ORIGIN" >&2
  echo "示例: http://192.0.2.10:10018" >&2
  exit 1
fi

if [[ -z "$RELEASE_ID" ]] || ((LISTEN_PORT < 1 || LISTEN_PORT > 65535)); then
  echo "用法: $0 http://服务器IP[:端口] 已存在的发布编号" >&2
  echo "示例: $0 http://192.0.2.10:10018 20260731-01" >&2
  exit 1
fi

APP_ROOT="/data/nicokara"
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
SHARED_DIR="$APP_ROOT/shared"
PYTHON_BIN="$RELEASE_DIR/backend/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "没有找到已安装依赖的虚拟环境: $PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -f "$RELEASE_DIR/frontend/server.js" ]]; then
  echo "没有找到前端产物: $RELEASE_DIR/frontend/server.js" >&2
  exit 1
fi

for required_file in \
  "$SHARED_DIR/models/faster-whisper-small/model.bin" \
  "$SHARED_DIR/models/audio-separator/UVR_MDXNET_KARA_2.onnx"; do
  if [[ ! -f "$required_file" ]]; then
    echo "缺少本地模型文件: $required_file" >&2
    exit 1
  fi
done

for command_name in node nginx curl systemctl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "缺少运行环境命令: $command_name" >&2
    exit 1
  fi
done

if ! id www-data >/dev/null 2>&1; then
  echo "缺少 www-data 系统用户，请确认 Nginx 已正确安装。" >&2
  exit 1
fi

echo "验证 Python 依赖..."
"$PYTHON_BIN" -c \
  'import audio_separator, faster_whisper, scipy, uvicorn; print("Python AI dependencies: OK")'

mkdir -p \
  "$SHARED_DIR/data" \
  "$SHARED_DIR/storage/jobs"

ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

WORKER_CONFIG="$SHARED_DIR/workers.toml"
if [[ ! -f "$WORKER_CONFIG" ]]; then
  cat >"$WORKER_CONFIG" <<EOF
[processing]
worker_count = 4
reload_interval_seconds = 1.0
EOF
fi

ANNOUNCEMENT_CONFIG="$SHARED_DIR/announcement.json"
if [[ ! -f "$ANNOUNCEMENT_CONFIG" ]]; then
  if [[ -f "$RELEASE_DIR/frontend/public/announcement.json" ]]; then
    cp "$RELEASE_DIR/frontend/public/announcement.json" "$ANNOUNCEMENT_CONFIG"
  else
    cat >"$ANNOUNCEMENT_CONFIG" <<EOF
{
  "id": "2026-08-06-qq-group-v1",
  "enabled": true,
  "title": "加入 QQ 交流群",
  "content": ["欢迎加入ニコカラ自动生成器 QQ 交流群：1101583605。"],
  "buttonLabel": "我知道了"
}
EOF
  fi
fi
mkdir -p "$RELEASE_DIR/frontend/public"
ln -sfn "$ANNOUNCEMENT_CONFIG" \
  "$RELEASE_DIR/frontend/public/announcement.json"

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
NICOKARA_WORKER_CONFIG_PATH=$WORKER_CONFIG
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
    listen $LISTEN_PORT;
    server_name $SERVER_NAME;

    client_max_body_size 1024m;
    add_header Cross-Origin-Opener-Policy same-origin always;
    add_header Cross-Origin-Embedder-Policy require-corp always;

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
echo "断点续跑完成: $PUBLIC_ORIGIN"
echo "当前发布目录: $RELEASE_DIR"
