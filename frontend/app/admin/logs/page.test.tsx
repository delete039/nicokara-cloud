import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import AdminLogsPage, { AdminLogsView } from "./page";
import type { AdminLogsResponse } from "@/types/admin";


const logs: AdminLogsResponse = {
  items: [
    {
      id: 7,
      level: "ERROR",
      category: "task",
      event: "job.state_changed",
      message: "任务处理失败：TRANSCRIPTION_FAILED",
      reference_type: "job",
      reference_id: "job-1",
      details: {
        status: "FAILED",
        stage: "TRANSCRIBING",
        progress: 40,
        error_code: "TRANSCRIPTION_FAILED",
      },
      created_at: "2026-08-10T00:00:00+00:00",
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};


describe("admin logs", () => {
  it("starts with a protected log-console token form", () => {
    const html = renderToStaticMarkup(<AdminLogsPage />);

    expect(html).toContain("管理员日志");
    expect(html).toContain('type="password"');
  });

  it("renders filters, lifecycle details and pagination state", () => {
    const html = renderToStaticMarkup(
      <AdminLogsView
        response={logs}
        loading={false}
        page={1}
        onPageChange={() => undefined}
      />,
    );

    expect(html).toContain("日志级别");
    expect(html).toContain("事件分类");
    expect(html).toContain("任务或上传 ID");
    expect(html).toContain("TRANSCRIPTION_FAILED");
    expect(html).toContain("第 1 / 1 页");
  });
});
