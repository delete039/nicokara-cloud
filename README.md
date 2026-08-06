# ニコカラ自动生成器 Cloud

## 项目简介

ニコカラ自动生成器 Cloud 面向没有字幕制作和视频剪辑经验的用户。用户只需提供原始 MV 和逐行歌词，系统即可完成音频处理、日语歌声识别、歌词时间轴对齐、汉字假名注音、Karaoke 逐字变色字幕以及视频导出。

### 项目定位

本项目以“浏览器完成、尽量少上传、无需学习专业软件”为目标：

- 无需掌握字幕打轴、ASS 特效或视频剪辑。
- 支持 `ON VOCAL` 原人声和 `OFF VOCAL` 伴奏两种输出。
- 对符合条件的素材，优先在浏览器提取音频，只将音频和歌词发送到后端。
- 使用 Kirakara 逻辑预览、检查注音、调整时间轴和渲染双行ニコカラ字幕。
- 浏览器具备本地导出能力时直接在本机生成视频；能力不足时自动改用云端渲染。
- 提供上传排队、处理排队、任务取消、异常恢复和管理员监控，适合多人访问。

当前版本仍处于 Alpha 阶段。建议先使用短视频验证浏览器兼容性和生成效果，再处理正式素材。

## 更新日志

### v0.3.0-alpha.2 - 2026-08-06

- 增加可配置的首次访问公告，公告 JSON 可在部署后直接更新或关闭。
- 后台任务默认使用 4 个 worker，并支持通过 TOML 配置热调整 worker 数量。
- 浏览器预览、本地导出和云端渲染统一采用 Kirakara 双行交替字幕逻辑。
- 增加可视化时间轴调整、整体偏移、逐词注音检查和字幕样式设置。
- 增加 WebCodecs 本地 MP4 导出；支持时只显示本地导出，不支持时只显示云端渲染。
- `OFF VOCAL` 支持下载云端 UVR 生成的伴奏，并在浏览器导出时替换原音轨。

### v0.3.0-alpha.1 - 2026-08-06

- 增加电脑和手机浏览器能力检测，以及 `LOCAL`、`AUDIO_ONLY`、`REMOTE_VIDEO` 自动选路。
- 对 300 MB 以内素材优先在浏览器提取音频，避免上传完整视频。
- 增加浏览器音频任务接口、模型清单与缓存接口、完全本地任务状态机。
- 增加 Kirakara DOM 实时预览和本地媒体会话恢复能力。

### v0.2.0 - 2026-08-05

- 增加受管理员令牌保护的 `/admin` 监控页面。
- 展示上传队列、处理队列、worker 心跳、系统资源和失败任务。
- 支持管理员取消任务、重新入队和操作审计。

### v0.1.1 - 2026-08-04

- 增加大文件上传排队、排队位置和退出排队。
- 视频改为 8 MiB 分片上传，单片失败最多重试 3 次。
- 增加任务幂等查询，减少 Cloudflare 524 或网络中断造成的重复提交。

### v0.1.0

- 完成视频与歌词上传、歌声识别、歌词处理、时间轴对齐、ASS 字幕和视频渲染的基础闭环。
- 支持 `ON VOCAL`、`OFF VOCAL`、任务状态查询和结果下载。

完整记录见 [CHANGELOG.md](./CHANGELOG.md)。

## 项目基本架构

### 处理流程

```text
用户选择 MP4 和逐行歌词
        |
        v
浏览器检测设备、素材和编码能力
        |
        +-- 浏览器优先路径：本地提取音频 -> 上传音频和歌词
        |
        `-- 兼容回退路径：分片上传完整视频和歌词
                              |
                              v
                 FastAPI 后端任务队列
                              |
          UVR 人声分离 / 歌声识别 / 歌词处理
                 / 时间轴对齐 / Ruby 注音
                              |
                              v
                  Kirakara 字幕时间轴
                              |
          +-------------------+-------------------+
          |                                       |
          v                                       v
浏览器预览与本地导出                    云端 FFmpeg 渲染后下载
```

### 技术组成

| 模块 | 技术与职责 |
|---|---|
| 前端 | React、TypeScript、vinext、Tailwind CSS；负责上传、排队、进度、预览和本地导出 |
| 浏览器媒体 | Mediabunny、DOM、Canvas、WebCodecs；负责本地音频提取、Kirakara DOM 预览和 Canvas MP4 导出 |
| 后端 | FastAPI、SQLite；负责任务、队列、上传票据、管理监控和产物接口 |
| 音频与识别 | FFmpeg、audio-separator/UVR、faster-whisper、pykakasi |
| 字幕与视频 | Mora 时间轴、Ruby 注音、Kirakara 双行布局、FFmpeg/libass |
| 数据 | `storage/jobs/{job_id}` 保存每个任务的输入、时间轴、字幕和结果 |

### 目录结构

```text
nicokara-cloud/
|-- frontend/                 前端页面、浏览器媒体处理和测试
|-- backend/                  FastAPI、任务流程、字幕处理和测试
|-- storage/jobs/             本地任务文件，不提交到 Git
|-- release/                  服务器部署与恢复脚本
|-- docker-compose.yml        本地完整运行配置
|-- docker-compose.dev.yml    修改代码时使用的开发配置
|-- .env.example              可选环境变量示例
`-- CHANGELOG.md              完整更新日志
```

Kirakara 渲染逻辑的来源和许可信息见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。

本地默认访问关系：

```text
浏览器 -> http://localhost:3000 -> 前端
浏览器 -> http://localhost:8000 -> FastAPI
前端 /api 请求 -> FastAPI -> SQLite + storage/jobs + 本地模型缓存
```

## 本地部署 0 基础教程

以下步骤以 Windows 10/11 为例。推荐使用 Docker Desktop，不需要单独安装 Python、Node.js 或 FFmpeg。

### 第 1 步：确认电脑条件

- 64 位 Windows 10/11。
- 至少 8 GB 内存，推荐 16 GB。
- 至少预留 20 GB 磁盘空间，用于 Docker 镜像、Python 依赖和模型缓存。
- 在 BIOS/UEFI 中启用 CPU 虚拟化。任务管理器的“性能 -> CPU”页面应显示“虚拟化：已启用”。

### 第 2 步：安装 Git

1. 打开 [Git for Windows 官方下载页](https://git-scm.com/install/windows)。
2. 下载并安装，安装过程保持默认选项即可。
3. 安装完成后重新打开 PowerShell，执行：

```powershell
git --version
```

能看到版本号说明安装成功。

### 第 3 步：安装 Docker Desktop

1. 打开 [Docker Desktop Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)。
2. 下载并安装 Docker Desktop，安装时使用 WSL 2 后端。
3. 如果安装程序提示缺少 WSL，以管理员身份打开 PowerShell并执行：

```powershell
wsl --install
wsl --update
```

4. 按提示重启电脑，然后启动 Docker Desktop。
5. 等待 Docker Desktop 显示 Engine running，再执行：

```powershell
docker --version
docker compose version
```

两条命令都能显示版本号，说明 Docker 已经可用。

### 第 4 步：下载项目

在希望保存项目的位置打开 PowerShell。例如保存到 `D:\study`：

```powershell
cd D:\study
git clone https://github.com/delete039/nicokara-cloud.git
cd nicokara-cloud
```

如果已经下载过项目，进入项目目录后更新即可：

```powershell
cd D:\study\nicokara-cloud
git pull
```

### 第 5 步：启动项目

确认 Docker Desktop 正在运行，然后在项目根目录执行：

```powershell
docker compose up --build
```

首次启动需要下载基础镜像、Python 依赖和前端依赖，通常会明显慢于后续启动。只要终端仍在持续输出下载或构建信息，就不要关闭窗口。

看到前后端均已启动后，打开浏览器访问：

- 项目首页：<http://localhost:3000>
- 后端接口文档：<http://localhost:8000/docs>
- 后端健康检查：<http://localhost:8000/health>

后台任务默认启动 4 个 worker。运行时可修改
`backend/config/workers.toml` 中的 `processing.worker_count`，后端会在 1 秒内热加载，
无需重启容器。全站公告位于 `frontend/public/announcement.json`；修改内容后刷新页面
即可生效，设置 `enabled` 为 `false` 可关闭公告。

### 第 6 步：完成第一次测试

1. 准备一个较短的 MP4 视频，建议首次测试控制在 1 分钟以内。
2. 准备 UTF-8 编码的 TXT 歌词，每句歌词单独成行。
3. 打开首页，选择视频、歌词和 `ON VOCAL`。
4. 提交后观察上传及处理进度。
5. 任务完成后检查注音、时间轴和字幕预览，再尝试导出。

首次执行歌声识别或 `OFF VOCAL` 时可能继续下载模型，因此第一次任务会比较慢。

### 第 7 步：停止和再次启动

在运行日志窗口按 `Ctrl + C` 停止服务，然后执行：

```powershell
docker compose down
```

下次启动通常不需要重新构建：

```powershell
docker compose up
```

修改了 `Dockerfile`、`backend/pyproject.toml` 或 `frontend/package-lock.json` 后，再执行：

```powershell
docker compose up --build
```

### 第 8 步：常见问题

| 现象 | 处理方法 |
|---|---|
| `docker` 不是可识别的命令 | 启动 Docker Desktop，并重新打开 PowerShell |
| 提示 WSL 或虚拟化不可用 | 执行 `wsl --update`，并确认 BIOS/UEFI 已启用虚拟化 |
| 端口 3000 或 8000 被占用 | 关闭占用端口的旧程序，或先执行 `docker compose down` |
| 构建期间下载很慢 | 保持网络连接并重试 `docker compose up --build`；Docker 会复用已经完成的缓存 |
| 页面打不开 | 执行 `docker compose ps`，确认 `frontend` 和 `backend` 状态正常 |
| 后端显示不健康 | 执行 `docker compose logs --tail 100 backend` 查看最后 100 行日志 |
| 第一次任务长时间停留在模型阶段 | 首次任务可能正在下载 Whisper 或 UVR 模型，查看后端日志确认下载仍在继续 |

查看全部服务日志：

```powershell
docker compose logs -f
```

只查看后端日志：

```powershell
docker compose logs -f backend
```

彻底停止容器但保留任务文件和模型缓存：

```powershell
docker compose down
```

不要随意添加 `-v`。`docker compose down -v` 会删除 Docker 数据卷中的数据库和模型缓存，下次需要重新下载和初始化。
