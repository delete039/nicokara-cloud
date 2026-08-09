# 更新日志

本文件记录已经完成并经过验证的主要改动。尚未实现的计划保留在 [ROADMAP.md](./ROADMAP.md)。

## v0.3.0-alpha.3 - 2026-08-06

### 云端 UVR + FA-Kara/MMS_FA 高精度对齐

- 增加可插拔高精度对齐引擎；音频优先任务使用 FA-Kara 的罗马音 token 思路和 TorchAudio `MMS_FA` 生成 Mora 时间戳。
- UVR 单次推理同时保存人声与伴奏，人声供 Whisper 和 MMS_FA 使用，伴奏继续供 `OFF VOCAL` 下载。
- MMS_FA 在独立子进程运行，达到配置超时后可终止；UVR 或 MMS_FA 缺少模型、推理失败、输出不完整或超时均自动回退原 Whisper Mora 对齐器，并记录回退原因。
- `timeline.json` 增加 `alignment_engine` 和 `alignment_model`，记录任务实际使用的对齐引擎。
- 增加 `NICOKARA_FA_KARA_ENABLED`、`NICOKARA_FA_KARA_DEVICE` 和 `NICOKARA_FA_KARA_TIMEOUT_SECONDS` 配置。
- 固定使用仍支持 MMS forced-alignment API 的 TorchAudio 2.7.1，并为模型增加独立 Docker 持久化缓存。
- 后端镜像默认使用 Debian 官方 HTTPS 软件源，支持有限重试、下载缓存和可选镜像参数，避免固定地区镜像阻断部署。
- 增加固定歌曲集基准汇总工具，比较 Mora 误差、失败率、耗时和峰值内存。

## v0.3.0-alpha.2 - 2026-08-06

### 运行配置

- 增加可配置的首次访问公告，部署后可直接修改或关闭公告，无需重新构建前端。
- 后台处理默认启动 4 个 worker，并支持通过 `workers.toml` 热调整 worker 数量。

### Kirakara 双行样式修正

- 浏览器预览与导出、云端回退和完整视频任务统一改为 Kirakara 双行交替布局：第一行靠左、第二行靠右，下一句提前显示并按 Mora 逐字变色。
- 注音仅显示在汉字词组上方并按 token 宽度对齐；人工修正读音后会立即重建对应 Ruby。
- 本节替代该版本早期记录的“单行底部字幕”方案。

### Kirakara 浏览器本地成片

- 使用 Mediabunny `Conversion.process` 解码本地视频帧，并复用 Kirakara Canvas 字幕绘制器逐帧合成。
- 使用 WebCodecs H.264 编码和 fragmented MP4 顺序封装，不在内存中保留全部编码帧对象。
- 支持 Chromium File System Access 直接持续写盘；其他浏览器按分片收集 Blob 并提供下载。
- 移动端使用 720p/30、桌面端使用 1080p/30 的受限导出配置。
- 增加本地导出进度、取消、失败反馈和结果下载状态。
- `ON VOCAL` 复用本地视频原音轨；`OFF VOCAL` 新增云端 UVR 伴奏下载端点，并在浏览器导出时替换原音轨。
- 修正音频任务结果页旧说明，并解决长日文文件名造成的移动端横向溢出。
- 增加可视化歌词时间轴、逐句起止时间、整体偏移和逐词注音检查；修改结果即时用于预览与导出。
- 浏览器缺少 WebCodecs/H.264 能力时明确显示 Chrome、Edge、Android Chrome 与 Safari/iOS 兼容说明，并提供云端渲染入口。
- 增加 `/api/v1/browser/jobs/{job_id}/cloud-render`：上传原视频后复用已校正时间轴，进入仅渲染队列，不重复运行 UVR、识别或对齐。

## v0.3.0-alpha.1 - 2026-08-06

### 云端浏览器本地处理基础

- 增加电脑与手机浏览器能力快照、300 MB 本地素材规则和 `LOCAL`、`AUDIO_ONLY`、`REMOTE_VIDEO` 自动选路。
- 增加 UVR Karaoke 2 与 ReazonSpeech CTC 的浏览器模型清单、内存缓存和 Cache Storage 接口；模型权重不进入仓库。
- 增加完全本地任务状态机及 FFmpeg、UVR、CTC、字幕和渲染适配器边界。
- 增加 `/api/v1/browser/audio-jobs` 音频任务契约，视频保留在浏览器，仅上传音频和歌词；旧 `/api/v1/mobile/audio-jobs` 保留为兼容入口。
- 接入按需加载的 Mediabunny 音轨提取器，优先将 MP4 主音轨无转码封装为 M4A。
- 首页在电脑和手机浏览器中启用 300 MB 内素材的 `AUDIO_ONLY` 路径，显示本地提取和音频上传进度。
- 本地提取和音频上传支持取消；不兼容音轨自动回退完整视频上传，音频上传失败不会重复上传视频。
- 音频任务完成 Kirakara 字幕产物后停止，不主动调用服务端视频渲染器。
- 增加 Kirakara 浏览器渲染基础：将云端行、词、Mora 三级时间轴转换为本地渲染数据。
- 音频任务结果页可重新使用仍在本机的原视频，通过 Canvas 实时预览逐词变色字幕。
- 增加 WebCodecs H.264 能力检测和移动端 720p/30、桌面端 1080p/30 导出配置边界；本地 MP4 封装仍待接入。
- 开发服务器、standalone 和生产 Nginx 增加 COOP/COEP，准备启用浏览器 WASM 多线程。
- 增加云端浏览器模型量化、缓存、回退策略和接口文档。

## v0.2.0 - 2026-08-05

### 后台监控与稳定性

- 新增受 Bearer Token 保护的 `/admin` 管理员监控页面。
- 分开展示等待上传、已获上传名额、正在上传、等待处理、正在处理和失败任务。
- 展示上传排队位置、任务阶段、阶段停留时间及最近公开错误信息。
- 新增 worker 独立心跳，展示配置 worker 数、存活数量、当前任务和内存队列长度。
- 新增受保护的 `/api/v1/admin/queue-health` 探针，worker 异常时返回 HTTP 503。
- 展示 CPU 核数、系统负载、内存和任务存储所在磁盘的使用情况。
- 支持管理员取消上传票据、取消任务和将失败或取消任务重新入队。
- 新增管理员操作审计表，记录操作、目标、结果和时间。
- 任务状态变化与管理员操作写入结构化 JSON 日志，便于按任务 ID 检索。
- 管理接口不会返回来源 `client_key`、素材路径、API Key 或管理员令牌。
- 增加 `NICOKARA_ADMIN_TOKEN` 和 `NICOKARA_WORKER_HEARTBEAT_INTERVAL_SECONDS` 配置。

### 测试

- 新增管理员认证、隐私字段、队列快照、资源指标、取消、重入队、审计和健康探针测试。
- 新增 worker 心跳、忙碌任务快照和结构化任务状态日志测试。
- 新增管理页面及管理员 API 客户端测试。

## v0.1.1 - 2026-08-04

### 上传与多人调度

- 增加上传排队，默认同一时间只允许 1 个用户上传大型视频。
- 前端显示当前上传排队位置，并支持退出排队。
- 视频改为每片 8 MiB 的分片上传，单片失败最多重试 3 次。
- 增加 `client_submission_id`。遇到 Cloudflare 524 或网络中断时，可以查询任务是否已经创建，避免重复提交。
- 增加上传票据超时、上传占位超时和处理进程数量配置。
- 新增上传队列调度、并发占位等后端测试。

### 本地开发与界面

- 增加 `docker-compose.dev.yml`，改善本地开发环境启动方式。
- 优化首页布局、文件拖放、长文件名显示和上传状态提示。

## v0.1.0

- 完成 MP4 与歌词上传、日语歌声识别、歌词处理、时间轴对齐、ASS 字幕和视频渲染基础闭环。
- 支持 ON VOCAL 与 OFF VOCAL 输出、任务状态查看及结果下载。
