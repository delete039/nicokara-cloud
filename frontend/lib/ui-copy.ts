export const HOME_COPY = {
  introduction:
    "上传原版 MV 和日语歌词，服务器将自动完成歌声识别、歌词同步、假名注音与视频合成。",
  steps: [
    {
      title: "提交素材",
      text: "选择 MP4 视频，并粘贴歌词或上传 UTF-8 TXT 文件。",
    },
    {
      title: "服务器处理",
      text: "任务进入队列后，服务器会依次完成音频分析、歌词同步和字幕生成。",
    },
    {
      title: "获取结果",
      text: "处理完成后可在线预览，并下载生成的ニコカラ视频。",
    },
  ],
  callToAction: "开始创建",
  author: {
    qq: "280475274",
    bilibili: "esrgt",
    xiaohongshu: "esr",
    message: "项目已开源，欢迎关注项目更新进度，与错误反馈或修改建议",
  },
  metadataDescription:
    "上传 MV 和日语歌词，自动生成带逐字高亮和假名注音的ニコカラ视频。",
} as const;

export const UPLOAD_COPY = {
  videoSectionTitle: "视频素材",
  videoPrompt: "选择 MP4 视频",
  videoHelp: "支持最大 1 GB 的 MP4 文件，请确保视频包含可正常播放的音轨。",
  lyricsSectionTitle: "歌词内容",
  lyricsHint: "每句歌词需单独成行（不然会卡出屏幕QAQ）",
  vocalSectionTitle: "人声模式",
  vocalOnLabel: "ON VOCAL",
  vocalOffLabel: "OFF VOCAL",
  offVocalHint:
    "服务器将使用 MDX 模型分离人声并生成伴奏音轨，处理时间会相应增加。",
  uploadProgressTitle: "正在上传素材到服务器",
  uploadProgressDescription: "上传完成后会自动进入任务状态页。",
  uploadingButton: "正在上传…",
  submitButton: "提交生成任务",
  footer:
    "上传完成后，任务会在服务器继续处理。关闭页面不会中断任务，请保存任务链接或任务 ID。",
} as const;

export const JOB_COPY = {
  backToUpload: "返回上传页",
  loading: "正在连接服务器并读取任务状态…",
  currentProgress: "当前进度",
  queuePosition: "当前排队位置",
  queueTotal: "个等待任务",
  canceling: "正在取消…",
  cancelQueuedConfirm: "确定退出排队吗？退出后需要重新上传才能再次生成。",
  cancelProcessingConfirm: "确定取消生成吗？服务器会停止后续处理步骤。",
  canceledNotice: "任务已取消，服务器将停止后续处理；已经生成的临时文件会按清理规则自动删除。",
  submittedVideo: "提交的视频",
  taskId: "任务 ID",
  lyricsSource: "歌词来源",
  pastedLyrics: "粘贴输入",
  textFileLyrics: "TXT 文件",
  resultHeading: "生成结果",
  downloadTranscript: "下载歌声识别数据",
  downloadLyrics: "下载歌词处理数据",
  downloadTimeline: "下载歌词时间轴",
  downloadSubtitle: "下载字幕文件",
  unsupportedVideo: "当前浏览器无法播放该视频，请直接下载后查看。",
  downloadVideo: "下载生成的视频",
  createAnother: "创建新任务",
} as const;
