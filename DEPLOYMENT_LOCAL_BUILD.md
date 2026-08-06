# 本地构建后部署到 `/data`

本文适用于以下部署方式：

- 本地完成前端生产构建。
- 服务器不使用 Docker，也不执行前端构建。
- 应用部署到 `/data/nicokara`。
- Whisper 模型单独上传，只在首次部署时传输。
- 后端 Python 依赖必须在 Linux 服务器安装，因为 macOS `.venv` 不能用于 Linux。

## 1. 本地构建

项目要求 Node.js `>=22.13.0`，建议本地和服务器统一使用 Node.js 24。

从项目根目录执行：

```bash
cd "./frontend"
npm ci
NEXT_PUBLIC_API_URL=/api/v1 npm run build

PORT=3100 HOST=127.0.0.1 node dist/standalone/server.js
cd ..
```

另开终端验证，成功后停止上面的前端进程：

```bash
curl -I http://127.0.0.1:3100/
```

## 2. 本地生成部署包

应用包和两个模型包分开。后续更新应用时，不需要重复上传模型。

```bash
PROJECT_ROOT="$(pwd)"
PACKAGE_STAGE="$(mktemp -d)"
RELEASE_NAME="nicokara-app-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$PROJECT_ROOT/release"
mkdir -p \
  "$PACKAGE_STAGE/nicokara/frontend" \
  "$PACKAGE_STAGE/nicokara/backend"

rsync -a \
  --exclude=".DS_Store" \
  "$PROJECT_ROOT/frontend/dist/standalone/" \
  "$PACKAGE_STAGE/nicokara/frontend/"
rsync -a \
  --exclude="__pycache__/" \
  --exclude="*.pyc" \
  --exclude="*.pyo" \
  "$PROJECT_ROOT/backend/app/" \
  "$PACKAGE_STAGE/nicokara/backend/app/"
cp "$PROJECT_ROOT/backend/pyproject.toml" \
  "$PACKAGE_STAGE/nicokara/backend/pyproject.toml"

tar -C "$PACKAGE_STAGE" -czf \
  "$PROJECT_ROOT/release/$RELEASE_NAME.tar.gz" nicokara

tar \
  --exclude="faster-whisper-small/.cache" \
  -C "$PROJECT_ROOT/models" \
  -czf "$PROJECT_ROOT/release/faster-whisper-small.tar.gz" \
  faster-whisper-small

tar \
  -C "$PROJECT_ROOT/models" \
  -czf "$PROJECT_ROOT/release/audio-separator-UVR_MDXNET_KARA_2.tar.gz" \
  audio-separator

(
  cd "$PROJECT_ROOT/release"
  shasum -a 256 \
    "$RELEASE_NAME.tar.gz" \
    "faster-whisper-small.tar.gz" \
    "audio-separator-UVR_MDXNET_KARA_2.tar.gz" \
    > "SHA256SUMS"
)
```

## 3. 上传服务器

将命令中的服务器地址和应用包名替换为实际值：

```bash
scp \
  "./release/nicokara-app-YYYYMMDD-HHMMSS.tar.gz" \
  "./release/faster-whisper-small.tar.gz" \
  "./release/audio-separator-UVR_MDXNET_KARA_2.tar.gz" \
  "./release/SHA256SUMS" \
  root@SERVER_IP:/data/
```

服务器解压前先校验：

```bash
cd /data
sha256sum -c SHA256SUMS
```

也可以上传并运行已生成的一键部署脚本。它从本节之后的步骤开始执行：

```bash
scp \
  "./release/deploy-nicokara-from-data.sh" \
  root@SERVER_IP:/data/

ssh root@SERVER_IP
chmod +x /data/deploy-nicokara-from-data.sh
/data/deploy-nicokara-from-data.sh http://SERVER_IP 20260731-01
```

## 4. 准备服务器

以下命令以 Ubuntu 24.04 为例。先安装系统依赖和 Node.js 24：

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  curl \
  ffmpeg \
  fonts-noto-cjk \
  nginx \
  python3 \
  python3-venv

curl -fsSL https://deb.nodesource.com/setup_24.x \
  -o /tmp/nodesource_setup.sh
sudo -E bash /tmp/nodesource_setup.sh
sudo apt install -y nodejs

node -v
python3 --version
ffmpeg -version
```

要求：

- Node.js `>=22.13.0`，推荐 24.x。
- Python `>=3.11`。
- `ffmpeg` 可从 `PATH` 调用。

## 5. 解压并安装

每次发布使用新的版本目录，`current` 指向当前版本，便于回滚。

```bash
RELEASE_ID="$(date +%Y%m%d-%H%M%S)"
APP_ARCHIVE="/data/nicokara-app-YYYYMMDD-HHMMSS.tar.gz"
RELEASE_DIR="/data/nicokara/releases/$RELEASE_ID"

sudo mkdir -p \
  "$RELEASE_DIR" \
  /data/nicokara/shared/data \
  /data/nicokara/shared/storage/jobs \
  /data/nicokara/shared/models

sudo tar -xzf "$APP_ARCHIVE" \
  -C "$RELEASE_DIR" \
  --strip-components=1

sudo tar -xzf /data/faster-whisper-small.tar.gz \
  -C /data/nicokara/shared/models

sudo tar -xzf /data/audio-separator-UVR_MDXNET_KARA_2.tar.gz \
  -C /data/nicokara/shared/models

sudo chown -R www-data:www-data /data/nicokara/shared

cd "$RELEASE_DIR/backend"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[ai]"

sudo ln -sfn "$RELEASE_DIR" /data/nicokara/current
```

## 6. 后端环境变量

创建 worker 配置 `/data/nicokara/shared/workers.toml`：

```toml
[processing]
worker_count = 4
reload_interval_seconds = 1.0
```

运行时修改 `worker_count` 会在 1 秒内生效，无需重启 systemd 服务。全站公告配置位于
`/data/nicokara/shared/announcement.json`；修改 JSON 后刷新页面即可生效，设置
`enabled` 为 `false` 可关闭公告。

创建 `/data/nicokara/shared/nicokara.env`：

```ini
NICOKARA_DATA_DIR=/data/nicokara/shared/data
NICOKARA_STORAGE_DIR=/data/nicokara/shared/storage/jobs
NICOKARA_ALLOWED_ORIGINS=http://SERVER_IP
NICOKARA_TRUSTED_PROXY_HOSTS=127.0.0.1,::1
NICOKARA_MAX_PENDING_JOBS=4
NICOKARA_MAX_ACTIVE_JOBS_PER_CLIENT=2
NICOKARA_WORKER_CONFIG_PATH=/data/nicokara/shared/workers.toml
NICOKARA_WORKER_HEARTBEAT_INTERVAL_SECONDS=5
NICOKARA_PROCESSING_ENABLED=true
NICOKARA_FFMPEG_PATH=ffmpeg
NICOKARA_WHISPER_MODEL=/data/nicokara/shared/models/faster-whisper-small
NICOKARA_WHISPER_DEVICE=cpu
NICOKARA_WHISPER_COMPUTE_TYPE=int8
NICOKARA_VOCAL_REMOVAL_BACKEND=mdx
NICOKARA_VOCAL_REMOVAL_MODEL=UVR_MDXNET_KARA_2.onnx
NICOKARA_VOCAL_REMOVAL_MODEL_DIR=/data/nicokara/shared/models/audio-separator
NICOKARA_DEEPSEEK_API_KEY=
NICOKARA_ADMIN_TOKEN=请替换为随机管理员令牌
```

有域名和 HTTPS 时，必须把 `NICOKARA_ALLOWED_ORIGINS` 改为真实地址，例如
`https://karaoke.example.com`。

`NICOKARA_TRUSTED_PROXY_HOSTS` 只填写实际反向代理地址或网段。默认部署中 Nginx
与后端位于同一台服务器，因此使用 `127.0.0.1,::1`。不要填写 `0.0.0.0/0`，否则客户端
可以伪造转发地址绕过按来源限流。

使用以下命令生成管理员令牌，将输出写入 `NICOKARA_ADMIN_TOKEN`，不要提交到 Git：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

设置后重启后端，通过 `https://你的域名/admin` 进入监控页面。队列健康探针为
`/api/v1/admin/queue-health`，请求必须携带 `Authorization: Bearer <令牌>`。

## 7. systemd

创建 `/etc/systemd/system/nicokara-backend.service`：

```ini
[Unit]
Description=Nicokara FastAPI Backend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/data/nicokara/current/backend
EnvironmentFile=/data/nicokara/shared/nicokara.env
ExecStart=/data/nicokara/current/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

创建 `/etc/systemd/system/nicokara-frontend.service`：

```ini
[Unit]
Description=Nicokara Frontend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/data/nicokara/current/frontend
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT=3000
ExecStart=/usr/bin/node /data/nicokara/current/frontend/server.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nicokara-backend nicokara-frontend
sudo systemctl status nicokara-backend nicokara-frontend --no-pager
```

后端保持单进程，不要增加 Uvicorn worker 数量。需要提高吞吐时，先调整
`/data/nicokara/shared/workers.toml` 中的 `processing.worker_count`；多实例部署前
需要迁移到共享任务队列。上传成功的任务会先写入 SQLite 持久队列，后台 worker 按
提交顺序自动处理。

## 8. Nginx

创建 `/etc/nginx/sites-available/nicokara`：

```nginx
server {
    listen 80;
    server_name SERVER_IP_OR_DOMAIN;

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
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用配置：

```bash
sudo ln -sfn \
  /etc/nginx/sites-available/nicokara \
  /etc/nginx/sites-enabled/nicokara
sudo nginx -t
sudo systemctl reload nginx
```

## 9. 验收

```bash
curl -fsS http://127.0.0.1:8000/health
curl -I http://127.0.0.1:3000/
curl -I http://SERVER_IP/

sudo journalctl -u nicokara-backend -n 100 --no-pager
sudo journalctl -u nicokara-frontend -n 100 --no-pager
```

最后通过网页上传一个短 MP4 和歌词，验证上传、Whisper 转录、字幕生成、视频烧录和下载。

## 10. 剩余边界

- `faster-whisper-small` 和 `UVR_MDXNET_KARA_2.onnx` 均已放入独立的本地模型包，服务器运行时不需要下载这两个模型。
- 保持 `NICOKARA_DEEPSEEK_API_KEY` 为空时，歌词读音处理使用本地 `pykakasi`，不会调用 DeepSeek API。
- 本地生成的 Python `.venv` 和 `frontend/node_modules` 不应上传，它们可能包含与操作系统或 CPU 架构相关的文件。
- `npm ci` 当前报告 16 个依赖漏洞，其中 15 个为 high。不要直接执行可能引入破坏性升级的 `npm audit fix --force`，应单独评估依赖升级。
