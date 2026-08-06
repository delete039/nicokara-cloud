import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelAdminUploadTicket,
  getAdminOverview,
  requeueAdminJob,
} from "./admin-api";


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("admin API", () => {
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
});
