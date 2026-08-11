import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelAdminUploadTicket,
  getAdminLogs,
  getAdminOverview,
  requeueAdminJob,
} from "./admin-api";


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("admin API", () => {
  it("explains how to enable admin monitoring when the server is unconfigured", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "Admin monitoring is not configured." }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(getAdminOverview("secret-token")).rejects.toMatchObject({
      status: 503,
      message: "管理员监控尚未配置，请在服务端设置 NICOKARA_ADMIN_TOKEN 后重启服务。",
    });
  });

  it("loads the monitor overview with a bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          generated_at: "2026-08-05T00:00:00+00:00",
          upload_counts: { WAITING: 2 },
          job_counts: { PROCESSING: 1 },
          upload_tickets: [],
          jobs: [],
          runner: { healthy: true },
          resources: {},
          audit_events: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const overview = await getAdminOverview("secret-token");

    expect(overview.upload_counts.WAITING).toBe(2);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/overview",
      expect.objectContaining({
        headers: { Authorization: "Bearer secret-token" },
        cache: "no-store",
      }),
    );
  });

  it("sends administrator actions to their protected endpoints", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ id: "target-1", status: "CANCELED" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await cancelAdminUploadTicket("secret-token", "ticket-1");
    await requeueAdminJob("secret-token", "job-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/admin/upload-tickets/ticket-1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/admin/jobs/job-1/requeue",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("loads filtered event logs with pagination and a bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ items: [], total: 0, limit: 50, offset: 50 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAdminLogs("secret-token", {
      level: "ERROR",
      category: "task",
      referenceId: "job / 1",
      query: "MMS 失败",
      limit: 50,
      offset: 50,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/logs?level=ERROR&category=task&reference_id=job+%2F+1&query=MMS+%E5%A4%B1%E8%B4%A5&limit=50&offset=50",
      expect.objectContaining({
        headers: { Authorization: "Bearer secret-token" },
        cache: "no-store",
      }),
    );
  });
});
