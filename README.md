# ニコカラ自动生成器 Cloud

面向没有字幕制作和视频剪辑经验的用户，提供简单、快速的ニコカラ视频生成服务。

只需上传原始 MV 和歌词文本，系统即可自动完成歌词时间轴匹配、汉字假名注音、Karaoke 逐字变色字幕生成及视频渲染。无需学习字幕打轴、ASS 特效或视频剪辑，即可在 KTV 等使用场景中快速生成并播放ニコカラ视频。

## 项目定位

云端轻量版以“开箱即用”为核心：

- 无需安装专业软件
- 无需掌握字幕打轴
- 无需学习视频剪辑
- 通过浏览器完成上传、生成和下载
- 尽可能减少参数设置和操作步骤

适合希望快速制作ニコカラ视频的普通用户，以及临时需要在 KTV 现场生成歌曲视频的使用场景。

## 当前运行状态

当前代码已完成 Phase 1-8，具备完整的视频生成闭环，并已用于 Linux 服务器部署。生产环境采用 Nginx、systemd 和 `/data/nicokara` 发布目录，前端与后端仅监听服务器本机端口，由 Nginx 统一对外提供服务。

> GitHub 仓库中的代码不会自动同步到正在运行的服务器。修改代码后仍需重新构建、打包、上传并切换服务器版本，具体步骤见 [本地构建与无 Docker 部署指南](./DEPLOYMENT_LOCAL_BUILD.md)。

## 当前能力

| 模块 | 状态 | 能力 |
|---|---|---|
| 素材上传 | 已完成 | MP4 校验、1 GB 限制、歌词粘贴或 UTF-8 TXT 上传、上传进度 |
| 人声模式 | 已完成 | `ON VOCAL` 保留原人声；`OFF VOCAL` 使用 MDX 生成人声分离后的伴奏 |
| 歌声识别 | 已完成 | FFmpeg 音频提取、faster-whisper 日语识别和词级时间戳 |
| 歌词处理 | 已完成 | DeepSeek 可选处理、pykakasi 本地降级、Ruby 注音和 Mora 拆分 |
| 时间轴与字幕 | 已完成 | 歌词对齐、漏词插值、ASS v4+、逐字高亮和 Ruby 注音 |
| 视频合成 | 已完成 | FFmpeg/libass 烧录、H.264 MP4、在线播放和下载 |
| 前端反馈 | 已完成 | 中文进度、服务器错误分类、详细原因、解决方案和技术信息 |
| 运行保护 | 已完成 | 原子队列容量、来源并发上限、实时排队位置、任务取消、重启恢复和自动清理 |
| 部署 | 已完成 | Docker Compose；Linux 下的 Nginx + systemd + `/data/nicokara` 发布结构 |

## 当前能力详情

- Next.js + React + TypeScript + Tailwind CSS 前端
- FastAPI 后端
- SQLite 任务元数据
- MP4 内容检查、流式写入、大小限制和 SHA-256
- 粘贴歌词或 UTF-8 TXT 歌词上传
- `ON VOCAL` 保留原人声，`OFF VOCAL` 使用 MDX 模型生成伴奏
- 每个任务独立的本地存储目录
- 上传进度、中文任务阶段和结果页面
- 面向服务器部署的错误反馈，覆盖上传、网络、HTTP 状态和处理阶段失败
- 错误卡片提供解决方案、重试入口、任务 ID 和必要的技术信息
- FFmpeg 提取 16 kHz 单声道 PCM 分析音频
- faster-whisper 日语识别、分段和词级时间戳
- 单任务后台队列、原子容量预留、来源并发上限、实时排队位置和任务取消，避免单个用户占满队列
- `transcript.json` 下载接口
- DeepSeek JSON 歌词格式化、分句和读音处理
- pykakasi 本地平假名降级处理
- Ruby 所需的 `surface`/`reading` token
- `lyrics_processed.json` 下载接口
- 日语读音规范化与 Mora（拍）拆分
- 歌词 Mora 与 Whisper 词级时间戳对齐
- ASR 漏词区间自动插值、匹配置信度和警告
- `timeline.json` 下载接口
- ASS v4+ 字幕生成
- 逐字符 `\kf` Karaoke 平滑变色标签
- 汉字上方 Ruby 平假名注音
- ニコカラ风高亮色、未唱色、描边和阴影样式
- 可配置画布、字体、字号和字幕基线
- 用户歌词 ASS 控制字符转义
- `lyrics.ass` 下载接口
- FFmpeg/libass 字幕烧录
- H.264、`yuv420p`、faststart MP4 输出
- `ON VOCAL` 使用原 MP4 音轨，`OFF VOCAL` 使用分离后的伴奏音轨
- 支持 HTTP Range 的结果视频预览
- `final_karaoke.mp4` 下载接口
- Docker 内置 Noto CJK 日文字体
- Docker Compose 本地运行环境

## 当前开发重点

来源并发控制、顺序处理、排队位置和任务取消已经完成。下一阶段主要优化方向包括：

- 在真实多人上传场景中持续压测并调整队列及同时任务参数
- 增加任务历史、用户隔离和存储配额
- 优化大文件上传和异常恢复能力
- 控制服务器资源占用，避免任务互相影响

## 处理流程

上传任务会依次经过以下阶段：

```text
上传完成
-> 提取音频
-> 分离人声（仅 OFF VOCAL）
-> 识别歌声
-> 处理歌词与假名
-> 对齐歌词时间轴
-> 生成 ASS 字幕
-> 合成最终视频
-> 在线预览或下载
```

成功任务会在独立任务目录中生成：

```text
storage/jobs/{job_id}/
|-- input.mp4
|-- lyrics.txt
|-- audio.wav
|-- audio_instrumental.wav      # 仅 OFF VOCAL
|-- transcript.json
|-- lyrics_processed.json
|-- timeline.json
|-- lyrics.ass
`-- final_karaoke.mp4
```

## 技术架构

```text
浏览器
|-- /       -> Nginx -> Next.js 前端 127.0.0.1:3000
`-- /api/   -> Nginx -> FastAPI 后端 127.0.0.1:8000
                           |-- SQLite
                           |-- storage/jobs
                           `-- Whisper/MDX 本地模型
```

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、SQLite
- 音视频：FFmpeg、libass、MDX-Net
- 识别与歌词：faster-whisper、DeepSeek（可选）、pykakasi（本地降级）
- 部署：Docker Compose，或 Linux + Nginx + systemd

## 项目目录

```text
frontend/       Next.js 前端
backend/        FastAPI 后端与测试
release/        Linux 发布、部署和恢复脚本
storage/jobs/   本地任务文件，不提交到 Git
DEPLOYMENT_LOCAL_BUILD.md  构建、发布和无 Docker 部署指南
```

## 本地运行

### Docker Compose

需要 Docker Desktop 和至少 2 GB 可用内存：

```powershell
docker compose up --build
```

启动后访问：

- 前端：http://localhost:3000
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

停止服务：

```powershell
docker compose down
```

### 不使用 Docker

后端需要 Python 3.11 或更高版本：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[ai,dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

另开终端启动前端。Node.js 要求 `>=22.13.0`，推荐 Node.js 24：

```powershell
cd frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 3000
```

然后访问 http://127.0.0.1:3000。开发服务器会自动将 `/api/` 请求代理到
`http://127.0.0.1:8000`，因此不需要单独配置 CORS。后端使用其他端口时，先设置
`NICOKARA_DEV_API_ORIGIN`：

```powershell
$env:NICOKARA_DEV_API_ORIGIN = "http://127.0.0.1:9000"
```

本地直接运行时还需安装 FFmpeg，并保证 `ffmpeg` 可从 `PATH` 调用。首次转录会下载 faster-whisper 模型。

## 服务器部署与更新

推荐生产结构：

```text
/data/nicokara/
|-- releases/          每次发布一个独立版本目录
|-- current -> releases/{release-id}
`-- shared/
    |-- data/          SQLite 数据
    |-- storage/jobs/  上传和生成结果
    |-- models/        Whisper 与 MDX 模型
    `-- nicokara.env   生产环境配置
```

更新已经运行的服务器时：

1. 在本地拉取或确认需要发布的提交。
2. 使用相对 API 地址 `NEXT_PUBLIC_API_URL=/api/v1` 构建 Linux 前端产物。
3. 按部署指南生成应用发布包并计算 SHA-256。
4. 将发布包上传到服务器 `/data/`。
5. 解压到新的 `/data/nicokara/releases/{release-id}/`。
6. 安装后端依赖，切换 `/data/nicokara/current` 软链接。
7. 重启前后端服务，并检查健康接口、首页和完整生成流程。

模型、SQLite、上传文件和任务结果位于 `shared/`，发布新版本时不应覆盖。完整命令和回滚方法见 [DEPLOYMENT_LOCAL_BUILD.md](./DEPLOYMENT_LOCAL_BUILD.md)。

应用包、Whisper 模型包和 MDX 模型包分开生成。后续更新应用时不需要重复上传模型。
完整打包命令和 SHA-256 校验流程见
[本地构建与无 Docker 部署指南](./DEPLOYMENT_LOCAL_BUILD.md)。

## 无 Docker 生产部署

推荐使用 Ubuntu 24.04、Nginx 和 systemd，部署到 `/data/nicokara`：

```text
浏览器
├── /        → Nginx → 前端 127.0.0.1:3000
└── /api/    → Nginx → 后端 127.0.0.1:8000
                         ├── SQLite
                         ├── storage/jobs
                         └── Whisper/MDX 本地模型
```

### 1. 安装服务器依赖

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
```

另外安装 Node.js 24，并确认版本：

```bash
node --version
python3 --version
ffmpeg -version
```

### 2. 准备持久化目录

```bash
sudo mkdir -p \
  /data/nicokara/releases \
  /data/nicokara/shared/data \
  /data/nicokara/shared/storage/jobs \
  /data/nicokara/shared/models
```

每次发布解压到新的 `releases/{发布编号}/`，并让
`/data/nicokara/current` 指向当前版本。SQLite、任务文件和模型放在
`shared/`，发布新版本时不会被覆盖。

### 3. 安装后端生产依赖

```bash
cd "/data/nicokara/current/backend"
python3 -m venv ".venv"
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -e ".[ai]"
```

创建 `/data/nicokara/shared/nicokara.env`：

```ini
NICOKARA_DATA_DIR=/data/nicokara/shared/data
NICOKARA_STORAGE_DIR=/data/nicokara/shared/storage/jobs
NICOKARA_ALLOWED_ORIGINS=http://SERVER_IP
NICOKARA_TRUSTED_PROXY_HOSTS=127.0.0.1,::1
NICOKARA_MAX_PENDING_JOBS=4
NICOKARA_MAX_ACTIVE_JOBS_PER_CLIENT=2
NICOKARA_PROCESSING_ENABLED=true
NICOKARA_FFMPEG_PATH=ffmpeg
NICOKARA_WHISPER_MODEL=/data/nicokara/shared/models/faster-whisper-small
NICOKARA_WHISPER_DEVICE=cpu
NICOKARA_WHISPER_COMPUTE_TYPE=int8
NICOKARA_VOCAL_REMOVAL_BACKEND=mdx
NICOKARA_VOCAL_REMOVAL_MODEL=UVR_MDXNET_KARA_2.onnx
NICOKARA_VOCAL_REMOVAL_MODEL_DIR=/data/nicokara/shared/models/audio-separator
NICOKARA_DEEPSEEK_API_KEY=
```

使用域名或 HTTPS 时，将 `NICOKARA_ALLOWED_ORIGINS` 改为浏览器实际访问地址。

### 4. 配置进程和反向代理

- 后端 systemd 运行
  `/data/nicokara/current/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`。
- 前端 systemd 运行
  `node /data/nicokara/current/frontend/server.js`，监听 `127.0.0.1:3000`。
- Nginx 对外只开放 80/443，将 `/api/` 转发到 8000，其余请求转发到 3000。
- Nginx 设置 `client_max_body_size 1024m`，并关闭 API 请求缓冲，避免大视频上传被默认限制。
- 后端保持单进程，不要增加 Uvicorn worker 数量；视频处理队列和来源并发控制仍为单进程设计。

完整的 systemd unit、Nginx 配置、发布目录切换和一键部署脚本说明见
[DEPLOYMENT_LOCAL_BUILD.md](./DEPLOYMENT_LOCAL_BUILD.md)。

### 5. 启动和验收

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nicokara-backend nicokara-frontend nginx

curl -fsS http://127.0.0.1:8000/health
curl -I http://127.0.0.1:3000/
curl -I http://SERVER_IP/
```

最后通过网页上传一个短 MP4 和歌词，完整验证上传、日语识别、歌词对齐、字幕生成、视频烧录、预览和下载。

## 关键配置

后端环境变量使用 `NICOKARA_` 前缀：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NICOKARA_STORAGE_DIR` | `../storage/jobs` | 任务文件目录 |
| `NICOKARA_MAX_VIDEO_BYTES` | `1073741824` | MP4 最大字节数 |
| `NICOKARA_MAX_LYRICS_BYTES` | `1048576` | 歌词最大字节数 |
| `NICOKARA_MAX_PENDING_JOBS` | `4` | 本地后台队列最大等待任务数 |
| `NICOKARA_MAX_ACTIVE_JOBS_PER_CLIENT` | `2` | 单个来源同时等待或处理的最大任务数 |
| `NICOKARA_CLEANUP_ENABLED` | `true` | 是否自动清理过期终态任务 |
| `NICOKARA_JOB_RETENTION_HOURS` | `24` | 成功或失败任务的保留小时数 |
| `NICOKARA_CLEANUP_INTERVAL_SECONDS` | `3600` | 过期任务扫描间隔秒数 |
| `NICOKARA_ALLOWED_ORIGINS` | `http://localhost:3000` | 允许的前端来源，逗号分隔 |
| `NICOKARA_TRUSTED_PROXY_HOSTS` | `127.0.0.1,::1` | 可信反向代理地址或网段，逗号分隔 |
| `NICOKARA_PROCESSING_ENABLED` | `true` | 是否自动执行本地转录任务 |
| `NICOKARA_FFMPEG_PATH` | `ffmpeg` | FFmpeg 可执行文件路径 |
| `NICOKARA_FFMPEG_TIMEOUT_SECONDS` | `900` | 音频提取超时秒数 |
| `NICOKARA_VIDEO_RENDER_TIMEOUT_SECONDS` | `7200` | 最终视频渲染超时秒数 |
| `NICOKARA_VIDEO_RENDER_PRESET` | `veryfast` | x264 编码速度预设 |
| `NICOKARA_VIDEO_RENDER_CRF` | `20` | x264 画质参数，越低画质越高 |
| `NICOKARA_WHISPER_MODEL` | `small` | faster-whisper 模型名称或本地路径 |
| `NICOKARA_WHISPER_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `NICOKARA_VOCAL_REMOVAL_BACKEND` | `mdx` | 人声分离后端 |
| `NICOKARA_DEEPSEEK_API_KEY` | 空 | DeepSeek Key；为空时使用本地歌词处理 |

密钥只应保存在本地 `.env` 或服务器 `/data/nicokara/shared/nicokara.env` 中，不要提交到 Git 仓库。

## 测试

当前测试基线为后端 100 项、前端 8 个测试文件共 34 项；前端覆盖 API 错误解析、服务器错误反馈、
本地 API 代理、任务阶段、排队信息、任务取消、轮询退避和界面文案。后端测试需要先安装
`.[ai,dev]` 依赖。

```powershell
cd backend
python -m pytest

cd ..\frontend
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

## 当前边界

- 队列和来源并发控制目前是单进程实现；多后端实例需要引入 Redis/Celery 等共享服务。
- 当前前端要求用户提供歌词，无歌词模式尚未接入前端流程。
- 当前没有用户账号和任务权限隔离，公开部署前应限制访问范围并启用 HTTPS。
- 后端应保持单进程，避免 SQLite、内存队列和来源并发状态不一致。
- 原始 FFmpeg、模型路径及外部 API 错误只应写入服务器日志，不直接返回给用户。

## 实现细节

歌词文本和歌词文件只能选择一种。前端在当前“有歌词模式”下要求至少提供一种歌词；后端保留歌词可选能力，方便未来接入无歌词模式。

上传后任务会依次经过：

```text
UPLOADED / UPLOAD_COMPLETE
→ PROCESSING / EXTRACTING_AUDIO
→ PROCESSING / REMOVING_VOCALS       # 仅 OFF VOCAL
→ PROCESSING / TRANSCRIBING
→ PROCESSING / PROCESSING_LYRICS
→ PROCESSING / ALIGNING
→ PROCESSING / GENERATING_SUBTITLE
→ PROCESSING / RENDERING_VIDEO
→ COMPLETED / VIDEO_RENDERING_COMPLETE
```

失败状态为 `FAILED`。错误码会区分人声分离、音频提取、Whisper 转录、歌词处理、
时间轴对齐、字幕生成、视频合成和服务重启中断。后端只返回可公开的阶段信息，前端再
根据错误类型展示原因、解决方案、是否可重试、HTTP 状态码和任务 ID。

前端不会直接显示 `REMOVING_VOCALS`、`RENDERING_VIDEO` 等内部代码，而是显示
“分离人声”“识别歌声”“处理歌词”“对齐时间”“生成字幕”“合成视频”等用户可读进度。

成功任务会生成：

```text
storage/jobs/{job_id}/
├── input.mp4
├── lyrics.txt
├── audio.wav
├── audio_instrumental.wav      # 仅 OFF VOCAL
├── transcript.json
├── lyrics_processed.json
├── timeline.json
├── lyrics.ass
└── final_karaoke.mp4
```

转录结果接口：

```text
GET /api/v1/jobs/{job_id}/transcript
GET /api/v1/jobs/{job_id}/lyrics
GET /api/v1/jobs/{job_id}/timeline
GET /api/v1/jobs/{job_id}/subtitle
GET /api/v1/jobs/{job_id}/result
GET /api/v1/jobs/{job_id}/download
```

`timeline.json` 按歌词行、Ruby token 和 Mora 三层保存 `start_ms`、`end_ms`、匹配状态与置信度。Whisper 漏掉的 Mora 会在前后时间锚点之间插值，并在文档中写入 `partial_alignment` 警告。

`lyrics.ass` 使用 UTF-8 BOM 保存。主歌词采用 `Karaoke` 样式与逐字符 `\kf` 标签；含汉字 token 的读音通过独立 `Ruby` 图层定位在歌词上方。默认画布为 1920×1080，字体为 `Noto Sans CJK JP`。

`/result` 以内联 `video/mp4` 响应支持浏览器 Range 请求，用于结果页预览；`/download` 以附件方式下载 `final_karaoke.mp4`。

## DeepSeek 与本地降级

不配置 API Key 时，歌词不会离开本机，系统使用 pykakasi 生成读音。辞典式读音无法可靠判断所有歌词上下文和多音字，因此结果包含 `local_reading_may_be_inaccurate` 警告。

如需使用 DeepSeek，可在根目录创建 `.env`：

```text
DEEPSEEK_API_KEY=
```

使用 DeepSeek 时只有歌词文本会发送到 API，音频和视频仍在本地处理。如果 DeepSeek 请求失败或返回的 token 无法还原歌词，系统会自动回退到本地处理，并在结果中记录 `deepseek_fallback` 警告。

## Phase 8 运行保护

- SQLite 使用 WAL、5 秒 busy timeout 和任务状态索引，降低上传、轮询和后台处理之间的锁竞争。
- 服务启动时，意外中断的 `PROCESSING` 任务会标记为 `FAILED / SERVICE_RESTARTED`；全部尚未开始的 `UPLOADED` 任务会按原顺序逐步恢复入队，不受内存队列瞬时容量影响。
- 默认每小时自动扫描一次，并删除超过 24 小时的成功或失败任务目录及数据库记录。处理中任务不会被删除。
- 本地队列默认最多等待 4 个任务；上传写盘前会原子预留队列容量，队列满时返回 `503` 和 `Retry-After`。
- 默认每个来源最多同时拥有 2 个等待或处理中的任务，避免单个用户占满整个队列。
- 已完成的任务不计入次数限制；同一来源可以继续创建新任务，不设置每小时上传次数上限。
- Nginx 转发地址只在请求来自可信代理时使用，并从代理链右侧识别真实来源，防止伪造请求头绕过来源并发控制。
- 任务接口返回排队位置和等待总数；等待任务可立即退出队列，处理中的任务可取消后续生成步骤；前端在排队、后台标签页或连续请求失败时自动降低轮询频率。
- 下载接口会验证数据库中的文件路径必须位于对应任务目录，防止读取任务目录外的文件。
- 对外任务错误只返回阶段化提示，原始 FFmpeg、模型路径和 API 错误仅写入服务日志。
- 前端将公开错误转换为服务器场景的详细反馈，并为常见 413、429、502、503、504、
  任务过期和各处理阶段失败提供对应解决方案。
- API 响应包含 `nosniff`、禁止 iframe、严格 Referrer Policy 和 Permissions Policy。
- Docker Compose 启用自动重启、init、禁止提权与 10 MB × 3 日志轮转。

## 当前边界与后续工作

- 当前视频处理队列和来源并发控制是单进程实现。部署多个后端实例前，需要将任务队列及并发预留迁移到
  Redis/Celery 等共享服务。
- 当前前端要求用户提供歌词；后端保留歌词可选能力，但无歌词模式尚未接入前端流程。
- 当前没有用户账号和任务权限隔离，不适合直接作为允许任意用户上传文件的公共服务。
- 公开部署应启用 HTTPS、限制访问范围，并更换任何已经暴露过的 API Key。
- 本地代码修改不会自动同步到服务器；每次发布仍需重新构建前端、打包发布目录、上传并
  切换 `/data/nicokara/current`，完整步骤见 [DEPLOYMENT_LOCAL_BUILD.md](./DEPLOYMENT_LOCAL_BUILD.md)。

## 进一步文档

- [本地构建与无 Docker 部署指南](./DEPLOYMENT_LOCAL_BUILD.md)
