# FA-Kara 接入完整性审计

## 审计基准

- 上游仓库：[moriwx/FA-Kara](https://github.com/moriwx/FA-Kara)
- 完整核对提交：`029a3e8d03645b2dd56931eff7092175cebf8379`
- 上游提交日期：2026-08-09
- 本项目版本：`v0.3.0-alpha.3`

本次不是只阅读 README 或摘取单个对齐函数。已逐行检查上游的
`main.py`、`align.py`、`align_yohane.py`、`haruraw2norm.py`、
`utils_audio.py`、`utils_basic.py`、`norm2lrc.py`、`norm2ass.py`、
`ass2lrc.py`、`lrcfmt.py`，并核对 `requirements.txt`、`LICENSE`、
示例歌词和输入音频。二进制示例音频只用于流程验证，不属于源码审读范围。

## 上游流程与本项目落点

| FA-Kara 行为 | 本项目适配位置 | 状态 |
|---|---|---|
| `{漢字|かな}` Ruby 标注 | `backend/app/lyrics/processor.py` | 已接入，标记不会泄漏到显示歌词 |
| `[表记|romaji]` 隐式发音 | `backend/app/lyrics/processor.py`、`alignment/mms.py` | 已接入，显示文字与对齐发音分开保存 |
| Janome 修正助词 `は/へ` | `backend/app/lyrics/processor.py` | 已接入 |
| pykakasi 假名转罗马音 | `backend/app/alignment/mms.py` | 已接入 |
| 促音 `っ` 与长音 `ー` 修正 | `backend/app/alignment/mms.py` | 已接入 |
| librosa RMS 非静音检测 | `backend/app/alignment/mms_worker.py` | 已接入，默认参数与上游一致 |
| 可选推理倍速 | `mms_worker.py`、`core/config.py` | 已接入，服务器环境变量控制 |
| 拼接非静音片段后运行 MMS_FA | `backend/app/alignment/mms_worker.py` | 已接入 |
| 压缩时间映射回原音频 | `backend/app/alignment/mms_worker.py` | 已接入 |
| 句首落点修正 | `backend/app/alignment/mms_worker.py` | 已按歌词行边界适配 |
| 20 ms 窗口尾音修正 | `backend/app/alignment/mms_worker.py` | 已按歌词行边界适配 |
| TorchAudio `MMS_FA` 默认模型 | `backend/app/alignment/mms_worker.py` | 已接入，保留默认 star token 行为 |
| GPU/CPU 自动选择 | `mms.py`、`mms_worker.py` | 已接入 |
| Ruby LRC、RLF、ASS 输出 | 本项目时间轴与 Kirakara 模块 | 由本项目原生输出链替代 |

## 为云端架构做的改动

1. 输入音频不由 FA-Kara CLI 自己寻找。任务队列先用 UVR 生成 vocals，Whisper 与 MMS 共用同一份人声音轨，避免重复做人声分离。
2. 上游扁平 `result_list` 被拆成 `LyricDocument -> LyricLine -> LyricToken -> Mora`。新增 `alignment_pronunciation`，避免 `[表记|romaji]` 的辅助读音污染页面显示和 Ruby 注音。
3. 上游一次运行同时写 LRC/RLF/ASS。本项目只把 MMS span 转成统一 `timeline.json`；KRL、DOM 预览、Canvas 导出和云端 FFmpeg 渲染继续由 Kirakara 适配层负责。
4. MMS 模型在可终止的独立子进程中按任务运行。超时、依赖缺失、无有效人声、span 数不完整或时间非法都会抛出受控错误，并由现有 Whisper Mora 对齐器继续任务。
5. 行边界信息通过 `line_token_counts` 传给子进程，使上游以换行符判断句首/尾音的逻辑可以在结构化歌词中等价执行。
6. LRC 行时间戳仍作为用户给定的最终行窗口。MMS 负责行内 Mora 相对节奏，随后由现有 LRC 重定时逻辑应用行起点。
7. DeepSeek 自动注音按实际唱法生成英文和数字的平假名读音，首次结果未转换时自动纠正一次；本地处理器对常见英文使用外来语词典，未收录的专名或缩写使用字母名假名作为可编辑占位。所有英文和数字都会在注音确认页高亮，确认后按 Mora 进入 MMS；用户也可使用 `[表记|romaji]` 明确特殊唱法。
8. Cloudflare 524、其他 5xx 或上传连接中断时，音频任务会使用同一次 `client_submission_id` 查询已创建任务；只有恢复失败才显示提交错误。
9. UVR 缓存若因下载中断而留下不受支持的 MD5，系统只删除当前损坏模型并重试一次；不会把损坏缓存静默降级成原曲 MMS 输入。
10. MMS 完整返回但平均置信度低于 `NICOKARA_FA_KARA_MIN_CONFIDENCE` 时同样视为失败，防止数量正确但时间明显失真的结果进入预览。

## 有意未移植的上游模块

- `align_yohane.py` 的 [NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn](https://huggingface.co/NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn) 可选模型：上游 `1998b98` 新增 `-m yohane` / `-hf` 选择，但默认仍是 `mms`。模型卡未提供相对 MMS_FA 的固定集误差数据，且许可为 CC BY-NC-SA 4.0，因此当前生产不在无基准的情况下直接替换默认模型。
- 英语 CMUdict/Pyphen 自动分音节、数字英语读法和中文拼音：会显著增加语言规则与模型依赖，当前日语云端使用显式 `[表记|romaji]` 和 Whisper 降级，避免静默生成错误时间轴。
- Moe/Uta 输入格式和 FA-Kara 自带 LRC/RLF/ASS CLI：项目已有 TXT/LRC 输入、KRL 工程和 Kirakara 渲染契约，重复接入会产生两套不一致输出。
- 上游导唱灯、BPM、Offset 和每行自动切字参数：这些属于 FA-Kara 文件输出层，不属于当前云端声学对齐职责。

以上项目是经过边界选择后明确不接入，并非漏抄文件。后续若增加多语言自动发音或第二对齐模型，应作为独立版本开发并新增基准数据，不能直接混进默认路径。

## 配置与运行注意事项

| 环境变量 | 默认值 | 作用 |
|---|---:|---|
| `NICOKARA_FA_KARA_ENABLED` | `true` | 开关 MMS 主对齐器 |
| `NICOKARA_FA_KARA_DEVICE` | `auto` | 自动选择 CPU/CUDA，也可固定 |
| `NICOKARA_FA_KARA_TIMEOUT_SECONDS` | `600` | 单任务 MMS 子进程超时 |
| `NICOKARA_FA_KARA_MIN_CONFIDENCE` | `0.15` | 低于该平均置信度时改走备用对齐 |
| `NICOKARA_FA_KARA_AUDIO_SPEED` | `1` | 推理变速，默认不变速 |
| `NICOKARA_FA_KARA_SILENCE_WINDOW_SECONDS` | `0.8` | 全曲非静音检测窗口 |
| `NICOKARA_FA_KARA_SILENCE_TOP_PERCENT` | `10` | 能量参考百分位 |
| `NICOKARA_FA_KARA_SILENCE_THRESHOLD_RATIO` | `0.1` | 静音阈值比例 |
| `NICOKARA_FA_KARA_TAIL_WINDOW_SECONDS` | `0.02` | 尾音检测窗口 |

TorchAudio MMS_FA 权重下载大小为 `1,262,047,414` 字节，约 1.18 GiB。首次任务需要下载，之后由 `mms-model-cache` Docker 卷复用。CPU 可以运行但耗时明显高于 GPU；超过配置时间会自动使用 Whisper，不会让任务以不明服务器错误中断。

## 验证记录

- 后端：`185 passed`
- 前端：`158 passed`；另有 3 项既有管理员日志页面测试因对应实现尚未加入工作区而失败，与本次对齐修改无关
- 前端 ESLint：通过
- 前端生产构建：通过
- 真实任务：使用 FA-Kara 官方示例音频制作 22 秒 MP4，提交 3 行带 Ruby 的官方歌词；任务依次完成 UVR、Whisper、歌词解析、MMS 和 Kirakara 字幕生成。
- 实际结果：`alignment_engine=fa_kara_mms`、`alignment_model=torchaudio.pipelines.MMS_FA`、3 行 43 个 Mora、无回退警告、无公开错误，时间轴范围 4.380 至 18.395 秒。
- 2026-08-11 故障复现：两个真实任务在 UVR 模型仅下载到 18 MB、MD5 不受支持后继续使用原曲 MMS，置信度分别只有 `0.058`、`0.113`，最长单 Mora 分别达到 `22.645s`、`13.9s`。
- 2026-08-11 修复复测：损坏缓存自动替换为可加载模型；同一首 252 秒音频的人声分离成功，重新对齐置信度为 `0.471`，最长 Mora 为 `5.305s`，超过 1 秒的 Mora 从 20 个降为 4 个。
- 幂等恢复：以相同 `client_submission_id` 再次提交后返回原任务，数据库任务总数仍为 1。
- 任务页 HTTP：`200`，服务端 HTML 不含“服务器处理请求失败”。应用内浏览器自动点击因其本机地址安全策略被阻止，未绕过该策略；交互组件由前端测试、生产构建和真实 API 流程共同覆盖。

本审计记录的是当前提交实际行为。更新 FA-Kara 上游版本时，应先更新本文件中的固定提交号，重新逐文件核对，再运行全部测试和网页流程。
