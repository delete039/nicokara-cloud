export function adminStatusLabel(value: string): string {
  return ({ WAITING: "等待上传", READY: "等待开始上传", UPLOADING: "正在上传", UPLOADED: "等待处理", PROCESSING: "处理中", FAILED: "失败", CANCELED: "已取消", COMPLETED: "已完成" } as Record<string, string>)[value] ?? value;
}

export function adminStageLabel(value?: string | null): string {
  if (!value) return "未记录阶段";
  if (value === "REMOVING_VOCALS") return "分离人声";
  if (value === "CLOUD_AUDIO_SWAP_QUEUED") return "等待音轨替换";
  if (value === "CLOUD_RENDER_QUEUED") return "等待云端渲染";
  return ({ UPLOADED: "等待处理", EXTRACTING_AUDIO: "提取音频", SEPARATING_VOCALS: "分离人声", TRANSCRIBING: "歌声时间分析", PROCESSING_LYRICS: "处理歌词", ALIGNING: "对齐时间轴", GENERATING_SUBTITLE: "生成字幕", RENDERING_VIDEO: "渲染视频", READING_REVIEW_REQUIRED: "等待注音确认", READING_REVIEW_SAVING: "保存注音", COMPLETED: "已完成", FAILED: "处理失败" } as Record<string, string>)[value] ?? value;
}

export const ADMIN_DIAGNOSTICS: Record<string, { title: string; suggestion: string }> = {
  TIMEOUT: { title: "操作超时", suggestion: "检查该组件的处理耗时、服务连通性和服务器负载；确认超时设置是否适合当前素材。" },
  OUT_OF_MEMORY: { title: "内存不足", suggestion: "检查可用内存和并行任务数量，释放资源或降低并发后重试。" },
  DISK_FULL: { title: "磁盘空间不足", suggestion: "检查任务存储与临时目录所在磁盘，清理过期文件后重试。" },
  PERMISSION_DENIED: { title: "访问权限不足", suggestion: "检查服务账号对相关文件、目录或程序的访问权限。" },
  FILE_NOT_FOUND: { title: "文件或程序不存在", suggestion: "根据原始错误检查输入文件、模型文件和可执行程序的路径。" },
  DEPENDENCY_MISSING: { title: "依赖加载失败", suggestion: "检查缺失模块及其运行环境，修复依赖后重启对应服务。" },
  CONNECTION_FAILED: { title: "连接失败", suggestion: "检查目标服务、网络和代理设置，恢复连接后重试。" },
  PROCESS_FAILED: { title: "外部程序执行失败", suggestion: "结合退出码和程序错误输出检查输入文件、命令参数及运行环境。" },
};
