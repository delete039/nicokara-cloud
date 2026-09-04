import { afterEach, describe, expect, it, vi } from "vitest";

import {
  normalizedAnalyticsPath,
  recordPageview,
} from "./analytics";


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("pageview analytics", () => {
  it("normalizes public routes without exposing job identifiers", () => {
    expect(normalizedAnalyticsPath("/")).toBe("/");
    expect(normalizedAnalyticsPath("/jobs/secret-job-id")).toBe("/jobs/:jobId");
    expect(normalizedAnalyticsPath("/admin")).toBeNull();
    expect(normalizedAnalyticsPath("/admin/logs")).toBeNull();
  });

  it("posts one pageview with a rolling visit cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await recordPageview("/jobs/:jobId");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/analytics/pageview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ path: "/jobs/:jobId" }),
        credentials: "same-origin",
        keepalive: true,
      }),
    );
  });
});
