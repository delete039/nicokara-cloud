import { describe, expect, it } from "vitest";

import { HOME_COPY, JOB_COPY, UPLOAD_COPY } from "./ui-copy";

describe("server-facing interface copy", () => {
  it("describes server processing without local performance promises", () => {
    const copy = JSON.stringify({ HOME_COPY, JOB_COPY, UPLOAD_COPY });

    expect(copy).not.toContain("电脑性能");
    expect(copy).not.toContain("最快约");
    expect(copy).not.toContain("请勿在处理中关闭服务");
    expect(HOME_COPY.introduction).toContain("服务器");
    expect(HOME_COPY.introduction).toContain("视频保留在浏览器");
    expect(HOME_COPY.steps[1].text).toContain("FA-Kara");
    expect(HOME_COPY.steps[2].text).toContain("浏览器");
    expect(UPLOAD_COPY.footer).toContain("排队时请保持页面打开");
    expect(UPLOAD_COPY.footer).toContain("保存浏览器地址");
    expect(UPLOAD_COPY.footer).toContain("之后打开即可查看结果");
  });

  it("labels transfer progress as uploading rather than video production", () => {
    expect(UPLOAD_COPY.uploadProgressTitle).toBe("正在上传素材到服务器");
    expect(UPLOAD_COPY.uploadingButton).toBe("正在上传…");
    expect(UPLOAD_COPY.uploadProgressDescription).toContain("任务状态页");
  });

  it("uses the requested vocal labels and lyrics guidance", () => {
    expect(UPLOAD_COPY.vocalOnLabel).toBe("ON VOCAL");
    expect(UPLOAD_COPY.vocalOffLabel).toBe("OFF VOCAL");
    expect(UPLOAD_COPY.offVocalHint).toContain("MDX");
    expect(UPLOAD_COPY.offVocalHint).not.toContain("相位抵消");
    expect(UPLOAD_COPY.lyricsHint).toBe(
      "每句歌词需单独成行（不然会卡出屏幕QAQ）",
    );
  });

  it("uses clear task and result labels", () => {
    expect(JOB_COPY.loading).toBe("正在连接服务器并读取任务状态…");
    expect(JOB_COPY.currentProgress).toBe("当前进度");
    expect(JOB_COPY.resultHeading).toBe("生成结果");
    expect(JOB_COPY.downloadVideo).toBe("下载生成的视频");
    expect(JOB_COPY.downloadTranscript).toBe("下载歌声识别数据");
    expect(JOB_COPY.downloadLyrics).toBe("下载歌词处理数据");
    expect(JOB_COPY.downloadTimeline).toBe("下载歌词时间轴");
    expect(JOB_COPY.downloadSubtitle).toBe("下载 Kirakara 工程 (.krl)");
    expect(JOB_COPY.queuePosition).toBe("当前排队位置");
    expect(JOB_COPY.canceling).toBe("正在取消…");
    expect(JOB_COPY.canceledNotice).toContain("停止后续处理");
  });
});
