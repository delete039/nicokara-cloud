# ニコカラ自动生成器 Cloud

在浏览器中上传 MV 和日语歌词，自动完成歌声识别、假名注音、Mora 时间轴、Kirakara 逐字字幕以及 ON VOCAL / OFF VOCAL 视频导出。

> 当前版本：`v0.3.0-alpha.3`。项目仍处于 Alpha 阶段，建议先用短视频验证浏览器兼容性、注音和时间轴效果。

## 项目能做什么

- 选择常见视频格式（MP4、MOV、M4V、MKV、WebM、AVI、WMV、FLV、MPEG、TS、3GP、OGV），粘贴歌词或上传 UTF-8 `TXT` / `LRC` 文件。
- 服务器先整理歌词读音，在 `READING_REVIEW_REQUIRED` 阶段等待用户确认或修正假名。
- 自动生成 Mora 级时间轴、Ruby 假名和 Kirakara 双行逐字高亮字幕。
- 浏览器支持时优先提取音频，只上传音频和歌词；不支持时改用可恢复的完整视频分片上传。
- 在结果页预览视频，编辑行、词和 Mora 时间，调整字幕样式，并自动保存草稿。
- 每个任务分别提供 `ON VOCAL` 和 `OFF VOCAL` 的本地导出与云端导出。
- 支持失败重试、排队取消、断点续传、提交幂等恢复和管理员队列监控。

## 先了解这些边界

- 视频入口接受常见容器并要求视频包含可正常读取的音轨，默认上限为 `1 GiB`；歌词上限为 `1 MiB`。最终导出统一为 MP4。
- 浏览器音频优先路径的本地媒体阈值约为 `300 MiB`。超过该阈值仍可提交，但会上传完整视频。
- 服务端音频入口默认上限为 `256 MiB`；浏览器提取的音频使用 8 MiB 分片上传。
- 浏览器的 `LOCAL` 完整本地推理接口尚未完成真实 UVR/CTC 模型适配，当前不要把它当作可用的离线推理方案。
- `AUDIO_ONLY` 只是不上传原视频，识别、注音和对齐仍由服务器完成；服务器生成字幕产物后停止，不会自动合成视频。
- 本地视频导出依赖 WebCodecs、H.264 和 AAC。最新版桌面 Chrome 或 Edge 最稳定；Safari/iOS 能力不足时请使用云端渲染。
- 第一次任务可能下载 Whisper、UVR、MMS_FA 等模型，CPU 环境会明显较慢。Yohane 源码和模型不随仓库提供，缺少时会自动降级。

## 快速开始

### Docker Compose

准备 Docker Desktop 和 Compose 后，在项目根目录执行：

~~~bash
git clone https://github.com/delete039/nicokara-cloud.git
cd nicokara-cloud
docker compose up --build
~~~

启动完成后访问：

| 服务 | 地址 |
| --- | --- |
| 前端 | <http://localhost:3000> |
| FastAPI OpenAPI | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| 健康检查 | <http://localhost:8000/health> |

首次构建和首次任务会下载依赖及模型，请保留模型缓存卷。普通停止使用：

~~~bash
docker compose down
~~~

不要把 `docker compose down -v` 当作普通停止命令，它会删除 SQLite 和模型缓存卷。

### GPU 对齐

宿主机已配置 Docker GPU 支持时，可以使用 CUDA 版 Torch 和 FA-Kara：

~~~bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
~~~

该覆盖文件将 `NICOKARA_FA_KARA_DEVICE` 设为 `cuda`，并要求可用的 NVIDIA GPU。没有 GPU 时直接使用默认 CPU 配置即可。

### 开发热更新

开发配置会把源代码挂载到容器，并启用前后端热更新：

~~~bash
docker compose -f docker-compose.dev.yml up --build
~~~

代码修改后通常不需要重新构建；修改依赖文件、Dockerfile 或锁文件后再加上 `--build`。

## 使用流程

### 提交素材

1. 选择一个常见格式的视频，确保视频包含可播放的音轨。
2. 粘贴歌词，或选择一个 UTF-8 的 `TXT` / `LRC` 文件。通常每句歌词单独一行。
3. 如需继续编辑已有结果，可额外导入本站导出的调整后注音 JSON、Mora 时间轴 JSON 或 ASS 字幕。最多导入 3 个文件，每个不超过 4 MiB。
4. 提交任务并保持页面打开，直到进入任务状态页。上传队列会显示位置，上传可以暂停、取消和恢复。

导入 ASS 会强制使用完整视频上传并进入云端渲染；只导入注音或时间轴数据时，仍可能使用音频优先路径。

首页固定以 `ON VOCAL` 和 `auto` 流程创建任务。视频完成后，在结果页分别准备 ON VOCAL 和 OFF VOCAL 版本，不需要重复识别和对齐。

### 处理和确认

服务器会先处理歌词读音。遇到 `READING_REVIEW_REQUIRED` 时，逐词确认或修改假名后再继续时间轴对齐。对齐主流程会优先使用可用的 Yohane 资源，随后使用 FA-Kara/TorchAudio `MMS_FA`，失败或不可用时回退到内置 Whisper 时间轴，并在任务产物和管理员日志中记录实际引擎。

任务失败可以重新入队，排队或处理中的任务可以取消。已完成任务重新打开注音审核后，时间轴、字幕和视频会按新的读音重新生成。

### 预览和编辑

有时间轴的任务可以在浏览器中：

- 播放逐字高亮字幕，按句定位、循环试听和调整播放速度。
- 修改行、词和 Mora 的起止时间，使用撤销和重做。
- 调整字体、字号、注音大小与偏移、颜色、描边、阴影以及上下行位置。
- 将时间轴和注音修改自动保存到云端，同时保留浏览器草稿。

`AUDIO_ONLY` 任务的原视频只保存在当前浏览器内存中。刷新或重新打开结果页后，需要重新选择同一个视频文件才能继续预览和本地导出。

### 导出结果

每个任务都有独立的 ON VOCAL 和 OFF VOCAL 导出区域：

| 方式 | ON VOCAL | OFF VOCAL |
| --- | --- | --- |
| 本地导出 | 复用当前设备上的原视频和原音轨，不重新上传视频 | 先从服务器准备 UVR 伴奏，再由浏览器替换音轨并导出 |
| 云端导出 | 重新上传原视频，服务器按当前时间轴和样式嵌字编码 | 重新上传原视频并使用服务器生成的伴奏编码 |

本地导出使用 Mediabunny、Canvas 和 WebCodecs，桌面目标为 `1080p/30`，移动端目标为 `720p/30`。浏览器不支持 H.264 或 AAC 时仍可预览，但应改用云端渲染。云端渲染只重新嵌字和编码，不会重新识别或对齐歌词。

完整视频任务可以下载原始识别数据、处理后歌词、时间轴、ASS 字幕和 Kirakara `.krl` 工程；有时间轴的任务都可以单独导出调整后的注音、时间轴和 ASS。

## 浏览器自动选路

~~~text
常见视频格式 + 歌词
   |
   v
浏览器能力检查
   |
   +-- AUDIO_ONLY：Mediabunny 提取 M4A，按 8 MiB 分片上传音频和歌词
   |
   +-- REMOTE_VIDEO：按 8 MiB 分片上传完整视频和歌词
          |
          v
     后端队列和处理流水线
          |
          v
   注音确认 -> 对齐 -> Mora / ASS / KRL
          |
          +-- 浏览器本地预览和导出
          +-- 云端 Kirakara 嵌字和 FFmpeg 编码
~~~

音频和视频分片都支持断点续传，单片网络失败最多自动重试 3 次。上传使用 `client_submission_id` 幂等；连接在任务创建后中断时，页面会尝试找回原任务，而不是重复创建。
音频上传开始后如果服务器拒绝，不会再次自动上传完整视频；只有浏览器提取音频失败时才会回退到完整视频路径。

## 处理流水线

实际步骤会根据输入模式和对齐器选择分支。高精度直对齐可以跳过 Whisper；OFF VOCAL 或需要人声 stem 时才会运行 UVR：

~~~text
FFmpeg 音频处理
   |
   +-- 按需：MDX / UVR 分离人声与伴奏
   +-- 按需：faster-whisper 歌声识别
   |
   v
Janome / pykakasi / alkana 日语读音处理
   -> Yohane / FA-Kara MMS_FA / Whisper 回退对齐
   -> Mora 时间轴与 Kirakara ASS
   -> 浏览器本地导出或 FFmpeg 云端渲染
~~~

默认后端使用 `faster-whisper`、`audio-separator` 的 `UVR_MDXNET_KARA_2.onnx`、TorchAudio `MMS_FA`、FFmpeg、Janome、pykakasi 和 alkana。配置 `DEEPSEEK_API_KEY`（Docker Compose）或 `NICOKARA_DEEPSEEK_API_KEY`（直接运行后端）后，可以启用 DeepSeek 读音复核；不配置时使用本地读音处理器。

## 配置

后端设置使用 `NICOKARA_` 前缀，完整变量和默认值见 [.env.example](./.env.example)。Docker Compose 还会把根目录 `.env` 中的部分变量映射到容器。

常用配置如下：

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `NICOKARA_ADMIN_TOKEN` | 空 | 管理员页面和管理 API 的 Bearer Token；为空时管理接口不可用 |
| `NICOKARA_FA_KARA_ENABLED` | `true` | 启用 FA-Kara/MMS_FA 主对齐器 |
| `NICOKARA_FA_KARA_DEVICE` | `cpu`（Compose）/ `auto`（直接运行） | `auto`、`cpu` 或 `cuda` |
| `NICOKARA_FA_KARA_TIMEOUT_SECONDS` | `600` | MMS_FA 单次对齐超时 |
| `NICOKARA_YOHANE_ENABLED` | `true` | Yohane 资源存在时允许优先使用 |
| `NICOKARA_JOB_RETENTION_HOURS` | `24` | 任务文件和结果的默认保留时间 |
| `NICOKARA_LOG_LEVEL` | `INFO` | 控制台日志级别 |
| `NICOKARA_EVENT_LOG_LEVEL` | `INFO` | 管理事件日志级别 |

Yohane 不随仓库提供。Docker Compose 默认只读挂载：

~~~text
./models/yohane/FA-Kara  -> /app/models/yohane/FA-Kara
./models/yohane/model    -> /app/models/yohane/model
~~~

可以通过 `NICOKARA_YOHANE_SOURCE_HOST_DIR` 和 `NICOKARA_YOHANE_MODEL_HOST_DIR` 更换宿主机目录。缺少必要文件、模型加载失败或对齐超时时，会自动使用备用引擎。

worker 数量在 [backend/config/workers.toml](./backend/config/workers.toml) 中配置：

~~~toml
[processing]
worker_count = 3
reload_interval_seconds = 1.0
~~~

默认资源保护包括：每客户端最多 2 个活动任务、最多 4 个内存等待任务、最多 32 个活动任务、最多 32 个上传会话、默认 1 个并行上传槽，并要求至少保留 2 GiB 空闲磁盘。

## API 和管理员入口

API 默认前缀为 `/api/v1`，运行后可直接打开 [OpenAPI 文档](http://localhost:8000/docs) 查看请求和响应模式。

| 能力 | 入口 |
| --- | --- |
| 上传队列和可恢复视频分片 | `/upload-tickets` |
| 任务创建、状态、取消和重试 | `/jobs`、`/jobs/{job_id}` |
| 注音、时间轴、ASS、KRL 和视频产物 | `/jobs/{job_id}/readings`、`timeline`、`subtitle`、`exports/*`、`download` |
| 浏览器音频优先上传 | `/browser/audio-uploads`、`/browser/audio-jobs` |
| 已有任务的云端渲染 | `/browser/jobs/{job_id}/cloud-render` |
| 页面访问统计 | `/analytics/pageview` |
| 管理监控、日志和任务时间线 | `/admin/overview`、`/admin/queue-health`、`/admin/logs`、`/admin/jobs/{job_id}/timeline` |

管理员 API 使用：

~~~bash
curl -H "Authorization: Bearer $NICOKARA_ADMIN_TOKEN" http://localhost:8000/api/v1/admin/overview
~~~

管理页面位于 <http://localhost:3000/admin>，结构化日志页面位于 <http://localhost:3000/admin/logs>。日志会记录队列、worker、处理阶段、降级和失败原因，并对歌词、凭据、Token、Cookie、签名 URL 和完整本地路径进行脱敏。

## 直接开发运行

Docker 是默认开发方式。需要直接运行时，要求 Python `>=3.11`、Node.js `>=22.13.0` 和可从 `PATH` 调用的 FFmpeg。

### 后端

~~~bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[ai,dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
~~~

PowerShell 激活虚拟环境时使用：

~~~powershell
./.venv/Scripts/Activate.ps1
~~~

### 前端

在另一个终端执行：

~~~bash
cd frontend
npm ci
NEXT_PUBLIC_API_URL=/api/v1 npm run dev -- --hostname 0.0.0.0 --port 3000
~~~

开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。需要其他后端地址时设置 `NICOKARA_DEV_API_ORIGIN`。开发和 standalone 构建会发送 COOP/COEP 响应头，以支持跨源隔离相关的浏览器媒体能力。

## 测试和代码检查

~~~bash
cd backend
python -m pytest

cd ../frontend
npm test
npm run lint
npm run typecheck
npm run build
~~~

前端 `npm run build` 会先执行类型检查，再生成 standalone 构建产物。

## 数据目录和项目结构

Docker Compose 默认把以下内容持久化：

| 内容 | 容器位置 | 宿主机或卷 |
| --- | --- | --- |
| SQLite | `/app/backend/data/nicokara.sqlite3` | `backend-data` 卷 |
| 任务输入、中间文件和结果 | `/app/storage/jobs` | `./storage/jobs` |
| Whisper / Hugging Face 缓存 | `/root/.cache/huggingface` | `whisper-cache` 卷 |
| MMS / Torch 缓存 | `/root/.cache/torch` | `mms-model-cache` 卷 |
| UVR 模型缓存 | `/app/models/audio-separator` | `mdx-model-cache` 卷 |

~~~text
nicokara-cloud/
|-- frontend/                 前端页面、浏览器媒体处理、预览和测试
|-- backend/                  FastAPI、任务队列、对齐、字幕和测试
|-- backend/config/           worker 配置
|-- storage/jobs/             任务文件和视频结果，不提交到 Git
|-- models/                   本地模型目录，不提交到 Git
|-- release/                  生产部署和发布包脚本
|-- docs/                     部署、架构、评测、审计和路线图文档
|-- docker-compose*.yml       生产、开发和 GPU 配置
+-- .env.example              环境变量示例
~~~

## 部署和进一步阅读

- [本地构建与无 Docker 部署](./docs/deployment/DEPLOYMENT_LOCAL_BUILD.md)：生产构建、发布包、Nginx、systemd、升级和回滚。
- [浏览器处理契约](./docs/architecture/MOBILE_BROWSER_PROCESSING.md)：自动选路、音频分片协议、浏览器能力边界和本地导出设计。
- [对齐基准](./docs/quality/ALIGNMENT_BENCHMARK.md)：固定歌曲集的准确率、耗时和内存统计工具。
- [FA-Kara 接入审计](./docs/integrations/FA_KARA_INTEGRATION_AUDIT.md)：上游逻辑、许可、适配范围和回退策略。
- [更新日志](./CHANGELOG.md)：已经完成并验证的主要改动。
- [路线图](./docs/planning/ROADMAP.md)：尚未实现的计划。
- [第三方许可](./THIRD_PARTY_NOTICES.md) 和 [项目许可证](./LICENSE)。

## 致谢

- [Kirakara-Player](https://github.com/FMPeach/Kirakara-Player)：字幕布局、预览和浏览器渲染适配参考。
- [FA-Kara](https://github.com/moriwx/FA-Kara)：歌词发音标记、非静音处理、MMS 强制对齐和时间回映射参考。

第三方版权和许可证以 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md) 为准。
