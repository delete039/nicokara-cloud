export type JobTone =
  | "pending"
  | "active"
  | "success"
  | "error"
  | "canceled";

export type JobPresentation = {
  eyebrow: string;
  title: string;
  description: string;
  progressLabel: string;
  terminal: boolean;
  tone: JobTone;
};

export function jobPresentation(
  status: string,
  stage: string,
): JobPresentation {
  if (status === "CANCELED") {
    return {
      eyebrow: "任务已取消",
      title: "已停止生成",
      description: "任务已从队列或处理流程中退出，不会继续执行后续步骤。",
      progressLabel: "已取消",
      terminal: true,
      tone: "canceled",
    };
  }
  if (status === "COMPLETED") {
    return {
      eyebrow: "处理完成",
      title: "ニコカラ视频已生成",
      description: "视频已经生成，可以直接预览或下载。",
      progressLabel: "处理完成",
      terminal: true,
      tone: "success",
    };
  }
  if (status === "SUBTITLE_GENERATED") {
    return {
      eyebrow: "字幕已生成",
      title: "字幕文件已生成",
      description: "逐字高亮和汉字假名注音已经写入字幕文件。",
      progressLabel: "字幕生成完成",
      terminal: true,
      tone: "success",
    };
  }
  if (status === "ALIGNED") {
    return {
      eyebrow: "时间轴已完成",
      title: "歌词时间轴已完成",
      description: "歌词已经与演唱时间完成匹配。",
      progressLabel: "时间轴完成",
      terminal: true,
      tone: "success",
    };
  }
  if (status === "LYRICS_PROCESSED") {
    return {
      eyebrow: "歌词已处理",
      title: "歌词与注音已处理",
      description: "歌词分行、假名读音和汉字注音已经整理完成。",
      progressLabel: "歌词处理完成",
      terminal: true,
      tone: "success",
    };
  }
  if (status === "TRANSCRIBED") {
    return {
      eyebrow: "识别已完成",
      title: "歌声识别已完成",
      description: "日语歌声和对应时间信息已经识别完成。",
      progressLabel: "识别完成",
      terminal: true,
      tone: "success",
    };
  }
  if (status === "FAILED") {
    return {
      eyebrow: "处理失败",
      title:
        stage === "REMOVING_VOCALS"
          ? "人声分离失败"
          : stage === "EXTRACTING_AUDIO"
          ? "音频提取失败"
          : stage === "RENDERING_VIDEO"
            ? "视频渲染失败"
          : stage === "GENERATING_SUBTITLE"
            ? "ASS 字幕生成失败"
          : stage === "ALIGNING"
            ? "歌词时间轴对齐失败"
            : stage === "PROCESSING_LYRICS"
              ? "歌词处理失败"
              : "歌声识别失败",
      description: "服务器未能完成当前处理阶段，请按下方建议检查素材或服务状态。",
      progressLabel: "任务失败",
      terminal: true,
      tone: "error",
    };
  }
  if (stage === "REMOVING_VOCALS") {
    return {
      eyebrow: "人声处理",
      title: "正在生成伴奏音轨",
      description: "服务器正在分离人声并生成伴奏音轨。选择 OFF VOCAL 模式时会执行此步骤。",
      progressLabel: "分离人声",
      terminal: false,
      tone: "active",
    };
  }
  if (stage === "EXTRACTING_AUDIO") {
    return {
      eyebrow: "音频准备",
      title: "正在准备视频音轨",
      description: "服务器正在读取视频中的音轨，为后续歌声识别做准备。",
      progressLabel: "提取音频",
      terminal: false,
      tone: "active",
    };
  }
  if (stage === "TRANSCRIBING") {
    return {
      eyebrow: "歌声识别",
      title: "正在识别歌声",
      description: "服务器正在识别日语歌声，并记录每句歌词对应的时间。",
      progressLabel: "识别歌声",
      terminal: false,
      tone: "active",
    };
  }
  if (stage === "PROCESSING_LYRICS") {
    return {
      eyebrow: "歌词处理",
      title: "正在整理歌词与注音",
      description: "服务器正在整理歌词分行、假名读音和汉字注音。",
      progressLabel: "处理歌词",
      terminal: false,
      tone: "active",
    };
  }
  if (stage === "ALIGNING") {
    return {
      eyebrow: "时间轴同步",
      title: "正在匹配歌词时间",
      description: "服务器正在把歌词与演唱时间匹配，确保逐字高亮同步。",
      progressLabel: "对齐时间",
      terminal: false,
      tone: "active",
    };
  }
  if (stage === "GENERATING_SUBTITLE") {
    return {
      eyebrow: "字幕生成",
      title: "正在生成逐字高亮字幕",
      description: "服务器正在生成逐字高亮和假名注音字幕。",
      progressLabel: "生成字幕",
      terminal: false,
      tone: "active",
    };
  }
  if (stage === "RENDERING_VIDEO") {
    return {
      eyebrow: "视频合成",
      title: "正在合成最终视频",
      description: "服务器正在将字幕与视频合成。此阶段通常耗时较长，请耐心等待。",
      progressLabel: "合成视频",
      terminal: false,
      tone: "active",
    };
  }
  return {
    eyebrow: "等待处理",
    title: "任务正在排队",
    description: "素材已保存，服务器会按顺序自动开始处理。可以保留页面，也可以稍后通过任务链接返回。",
    progressLabel: "等待处理",
    terminal: false,
    tone: "pending",
  };
}
