# 云端浏览器本地处理设计

本文记录首个云端浏览器可交付版本的边界、自动选路规则、模型预算、缓存接口、本地任务状态机和音频上传契约。电脑与手机浏览器使用同一套能力判断和回退逻辑。

## 当前边界

首个版本包含：

- 电脑与手机浏览器能力检测并自动选择处理路径。
- 本地素材大小上限 300 MB。
- UVR 与 CTC 浏览器模型清单和 Cache Storage 缓存接口。
- 完全本地任务状态机及可替换适配器。
- 只上传音频、不上传视频的后端任务契约。
- 浏览器提取 MP4 主音轨、显示进度、取消和失败回退。
- 云端时间轴转换、浏览器本地视频播放和 Kirakara Canvas 同步字幕预览。
- WebCodecs H.264 导出能力检测，以及移动端 720p/30、桌面端 1080p/30 配置边界。
- Mediabunny 逐帧 Canvas 合成、fragmented MP4 顺序封装、导出进度和取消。
- `ON VOCAL` 原音轨复用与 `OFF VOCAL` 云端 UVR 伴奏替换。
- 开发、standalone 和 Nginx 的 COOP/COEP 响应头。

当前版本不包含真实浏览器 UVR/CTC 模型权重和 ONNX 推理。模型适配器未就绪时必须自动回退到音频上传或完整视频上传，不能返回模拟处理结果。

## 自动选路

| 路径 | 选择条件 | 当前状态 |
|---|---|---|
| `LOCAL` | 素材不超过 300 MB、WebAssembly、WebGPU、跨源隔离、缓存可用、UVR/CTC 已缓存、至少 6 核/6 GB、剩余空间满足预算 | 接口完成，模型适配器待接入 |
| `AUDIO_ONLY` | 素材不超过 300 MB、浏览器文件 API 可用，但完整本地推理条件不足 | Alpha 可用；电脑与手机浏览器均可提取 M4A，只上传音频和歌词 |
| `REMOTE_VIDEO` | 素材超过 300 MB、设备能力不足、音轨不兼容或提取失败 | 正式回退路径；后续可将传输实现替换为 OSS 直传 |

本地路径的空间预算为：

```text
可用空间 >= 2 × 视频大小 + UVR/CTC 模型估算大小
```

300 MB 素材和约 150.3 MB 模型对应的最低可用空间约为 750.3 MB。阈值是首轮保护值，后续必须分别用电脑和手机浏览器基准测试调整。

## 模型量化结论

| 模型 | 原始规模 | 浏览器目标 | 决策 |
|---|---:|---:|---|
| UVR-MDX-NET Karaoke 2 | ONNX 约 50.3 MB | 50.3 MB | 首选人声分离模型 |
| ReazonSpeech Japanese wav2vec2-base-rs35kh | 96.7M 参数；FP32 约 387 MB | INT8 目标约 100 MB | 首选日语 CTC 实验模型 |
| torchaudio `MMS_FA` | 下载约 1.18 GiB | 不进入浏览器 | 在云端运行，并复用 FA-Kara 的非静音处理、CTC 强制对齐与时间回映射 |

ReazonSpeech 的 100 MB 是按 96.7M 参数 INT8 量化得到的工程估算，不是仓库中已经存在的 ONNX 文件。转换后仍需验证算子兼容、精度和实际文件大小。

FA-Kara 的核心流程是：使用 UVR/MSST 得到人声、进行歌词读音规范化和静音区间处理、通过 `MMS_FA` 生成 CTC emission，再把 token span 映射回原始时间。当前版本由服务器实际运行这条 FA-Kara/MMS 数据流；浏览器负责提取并上传音频、检查时间轴以及本地导出视频，不在手机中加载 1.18 GiB 的声学模型。

参考资料：

- [FA-Kara](https://github.com/moriwx/FA-Kara)
- [torchaudio 多语言强制对齐](https://docs.pytorch.org/audio/master/tutorials/forced_alignment_for_multilingual_data_tutorial.html)
- [torchaudio CTC 强制对齐示例](https://docs.pytorch.org/audio/main/tutorials/ctc_forced_alignment_api_tutorial.html)
- [ReazonSpeech Japanese wav2vec2-base CTC](https://huggingface.co/reazon-research/japanese-wav2vec2-base-rs35kh)
- [ONNX Runtime Web 浏览器支持矩阵](https://onnxruntime.ai/docs/get-started/with-javascript/web.html)
- [ONNX Runtime Web 环境与线程设置](https://onnxruntime.ai/docs/tutorials/web/env-flags-and-session-options.html)
- [sherpa-onnx UVR 模型大小](https://k2-fsa.github.io/sherpa/onnx/source-separation/models.html)

## 模型清单与缓存

前端清单位于 `frontend/lib/browser-models.ts`：

- `uvr-mdxnet-karaoke-2`
- `reazon-wav2vec2-base-rs35kh-int8`

两个条目当前均为 `ADAPTER_PENDING`，`downloadUrl` 为空。仓库不保存模型权重，也不会在页面加载时下载模型。

缓存接口提供：

- `get(modelId)`
- `put(modelId, blob)`
- `remove(modelId)`
- `areRequiredModelsCached(cache)`

浏览器实现使用 Cache Storage 的 `nicokara-browser-models-v1` 缓存；测试使用同一接口的内存实现。模型发布后只需补充下载、摘要校验和进度适配器，不改变选路与任务状态机。

## 浏览器音频提取

前端使用 Mediabunny 1.52.3 读取 MP4，丢弃视频轨并将主音轨封装为 M4A。兼容的 AAC 音轨会优先直接复制数据，不执行视频解码，也不加载 FFmpeg WASM。提取模块通过动态导入按需加载，当前生产构建的独立压缩前代码块约 505 KB，不进入首页首屏代码。

提取流程支持 0 至 100 的进度和 `AbortSignal` 取消。提取器未找到音轨、容器损坏或浏览器无法处理编码时，页面自动切换为 `REMOTE_VIDEO`；用户主动取消不会触发回退。音频开始上传后的服务器错误直接反馈，不会再次上传完整视频，避免重复创建任务。

当前 `AUDIO_ONLY` 任务最终生成 ASS 字幕和 Mora 时间轴，原视频仍保留在当前电脑或手机上。任务创建后，页面以内存会话保存原始 `File`；时间轴完成后可直接进行 Canvas 同步预览和本地 MP4 导出。刷新结果页会丢失浏览器内存引用，此时用户重新选择同一原视频即可恢复。

浏览器预览按原文 token 绘制，内部保留 Mora 时间，避免把“君”等汉字错误替换成“きみ”等读音。预览与后续逐帧导出共用 `kirakara-timeline` 和 `kirakara-canvas` 数据及绘制接口。WebCodecs 不可用时仍可播放和预览，只禁用后续本地导出能力。

## 完全本地任务状态机

```text
INSPECTING
-> PREPARING_MODELS
-> EXTRACTING_AUDIO
-> SEPARATING_VOCALS
-> ALIGNING
-> GENERATING_SUBTITLE
-> RENDERING_VIDEO
-> COMPLETED
```

任一阶段失败进入 `FAILED`，收到 `AbortSignal` 后进入 `CANCELED`。`runLocalMobileJob` 只编排阶段，真实 FFmpeg、UVR、CTC、ASS 和渲染实现通过适配器注入。

## 只上传音频契约

接口：

```text
POST /api/v1/browser/audio-jobs
Content-Type: multipart/form-data
```

旧地址 `POST /api/v1/mobile/audio-jobs` 暂时保留为兼容入口，不再作为公开契约使用。

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `audio` | 文件 | WAV、MP3、M4A、AAC、FLAC 或 OGG |
| `original_video_name` | 文本 | 本地保留的原 MP4 文件名 |
| `original_video_size_bytes` | 整数 | 原视频大小，必须不超过 300 MB |
| `lyrics_text` | 文本 | 与 `lyrics_file` 二选一 |
| `lyrics_file` | UTF-8 TXT | 与 `lyrics_text` 二选一 |
| `vocal_mode` | `on`/`off` | 沿用现有任务字段 |
| `client_submission_id` | UUID | 网络中断后的幂等恢复标识 |

响应沿用 `JobResponse`，并增加：

```json
{
  "input_mode": "AUDIO_ONLY",
  "source_upload_size_bytes": 123456,
  "source_upload_sha256": "..."
}
```

音频任务进入现有后台队列，完成识别、歌词处理、对齐和 Kirakara 字幕产物生成后停在 `SUBTITLE_GENERATED`，服务端不会主动调用视频渲染器。用户可在浏览器中检查并调整逐句时间、整体偏移和注音，然后选择本地导出。

浏览器缺少 WebCodecs 或 H.264 编码能力时，用户仍可提交原视频和校正数据到 `/api/v1/browser/jobs/{job_id}/cloud-render`。同一任务转入 `CLOUD_RENDER_QUEUED`，服务端跳过音频提取、UVR、识别和对齐，只按统一 Kirakara 规范完成嵌字和编码。原始完整视频任务也使用相同的 Kirakara 视觉与时间语义。

## 下一步验收

1. 使用桌面 Chrome/Edge、Android Chrome 与 iPhone Safari 测试常见 AAC MP4 的兼容率、耗时、峰值内存和后台切换行为。
2. 接入云端 FA-Kara/MMS_FA 可插拔对齐器，复用 UVR 人声结果并输出相同 Mora 时间轴契约。
3. 将 UVR 模型托管到独立模型源，补 SHA-256 校验、断点缓存和真机峰值内存测试。
4. 转换 ReazonSpeech CTC 为 ONNX INT8，使用固定日语歌曲集测量 Mora 中位误差、P95 误差、失败率和实时倍率。
5. Android Chromium 优先测试 WebGPU；iOS Safari 只开放通过 WASM 内存和耗时门槛的路径。
6. UVR、CTC 和本地渲染全部完成后，才允许自动选择 `LOCAL`。
