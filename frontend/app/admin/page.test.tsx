import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import AdminPage, { AdminDashboardView } from "./page";
import type { AdminOverview } from "@/types/admin";


const overview: AdminOverview = {
  generated_at: "2026-08-05T00:00:00+00:00",
  traffic: {
    tracking_started_at: "2026-08-01T00:00:00+00:00",
    pageviews: 1280,
    visits: 640,
    pageviews_24h: 96,
    visits_24h: 48,
    active_visits: 7,
    pages_per_visit: 2,
    periods: [
      {
        key: "cloudflare-2026-08",
        label: "2026 年 8 月",
        started_at: "2026-07-31T16:00:00+00:00",
        ended_at: "2026-08-31T15:59:59+00:00",
        pageviews: 8720,
        visits: 6160,
        source: "Cloudflare Web Analytics PDF",
      },
      {
        key: "live",
        label: "实时统计",
        started_at: "2026-09-04T06:50:00+00:00",
        ended_at: "2026-09-04T07:00:00+00:00",
        pageviews: 32,
        visits: 20,
        source: "Nicokara",
      },
    ],
  },
  upload_counts: { WAITING: 2, READY: 1, UPLOADING: 1 },
  job_counts: { UPLOADED: 3, PROCESSING: 1, FAILED: 1 },
  upload_tickets: [
    {
      id: "ticket-1",
      status: "WAITING",
      video_name: "long-video-name.mp4",
      video_size_bytes: 1024,
      job_id: null,
      created_at: "2026-08-05T00:00:00+00:00",
      updated_at: "2026-08-05T00:00:00+00:00",
      last_seen_at: "2026-08-05T00:00:00+00:00",
      queue_position: 2,
      queue_size: 2,
    },
  ],
  jobs: [
    {
      id: "job-1",
      status: "FAILED",
      stage: "TRANSCRIBING",
      progress: 40,
      original_video_name: "failed.mp4",
      video_size_bytes: 2048,
      error_code: "TRANSCRIPTION_FAILED",
      error_message: "failed",
      created_at: "2026-08-05T00:00:00+00:00",
      updated_at: "2026-08-05T00:00:00+00:00",
      stage_age_seconds: 120,
    },
  ],
  runner: {
    healthy: true,
    worker_count: 1,
    alive_workers: 1,
    queued_in_memory: 3,
    last_heartbeat_at: "2026-08-05T00:00:00+00:00",
    active_jobs: [],
  },
  resources: {
    cpu_count: 2,
    load_average: {
      one_minute: 0.5,
      five_minutes: 0.4,
      fifteen_minutes: 0.3,
    },
    memory: {
      total_bytes: 1024,
      available_bytes: 512,
      used_bytes: 512,
    },
    disk: {
      total_bytes: 4096,
      used_bytes: 1024,
      free_bytes: 3072,
    },
  },
  audit_events: [],
};


describe("admin monitor", () => {
  it("starts with the protected administrator token form", () => {
    const html = renderToStaticMarkup(<AdminPage />);

    expect(html).toContain("管理员监控");
    expect(html).toContain('type="password"');
    expect(html).not.toContain("secret-token");
  });

  it("renders upload, processing, worker and resource state", () => {
    const html = renderToStaticMarkup(
      <AdminDashboardView
        overview={overview}
        pendingAction={null}
        onCancelUpload={() => undefined}
        onCancelJob={() => undefined}
        onRequeueJob={() => undefined}
      />,
    );

    expect(html).toContain("等待上传");
    expect(html).toContain("已获上传名额");
    expect(html).toContain("第 2 位");
    expect(html).toContain("Worker 正常");
    expect(html).toContain("TRANSCRIBING");
    expect(html).toContain("重新入队");
    expect(html).toContain("磁盘可用");
    expect(html).toContain("访问分析");
    expect(html).toContain("Pageviews");
    expect(html).toContain("1,280");
    expect(html).toContain("Visits");
    expect(html).toContain("640");
    expect(html).toContain("近 5 分钟活跃");
    expect(html).toContain("统计起始");
    expect(html).toContain("Page Views summary");
    expect(html).toContain("Visits summary");
    expect(html).toContain("Cloudflare 历史数据");
    expect(html).toContain('data-traffic-period="cloudflare-2026-08"');
  });
});
