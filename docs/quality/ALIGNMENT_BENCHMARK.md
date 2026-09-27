# FA-Kara/MMS_FA 对齐基准

本基准用于比较 `whisper_mora` 与 `fa_kara_mms` 相对于人工校准时间轴的 Mora 误差、失败率、耗时和峰值内存。歌曲音频及歌词可能受版权保护，因此仓库只提供清单格式，不提交测试素材。

## 准备固定样本

每首歌准备三个结构完全相同的 `timeline.json`：

- `reference.timeline.json`：人工逐 Mora 校准结果。
- `whisper.timeline.json`：关闭 FA-Kara 后生成的结果。
- `mms.timeline.json`：启用 FA-Kara 后生成的结果。

将实际耗时和峰值 RSS 填入清单。可复制 [ALIGNMENT_BENCHMARK.example.json](./ALIGNMENT_BENCHMARK.example.json) 后修改路径；相对路径以清单文件所在目录为基准。

## 生成报告

在 `backend` 目录执行：

```bash
python -m app.alignment.benchmark_cli \
  ../docs/quality/ALIGNMENT_BENCHMARK.json \
  --output ../alignment-benchmark-report.json
```

报告按引擎输出：

- 样本数、成功数和失败率。
- Mora 起止点平均绝对误差和中位绝对误差。
- 单个时间点最大绝对误差。
- 每首歌的 P95 时间点误差（最近秩法），以及各歌曲 P95 的平均值。
- 平均耗时和样本峰值内存。

报告中的平均误差按歌曲等权汇总，`median_absolute_error_ms` 为各歌曲中位数的平均值，
不是将所有歌曲的 Mora 合并后的中位数。资源统计包含有测量数据的失败任务。未测量的耗时或
内存填写 `null`，不要用 `0` 代替。该命令比较已有时间轴，不会运行模型或自动采集资源。

## 数据完整性与通过标准

清单顶层的 `engines` 固定本轮参评引擎。某首歌缺少任一引擎结果时计为失败；
标为 `fa_kara_mms` 的结果如果实际使用了 Whisper 回退，同样计为失败。空清单、重复样本名、
无效时间区间，以及负数或非有限资源数据均不能作为有效评测。报告记录清单和时间轴的 SHA-256，
便于核对两次评测是否使用同一批数据。

`limits` 可设置 `max_failure_rate`、`max_mean_absolute_error_ms`、
`max_mean_case_p95_absolute_error_ms`、`max_mean_elapsed_seconds` 和 `max_peak_rss_mb`。
默认要求失败率为 0，误差及资源阈值由项目实际基线确定。设置资源阈值后，任何样本缺失相应测量
都会导致检查不通过。模型执行失败时，可在该引擎结果中填写 `error`，并保留实际耗时和峰值内存。

```bash
python -m app.alignment.benchmark_cli \
  ../docs/quality/ALIGNMENT_BENCHMARK.json \
  --output ../alignment-benchmark-report.json --strict
```

`--strict` 在检查不通过时仍保存报告，并以退出码 1 结束；清单格式错误以退出码 2 结束。
没有 `--strict` 时也会在报告的 `quality_gate` 中列出未通过项目。

仓库的示例清单没有附带歌曲及人工标注，直接执行会得到缺失文件的失败报告。单元测试使用
构造时间轴验证统计与检查逻辑，不能据此判断真实歌曲上的对齐准确率。

同一批样本应固定音频、歌词、人工参考时间轴、UVR 模型和全部配置。只有 FA-Kara 的误差明显下降且服务器资源可接受时，才应继续默认启用。
