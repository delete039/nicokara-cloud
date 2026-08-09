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
  ../ALIGNMENT_BENCHMARK.json \
  --output ../alignment-benchmark-report.json
```

报告按引擎输出：

- 样本数、成功数和失败率。
- Mora 起止点平均绝对误差和中位绝对误差。
- 单个时间点最大绝对误差。
- 平均耗时和样本峰值内存。

同一批样本应固定音频、歌词、人工参考时间轴、UVR 模型和全部配置。只有 FA-Kara 的误差明显下降且服务器资源可接受时，才应继续默认启用。
