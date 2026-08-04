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
});

describe("jobFailureFeedback", () => {
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
