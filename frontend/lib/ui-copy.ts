export const HOME_COPY = {
  introduction:
    "上传原版 MV 和日语歌词：支持的浏览器会把视频保留在浏览器，仅上传音频到服务器。先确认假名注音，再由 FA-Kara 生成 Mora 时间轴和字幕。",
  steps: [
    {
      title: "提交素材",
      text: "选择 MP4 视频，并粘贴歌词或上传 UTF-8 TXT / LRC 文件。",
    },
    {
      title: "确认假名注音",
      text: "服务器整理歌词读音后先暂停，确认或修正每个词的假名，再交给 FA-Kara 对齐。",
    },
    {
      title: "对齐与导出",
      text: "FA-Kara / MMS 使用确认后的读音生成 Mora 时间轴，完成后可在浏览器中预览、调整时间并导出。",
    },
  ],
  callToAction: "开始创建",
  author: {
    qq: "280475274",
    bilibili: "esrgt",
    xiaohongshu: "esr",
    repositoryLabel: "本项目已开源",
    repositoryUrl: "https://github.com/delete039/nicokara-cloud",
    message: "欢迎关注项目更新进度，与错误反馈或修改建议",
    acknowledgements: [
      {
        developer: "FMPeach",
        developerUrl: "https://github.com/FMPeach",
        project: "Kirakara-Player",
        projectUrl: "https://github.com/FMPeach/Kirakara-Player",
        description: "本项目的字幕预览、样式配置与渲染适配参考了该项目。",
      },
      {
        developer: "moriwx",
        developerUrl: "https://github.com/moriwx",
        project: "FA-Kara",
        projectUrl: "https://github.com/moriwx/FA-Kara",
        description: "本项目的歌词发音标记、非静音处理与 MMS 强制对齐参考并适配了该项目。",
      },
    ],
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
    "排队时请保持页面打开；进入任务页后可关闭，保存浏览器地址，之后打开即可查看结果。",
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
  textFileLyrics: "TXT / LRC 文件",
  resultHeading: "生成结果",
  downloadTranscript: "下载歌声识别数据",
  downloadLyrics: "下载歌词处理数据",
  downloadTimeline: "下载歌词时间轴",
  downloadAssSubtitle: "下载 ASS 字幕",
  downloadSubtitle: "下载 Kirakara 工程 (.krl)",
  unsupportedVideo: "当前浏览器无法播放该视频，请直接下载后查看。",
  downloadVideo: "下载生成的视频",
  createAnother: "创建新任务",
} as const;
