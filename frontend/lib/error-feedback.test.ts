import { describe, expect, it } from "vitest";

import {
  httpErrorFeedback,
  jobFailureFeedback,
  networkErrorFeedback,
  validationErrorFeedback,
} from "./error-feedback";

describe("validationErrorFeedback", () => {
  it("explains how to fix an invalid MP4 selection", () => {
    const feedback = validationErrorFeedback("invalid_video_type");

    expect(feedback.title).toBe("视频格式不受支持");
    expect(feedback.description).toContain("MP4");
    expect(feedback.solutions).toContain(
      "使用视频转换工具将素材重新编码为标准 MP4 后再上传。",
    );
  });
});

describe("networkErrorFeedback", () => {
  it("uses server deployment guidance instead of local backend wording", () => {
    const feedback = networkErrorFeedback("upload");

    expect(feedback.title).toBe("无法连接服务器");
    expect(feedback.description).toContain("服务器");
    expect(feedback.description).not.toContain("本地");
    expect(feedback.solutions.join(" ")).toContain("刷新页面");
    expect(feedback.solutions.join(" ")).toContain("管理员");
    expect(feedback.retryable).toBe(true);
  });
});

describe("httpErrorFeedback", () => {
  it("maps oversized uploads to an actionable size error", () => {
    const feedback = httpErrorFeedback("upload", 413, "视频文件超过大小限制");

    expect(feedback.title).toBe("上传文件超过大小限制");
    expect(feedback.solutions.join(" ")).toContain("1 GB");
    expect(feedback.solutions.join(" ")).toContain("本地开发");
    expect(feedback.solutions.join(" ")).toContain("Nginx");
    expect(feedback.technicalDetails).toContain("HTTP 状态码：413");
  });

  it("explains the per-client active job limit", () => {
    const feedback = httpErrorFeedback(
      "upload",
      429,
      "Too many active jobs for this client. Try again later.",
      60,
    );

    expect(feedback.title).toBe("同时任务数已达上限");
    expect(feedback.description).toContain("等待或处理");
    expect(feedback.solutions.join(" ")).toContain("取消");
    expect(JSON.stringify(feedback)).not.toContain("每小时");
    expect(JSON.stringify(feedback)).not.toContain("频率限制");
    expect(feedback.retryable).toBe(true);
  });

  it("explains that a full server queue should be retried later", () => {
    const feedback = httpErrorFeedback(
      "upload",
      503,
      "Processing queue is full. Try again later.",
      60,
    );

    expect(feedback.title).toBe("服务器处理队列已满");
    expect(feedback.solutions.join(" ")).toContain("1 分钟");
    expect(feedback.retryable).toBe(true);
  });

  it("provides reverse proxy checks for gateway failures", () => {
    const feedback = httpErrorFeedback("job", 502, "Bad Gateway");

    expect(feedback.title).toBe("服务器网关暂时不可用");
    expect(feedback.solutions.join(" ")).toContain("Nginx");
    expect(feedback.solutions.join(" ")).toContain("nicokara-backend");
  });

  it("explains Cloudflare 524 without dumping an HTML error page", () => {
    const feedback = httpErrorFeedback(
      "upload",
      524,
      "<!DOCTYPE html><title>A timeout occurred</title>",
    );

    expect(feedback.title).toBe("服务器响应超时，正在确认任务");
    expect(feedback.description).toContain("任务可能已经创建");
    expect(feedback.solutions.join(" ")).toContain("不要重复提交");
    expect(feedback.technicalDetails.join(" ")).not.toContain("DOCTYPE");
  });

  it("uses a specific message for an internal job-status failure", () => {
    const feedback = httpErrorFeedback("job", 500, "Internal Server Error");

    expect(feedback.title).toBe("任务状态读取失败");
    expect(feedback.description).toContain("任务仍可能继续处理");
    expect(feedback.title).not.toBe("服务器处理请求失败");
  });

  it("describes invalid reviewed timelines as cloud render input errors", () => {
    const feedback = httpErrorFeedback(
      "cloud_render",
      422,
      "时间轴校正数据无效：line 6 token timing is invalid",
    );

    expect(feedback.title).toBe("时间轴校正数据无效");
    expect(feedback.description).toContain("第 6 行");
    expect(feedback.description).not.toContain("歌词或表单参数创建任务");
  });

  it("shows the exact line and token for reviewed artifact validation", () => {
    const feedback = httpErrorFeedback(
      "timeline_review",
      422,
      "时间轴校正数据无效：line 6 token 3 timing is invalid",
    );

    expect(feedback.title).toBe("调整后的时间轴无效");
    expect(feedback.description).toContain("第 6 行第 3 个词元");
    expect(feedback.description).toContain("词元时间无效");
    expect(feedback.solutions.join(" ")).toContain("第 6 行");
  });

  it("does not describe a cloud render state conflict as a download error", () => {
    const feedback = httpErrorFeedback(
      "cloud_render",
      409,
      "当前任务不能进入云端仅渲染队列",
    );

    expect(feedback.title).toBe("云端渲染状态已变化");
    expect(feedback.description).toContain("刷新");
    expect(feedback.description).not.toContain("文件暂时不能下载");
  });

  it("translates FastAPI field validation into an actionable user explanation", () => {
    const feedback = httpErrorFeedback(
      "upload",
      422,
      JSON.stringify([
        {
          type: "missing",
          loc: ["body", "original_video_size_bytes"],
          msg: "Field required",
          input: { original_video_name: "song.mp4" },
        },
      ]),
    );

    expect(feedback.title).toBe("提交内容未通过校验");
    expect(feedback.description).toContain("原视频大小未提供");
    expect(feedback.description).not.toContain("服务器无法使用当前视频");
    expect(feedback.solutions.join(" ")).toContain("返回修改");
    expect(feedback.technicalDetails.join(" ")).toContain(
      "original_video_size_bytes",
    );
    expect(feedback.technicalDetails.join(" ")).not.toContain("song.mp4");
  });
});

describe("jobFailureFeedback", () => {
  it("does not blame the video when browser-extracted audio cannot be decoded", () => {
    const feedback = jobFailureFeedback(
      "AUDIO_EXTRACTION_FAILED",
      "EXTRACTING_AUDIO",
      null,
      "job-audio-only",
      "AUDIO_ONLY",
    );

    expect(feedback.description).toContain("音频");
    expect(feedback.solutions.join(" ")).toContain("FFmpeg");
    expect(JSON.stringify(feedback)).not.toContain("H.264");
    expect(JSON.stringify(feedback)).not.toContain("重新编码视频");
  });

  it("reports a missing FFmpeg installation as a server configuration error", () => {
    const feedback = jobFailureFeedback(
      "FFMPEG_UNAVAILABLE",
      "EXTRACTING_AUDIO",
      null,
      "job-missing-ffmpeg",
      "AUDIO_ONLY",
    );

    expect(feedback.title).toBe("服务器音视频处理工具不可用");
    expect(feedback.description).toContain("FFmpeg");
    expect(feedback.solutions.join(" ")).toContain("NICOKARA_FFMPEG_PATH");
    expect(JSON.stringify(feedback)).not.toContain("视频编码");
  });

  it("offers the ON VOCAL fallback when MDX vocal removal fails", () => {
    const feedback = jobFailureFeedback(
      "VOCAL_REMOVAL_FAILED",
      "REMOVING_VOCALS",
      "Processing failed during vocal removal.",
      "job-123",
    );

    expect(feedback.title).toBe("人声分离失败");
    expect(feedback.solutions.join(" ")).toContain("ON VOCAL");
    expect(feedback.solutions.join(" ")).toContain("MDX");
    expect(feedback.technicalDetails).toContain("任务 ID：job-123");
  });

  it("explains how to improve lyrics alignment input", () => {
    const feedback = jobFailureFeedback(
      "ALIGNMENT_FAILED",
      "ALIGNING",
      null,
      "job-456",
    );

    expect(feedback.title).toBe("歌词时间轴对齐失败");
    expect(feedback.solutions.join(" ")).toContain("每句歌词单独一行");
    expect(feedback.solutions.join(" ")).toContain("演唱内容一致");
    expect(feedback.description).toContain("FA-Kara / MMS");
    expect(feedback.solutions.join(" ")).toContain("{漢字|かな}");
  });

  it("describes transcription failures without claiming Whisper is primary", () => {
    const feedback = jobFailureFeedback(
      "TRANSCRIPTION_FAILED",
      "TRANSCRIBING",
      null,
      "job-transcription",
    );

    expect(feedback.title).toBe("歌声时间分析失败");
    expect(feedback.description).toContain("歌声时间信息");
    expect(JSON.stringify(feedback)).not.toContain("Whisper");
  });

  it("tells the user to recreate a task interrupted by deployment", () => {
    const feedback = jobFailureFeedback(
      "SERVICE_RESTARTED",
      "TRANSCRIBING",
      "Processing was interrupted by a service restart.",
      "job-789",
    );

    expect(feedback.title).toBe("任务因服务器重启而中断");
    expect(feedback.solutions.join(" ")).toContain("重新上传");
    expect(feedback.solutions.join(" ")).toContain("部署");
  });

  it("keeps unknown failures useful for support", () => {
    const feedback = jobFailureFeedback(
      "UNEXPECTED_FAILURE",
      "UNKNOWN_STAGE",
      "Unexpected processing failure.",
      "job-999",
    );

    expect(feedback.title).toBe("服务器处理任务失败");
    expect(feedback.solutions.join(" ")).toContain("任务 ID");
    expect(feedback.technicalDetails).toContain("错误代码：UNEXPECTED_FAILURE");
  });
});
