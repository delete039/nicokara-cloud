import { describe, expect, it } from "vitest";

import {
  canCancelJob,
  cancelJobLabel,
  jobPollDelay,
  queueStatusLabel,
} from "./job-queue";

describe("queueStatusLabel", () => {
  it("shows the current position and total queued jobs", () => {
    expect(queueStatusLabel(2, 5)).toBe(
      "当前排在第 2 位，队列中共有 5 个等待任务。",
    );
  });

  it("omits unavailable queue metrics", () => {
    expect(queueStatusLabel(null, null)).toBeNull();
    expect(queueStatusLabel(0, 3)).toBeNull();
  });
});

describe("jobPollDelay", () => {
  it("polls queued jobs less often than active jobs", () => {
    expect(jobPollDelay("UPLOADED", 0, false)).toBe(4000);
    expect(jobPollDelay("PROCESSING", 0, false)).toBe(2000);
  });

  it("slows polling for hidden tabs", () => {
    expect(jobPollDelay("PROCESSING", 0, true)).toBe(15000);
  });

  it("backs off repeated errors up to thirty seconds", () => {
    expect(jobPollDelay("PROCESSING", 1, false)).toBe(5000);
    expect(jobPollDelay("PROCESSING", 2, false)).toBe(10000);
    expect(jobPollDelay("PROCESSING", 10, false)).toBe(30000);
  });
});

describe("job cancellation controls", () => {
  it("labels queued and processing cancellation actions", () => {
    expect(canCancelJob("UPLOADED")).toBe(true);
    expect(cancelJobLabel("UPLOADED")).toBe("退出排队");
    expect(canCancelJob("PROCESSING")).toBe(true);
    expect(cancelJobLabel("PROCESSING")).toBe("取消生成");
  });

  it("hides cancellation after a task reaches a terminal state", () => {
    expect(canCancelJob("COMPLETED")).toBe(false);
    expect(canCancelJob("FAILED")).toBe(false);
    expect(canCancelJob("CANCELED")).toBe(false);
    expect(cancelJobLabel("CANCELED")).toBeNull();
  });
});
