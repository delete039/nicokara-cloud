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
  inputMode?: "VIDEO" | "AUDIO_ONLY",
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
    if (inputMode === "AUDIO_ONLY") {
      return {
        eyebrow: "字幕已生成",
        title: "字幕已生成，视频仍在本机",
        description:
          "云端时间轴已经完成。重新选择原视频后，可以在浏览器中预览并导出ニコカラ视频。",
        progressLabel: "字幕生成完成",
        terminal: true,
        tone: "success",
      };
    }
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
    if (stage === "READING_REVIEW_SAVING") {
      return {
        eyebrow: "正在保存注音",
        title: "正在保存假名注音",
        description: "保存完成后将自动开始生成 FA-Kara Mora 时间轴。",
        progressLabel: "保存注音",
        terminal: false,
        tone: "active",
      };
    }
    if (stage === "READING_REVIEW_REQUIRED") {
      return {
        eyebrow: "注音待确认",
        title: "请先确认假名注音",
        description: "确认后将使用当前读音生成 FA-Kara Mora 时间轴。",
        progressLabel: "等待注音确认",
        terminal: true,
        tone: "pending",
      };
    }
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
            ? "Kirakara 字幕生成失败"
          : stage === "ALIGNING"
            ? "歌词时间轴对齐失败"
          : stage === "PROCESSING_LYRICS"
              ? "歌词处理失败"
              : "歌声时间分析失败",
      description: "服务器未能完成当前处理阶段，请按下方建议检查素材或服务状态。",
      progressLabel: "任务失败",
      terminal: true,
      tone: "error",
    };
  }
  if (stage === "CLOUD_RENDER_QUEUED") {
    return {
      eyebrow: "云端渲染排队",
      title: "Kirakara 视频正在排队",
      description: "原视频与校正结果已保存，服务器将按顺序直接进行 Kirakara 嵌字和视频编码。",
      progressLabel: "等待云端渲染",
      terminal: false,
      tone: "pending",
    };
  }
  if (stage === "REMOVING_VOCALS") {
    return {
      eyebrow: "人声处理",
      title: "正在分离人声与伴奏",
      description: "服务器正在使用 UVR 分离人声与伴奏：人声音轨用于提高歌词对齐精度，选择 OFF VOCAL 时还会用于最终导出。",
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
      eyebrow: "歌声分析",
      title: "正在分析歌声时间",
      description: "服务器正在生成备用的歌声时间信息。",
      progressLabel: "分析歌声",
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
      description: "服务器正在使用 FA-Kara / MMS 匹配人声与歌词；主对齐无法完成时才会尝试备用时间轴。",
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
