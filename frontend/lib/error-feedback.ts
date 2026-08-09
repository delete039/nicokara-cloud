export type ErrorFeedback = {
  title: string;
  description: string;
  solutions: string[];
  technicalDetails: string[];
  retryable: boolean;
};

export type ErrorContext = "upload" | "job" | "cloud_render";

export type ValidationErrorCode =
  | "video_required"
  | "lyrics_required"
  | "lyrics_source_conflict"
  | "invalid_video_type"
  | "video_too_large";

const VALIDATION_ERRORS: Record<ValidationErrorCode, ErrorFeedback> = {
  video_required: {
    title: "尚未选择视频",
    description: "生成任务需要一个包含画面和音轨的 MP4 视频。",
    solutions: ["点击“上传原版 MV”并选择视频文件。"],
    technicalDetails: [],
    retryable: false,
  },
  lyrics_required: {
    title: "尚未提供歌词",
    description: "当前服务器版本需要歌词才能生成逐字变色字幕。",
    solutions: [
      "在歌词输入框中粘贴歌词，或选择一个 UTF-8 编码的 TXT 文件。",
      "每句歌词单独一行，并尽量与视频中的演唱顺序一致。",
    ],
    technicalDetails: [],
    retryable: false,
  },
  lyrics_source_conflict: {
    title: "歌词来源重复",
    description: "粘贴歌词和 TXT 文件不能同时提交。",
    solutions: ["保留其中一种歌词来源，移除另一种后重新提交。"],
    technicalDetails: [],
    retryable: false,
  },
  invalid_video_type: {
    title: "视频格式不受支持",
    description: "服务器当前只接受标准 MP4 容器的视频。",
    solutions: [
      "使用视频转换工具将素材重新编码为标准 MP4 后再上传。",
      "不要仅修改文件扩展名，服务器会检查文件内部的 MP4 标识。",
    ],
    technicalDetails: [],
    retryable: false,
  },
  video_too_large: {
    title: "视频文件过大",
    description: "当前服务器允许上传的视频最大为 1 GB。",
    solutions: [
      "降低视频分辨率或码率，将文件压缩到 1 GB 以内。",
      "裁剪不需要的片头、片尾后重新上传。",
    ],
    technicalDetails: [],
    retryable: false,
  },
};

function retryDelay(seconds?: number): string {
  if (!seconds || seconds <= 0) return "稍后";
  if (seconds < 60) return `${seconds} 秒后`;
  return `${Math.ceil(seconds / 60)} 分钟后`;
}

function httpDetails(status: number, detail?: string | null): string[] {
  const details = [`HTTP 状态码：${status}`];
  if (detail?.trim()) details.push(`服务器信息：${detail.trim()}`);
  return details;
}

export function validationErrorFeedback(
  code: ValidationErrorCode,
): ErrorFeedback {
  return VALIDATION_ERRORS[code];
}

export function networkErrorFeedback(context: ErrorContext): ErrorFeedback {
  return {
    title: "无法连接服务器",
    description:
      context === "upload"
        ? "视频尚未成功提交。浏览器没有收到服务器响应，可能是网络中断、反向代理超时或服务正在重启。"
        : "暂时无法读取任务状态。任务可能仍在服务器上继续处理，页面会自动尝试恢复连接。",
    solutions: [
      "确认网络正常后刷新页面或重新尝试。",
      "如果其他设备也无法访问，请联系管理员检查 Nginx 和 Nicokara 服务状态。",
      context === "upload"
        ? "不要连续重复提交大文件；先确认任务列表或稍后重新上传。"
        : "保留当前任务页面和任务 ID，连接恢复后可继续查询。",
    ],
    technicalDetails: ["网络请求未收到有效的 HTTP 响应。"],
    retryable: true,
  };
}

export function httpErrorFeedback(
  context: ErrorContext,
  status: number,
  detail?: string | null,
  retryAfterSeconds?: number,
): ErrorFeedback {
  const technicalDetails = httpDetails(status, detail);

  if (context === "cloud_render" && (status === 400 || status === 422)) {
    const lineMatch = detail?.match(/line\s+(\d+)/iu);
    const lineNumber = lineMatch?.[1];
    return {
      title: "时间轴校正数据无效",
      description: lineNumber
        ? `第 ${lineNumber} 行的时间范围或词元时间不符合要求，服务器无法生成云端渲染字幕。`
        : "校正后的时间轴与服务器保存的歌词结构不一致，暂时不能进入云端渲染队列。",
      solutions: [
        "检查相邻歌词是否发生时间重叠，并确认每行结束时间晚于开始时间。",
        "刷新任务页重新读取服务器时间轴；如仍然失败，请保留下方服务器信息。",
      ],
      technicalDetails,
      retryable: false,
    };
  }

  if (context === "cloud_render" && status === 409) {
    return {
      title: "云端渲染状态已变化",
      description:
        "任务可能已经进入队列，或者重新选择的视频与最初素材不一致。页面将优先恢复最新任务状态，必要时刷新后继续查看。",
      solutions: [
        "刷新任务页查看排队位置或渲染进度，不要连续重复提交同一视频。",
        "如果任务仍可编辑，请重新选择名称和大小都与最初上传记录一致的原视频。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 413) {
    return {
      title: "上传文件超过大小限制",
      description: "上传入口拒绝了本次请求，视频、歌词或请求体超过了允许大小。",
      solutions: [
        "将视频压缩到 1 GB 以内后重新上传。",
        "歌词 TXT 文件应小于 1 MB，并使用 UTF-8 编码。",
        "本地开发时，请确认前端的 /api/v1 请求已代理到 127.0.0.1:8000。",
        "服务器部署时，请管理员检查 Nginx 的 client_max_body_size 配置。",
      ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 415) {
    return {
      title: "上传内容格式不正确",
      description: "服务器检测到视频不是有效 MP4，或歌词文件不是 UTF-8 文本。",
      solutions: [
        "重新编码视频为 MP4，不要只修改扩展名。",
        "将歌词文件另存为 UTF-8 编码的 TXT 文件。",
      ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 422 || status === 400) {
    return {
      title: "提交内容未通过校验",
      description: "服务器无法使用当前视频、歌词或表单参数创建任务。",
      solutions: [
        "确认选择了 MP4 视频，并且只使用粘贴歌词或 TXT 文件中的一种。",
        "重新选择素材后提交；如果持续失败，请将下方技术信息提供给管理员。",
      ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 429) {
    return {
      title: "同时任务数已达上限",
      description:
        "当前来源已有较多任务正在等待或处理。为避免单个用户占满队列，暂时不能创建更多任务。",
      solutions: [
        "等待现有任务完成，或在任务状态页取消不再需要的任务后重新提交。",
        "如果多人共用同一网络出口，请确认是否已有其他任务正在生成。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 503 && detail?.toLowerCase().includes("queue")) {
    const delay = retryDelay(retryAfterSeconds);
    return {
      title: "服务器处理队列已满",
      description: `当前已有较多任务等待处理，请在${delay}重新提交。`,
      solutions: [
        `等待约${delay}后再上传。`,
        "不要重复提交同一视频，已有任务完成后队列会自动释放。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 502 || status === 504) {
    return {
      title: "服务器网关暂时不可用",
      description: "Nginx 没有及时连接到后端服务，可能正在发布、重启或处理超时。",
      solutions: [
        "等待 1 至 2 分钟后刷新页面。",
        "管理员可检查 Nginx 错误日志以及 nicokara-backend、nicokara-frontend 服务状态。",
        "若上传大视频时出现 504，请管理员检查代理读写超时配置。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 503) {
    return {
      title: "服务器服务暂时不可用",
      description: "应用可能正在重启、发布新版本或暂时没有足够资源处理请求。",
      solutions: [
        "等待 1 至 2 分钟后重新尝试。",
        "管理员可运行 systemctl status nicokara-backend nicokara-frontend 检查服务。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 404) {
    return {
      title: context === "job" ? "任务不存在或已过期" : "上传接口不存在",
      description:
        context === "job"
          ? "服务器找不到这个任务。任务可能已超过保留时间被自动清理，或任务地址不完整。"
          : "当前站点没有找到上传接口，可能是前后端版本或 Nginx 路由配置不一致。",
      solutions:
        context === "job"
          ? ["返回上传页创建新任务。", "核对任务链接是否完整。"]
          : [
              "刷新页面后重试。",
              "管理员应确认前端使用 /api/v1，并检查 Nginx 的 /api/ 代理配置。",
            ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 409) {
    return {
      title: "任务结果尚未准备完成",
      description: "服务器仍在处理任务，当前文件暂时不能下载。",
      solutions: ["返回任务状态页等待处理完成后再下载。"],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 410) {
    return {
      title: "任务文件已被清理",
      description: "任务记录仍存在，但对应文件已过期或不再可用。",
      solutions: ["重新上传原视频和歌词创建新任务。"],
      technicalDetails,
      retryable: false,
    };
  }

  return {
    title: status >= 500 ? "服务器处理请求失败" : "请求未能完成",
    description:
      status >= 500
        ? "服务器发生内部错误，当前请求没有正常完成。"
        : "服务器拒绝了当前请求，请检查提交内容或任务地址。",
    solutions: [
      "稍后重试一次。",
      "如果问题持续出现，请将技术信息和发生时间提供给管理员查询服务器日志。",
    ],
    technicalDetails,
    retryable: status >= 500,
  };
}

type JobFailureDefinition = Omit<
  ErrorFeedback,
  "technicalDetails" | "retryable"
>;

const JOB_FAILURES: Record<string, JobFailureDefinition> = {
  VOCAL_REMOVAL_FAILED: {
    title: "人声分离失败",
    description: "服务器无法使用 MDX 模型生成伴奏音轨。原任务不能继续渲染。",
    solutions: [
      "重新上传并选择 ON VOCAL，可跳过人声分离继续制作。",
      "确认源视频包含正常的立体声音轨，而不是损坏或无声素材。",
      "管理员应检查 MDX 模型文件、磁盘空间和 nicokara-backend 日志。",
    ],
  },
  AUDIO_EXTRACTION_FAILED: {
    title: "音频提取失败",
    description: "服务器无法从视频中提取可供分析的音轨。",
    solutions: [
      "确认视频可以正常播放且确实包含音频。",
      "将视频重新编码为 H.264 视频加 AAC 音频的标准 MP4 后再上传。",
      "管理员应检查 FFmpeg 是否可用，并根据任务 ID 查询后端日志。",
    ],
  },
  TRANSCRIPTION_FAILED: {
    title: "日语语音识别失败",
    description: "服务器未能完成 Whisper 转录，后续歌词对齐无法继续。",
    solutions: [
      "确认视频音轨清晰且不是完全静音。",
      "尝试上传较短或码率更低的视频，避免服务器内存不足。",
      "管理员应检查 Whisper 模型路径、可用内存和后端日志。",
    ],
  },
  LYRIC_PROCESSING_FAILED: {
    title: "歌词处理失败",
    description: "服务器无法完成歌词分句、日语读音或 Ruby 注音处理。",
    solutions: [
      "移除歌词中的网页标签、异常控制字符和大段空白后重试。",
      "确保 TXT 文件使用 UTF-8 编码，并让每句歌词单独一行。",
      "管理员应根据任务 ID 检查歌词处理和 DeepSeek 降级日志。",
    ],
  },
  ALIGNMENT_FAILED: {
    title: "歌词时间轴对齐失败",
    description: "歌词内容与识别到的演唱音频差异过大，无法生成可靠时间轴。",
    solutions: [
      "确保歌词与视频中的实际演唱内容一致，不要混入翻译、时间标签或说明文字。",
      "每句歌词单独一行，并保持与演唱顺序一致。",
      "删去视频中未演唱的歌词，或补齐明显缺失的歌词后重试。",
    ],
  },
  SUBTITLE_GENERATION_FAILED: {
    title: "ASS 字幕生成失败",
    description: "时间轴已处理，但服务器无法生成可烧录的 ASS 字幕。",
    solutions: [
      "将过长歌词拆成多行，并移除特殊控制字符后重试。",
      "管理员应检查服务器日文字体和字幕生成日志。",
    ],
  },
  VIDEO_RENDERING_FAILED: {
    title: "最终视频渲染失败",
    description: "字幕已经生成，但 FFmpeg 没有成功输出最终 MP4。",
    solutions: [
      "稍后重新创建任务，避免服务器临时负载或磁盘空间问题。",
      "尝试使用分辨率或码率更低的源视频。",
      "管理员应检查磁盘剩余空间、FFmpeg/libass、日文字体和后端日志。",
    ],
  },
  SERVICE_RESTARTED: {
    title: "任务因服务器重启而中断",
    description: "任务处理期间服务器服务发生重启，当前任务无法从中断位置继续。",
    solutions: [
      "返回上传页重新上传视频和歌词，创建一个新任务。",
      "如果服务器正在部署新版本，请等待部署结束后再提交。",
      "管理员可检查服务重启原因，避免在有任务处理时发布。",
    ],
  },
};

export function jobFailureFeedback(
  errorCode: string | null,
  stage: string,
  serverMessage: string | null,
  jobId: string,
): ErrorFeedback {
  const definition =
    (errorCode ? JOB_FAILURES[errorCode] : undefined) ?? {
      title: "服务器处理任务失败",
      description: "服务器未能完成当前任务，具体原因需要结合任务日志确认。",
      solutions: [
        "检查素材后重新创建一次任务。",
        "如果问题重复出现，请把任务 ID、错误代码和失败阶段提供给管理员。",
      ],
    };
  const technicalDetails = [`任务 ID：${jobId}`, `失败阶段：${stage}`];
  if (errorCode) technicalDetails.push(`错误代码：${errorCode}`);
  if (serverMessage?.trim()) {
    technicalDetails.push(`服务器信息：${serverMessage.trim()}`);
  }

  return {
    ...definition,
    technicalDetails,
    retryable: false,
  };
}
