import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AdminLogsView, JobTimelineView } from "./page";
import type { AdminJobTimelineResponse, AdminLogsResponse } from "@/types/admin";


const structuredLogs: AdminLogsResponse = {
  items: [
    {
      id: 21,
      level: "WARNING",
      category: "pipeline",
      event: "stage.fallback",
      message: "高精度对齐不可用，切换普通对齐器",
      reference_type: "job",
      reference_id: "job-1",
      run_id: "run-1",
      stage: "ALIGNING",
      component: "fa_kara",
      duration_ms: 1280,
      request_id: "request-1",
      schema_version: 1,
      details: { reason: "low confidence" },
      created_at: "2026-08-18T00:00:00+00:00",
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};


describe("structured admin logs", () => {
  it("renders structured filters, diagnostic fields and duration", () => {
    const html = renderToStaticMarkup(
      <AdminLogsView
        response={structuredLogs}
        loading={false}
        page={1}
        onPageChange={() => undefined}
      />,
    );

    expect(html).toContain("事件名");
    expect(html).toContain("处理阶段");
    expect(html).toContain("组件");
    expect(html).toContain("运行批次");
    expect(html).toContain("DEBUG");
    expect(html).toContain("fa_kara");
    expect(html).toContain("1.28 秒");
  });

  it("renders the pipeline duration as the task total without double counting stages", () => {
    const timeline: AdminJobTimelineResponse = {
      ...structuredLogs,
      job_id: "job-1",
      run_ids: ["run-1"],
      total: 3,
      items: [
        structuredLogs.items[0],
        { ...structuredLogs.items[0], id: 22, event: "stage.completed", duration_ms: 2000 },
        { ...structuredLogs.items[0], id: 23, event: "pipeline.completed", duration_ms: 5000 },
      ],
    };

    const html = renderToStaticMarkup(
      <JobTimelineView
        response={timeline}
        selectedRunId="run-1"
        loading={false}
        onRunChange={() => undefined}
        onBack={() => undefined}
      />,
    );

    expect(html).toContain("任务总耗时 5.00 秒");
    expect(html).not.toContain("阶段累计耗时 8.28 秒");
  });
});
