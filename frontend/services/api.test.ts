import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("result video URLs", () => {
  it("uses the deployed reverse proxy by default", async () => {
    const api = await import("./api");

    expect(api.resultVideoUrl("job-1")).toBe(
      "/api/v1/jobs/job-1/result",
    );
    expect(api.downloadVideoUrl("job-1")).toBe(
      "/api/v1/jobs/job-1/download",
    );
  });
});

describe("createUploadTicket", () => {
  it("sends the client submission id with the upload ticket", async () => {
    const ticket = {
      id: "ticket-1",
      status: "READY",
      video_name: "song.mp4",
      video_size_bytes: 1024,
      client_submission_id: "11111111-1111-4111-8111-111111111111",
      created_at: "2026-08-04T00:00:00Z",
      updated_at: "2026-08-04T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(ticket), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { createUploadTicket } = await import("./api");

    await expect(
      createUploadTicket({
        videoName: "song.mp4",
        videoSizeBytes: 1024,
        clientSubmissionId: "11111111-1111-4111-8111-111111111111",
      }),
    ).resolves.toMatchObject(ticket);

    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(requestInit.body as string)).toMatchObject({
      video_name: "song.mp4",
      video_size_bytes: 1024,
      client_submission_id: "11111111-1111-4111-8111-111111111111",
    });
  });
});

describe("createJob", () => {
  it("recovers an already-created task after a 524 completion response", async () => {
    const clientSubmissionId = "22222222-2222-4222-8222-222222222222";
    const ticket = {
      id: "ticket-1",
      status: "READY",
      video_name: "song.mp4",
      video_size_bytes: 1024,
      client_submission_id: clientSubmissionId,
      created_at: "2026-08-04T00:00:00Z",
      updated_at: "2026-08-04T00:00:00Z",
    };
    const session = {
      ticket_id: "ticket-1",
      status: "UPLOADING",
      chunk_size_bytes: 8 * 1024 * 1024,
      total_chunks: 1,
      received_chunks: 0,
    };
    const recoveredJob = {
      id: "job-1",
      status: "UPLOADED",
      stage: "UPLOAD_COMPLETE",
      progress: 100,
      original_video_name: "song.mp4",
      video_size_bytes: 1024,
      video_sha256: "abc",
      lyrics_source: "text",
      client_submission_id: clientSubmissionId,
      error_code: null,
      error_message: null,
      created_at: "2026-08-04T00:00:00Z",
      updated_at: "2026-08-04T00:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(ticket), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(session), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response("524", { status: 524 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(recoveredJob), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    class FakeXMLHttpRequest {
      static instances: FakeXMLHttpRequest[] = [];

      readonly upload = { addEventListener: vi.fn() };
      readonly open = vi.fn();
      readonly send = vi.fn(() => {
        this.listeners.load?.forEach((listener) => listener());
      });
      readonly getResponseHeader = vi.fn(() => null);
      responseText = JSON.stringify({
        ticket_id: "ticket-1",
        chunk_index: 0,
        received_chunks: 1,
        total_chunks: 1,
      });
      status = 200;

      private readonly listeners: Record<string, Array<() => void>> = {};

      constructor() {
        FakeXMLHttpRequest.instances.push(this);
      }

      addEventListener(type: string, listener: () => void) {
        this.listeners[type] ??= [];
        this.listeners[type].push(listener);
      }
    }
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => clientSubmissionId) });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal(
      "XMLHttpRequest",
      FakeXMLHttpRequest as unknown as typeof XMLHttpRequest,
    );
    const { createJob } = await import("./api");

    await expect(
      createJob(
        {
          video: new File(["video"], "song.mp4", { type: "video/mp4" }),
          lyricsText: "lyrics",
        },
        vi.fn(),
      ),
    ).resolves.toMatchObject(recoveredJob);

    expect(FakeXMLHttpRequest.instances[0].open).toHaveBeenCalledWith(
      "POST",
      "/api/v1/upload-tickets/ticket-1/chunks/part/0",
    );
    expect(fetchMock.mock.calls.map((call) => call[0])).toContain(
      `/api/v1/jobs/by-submission/${clientSubmissionId}`,
    );
  });
});

describe("getJob", () => {
  it("returns detailed guidance when the task has expired", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "任务不存在" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const { ApiRequestError, getJob } = await import("./api");

    try {
      await getJob("missing-job");
      expect.fail("getJob should reject a missing task");
    } catch (reason) {
      expect(reason).toBeInstanceOf(ApiRequestError);
      expect((reason as InstanceType<typeof ApiRequestError>).feedback).toMatchObject({
        title: "任务不存在或已过期",
        retryable: false,
      });
    }
  });

  it("returns gateway recovery steps for a deployed server outage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("Bad Gateway", {
          status: 502,
          statusText: "Bad Gateway",
        }),
      ),
    );
    const { ApiRequestError, getJob } = await import("./api");

    try {
      await getJob("job-1");
      expect.fail("getJob should reject a gateway failure");
    } catch (reason) {
      expect(reason).toBeInstanceOf(ApiRequestError);
      const feedback = (reason as InstanceType<typeof ApiRequestError>).feedback;
      expect(feedback.title).toBe("服务器网关暂时不可用");
      expect(feedback.solutions.join(" ")).toContain("Nginx");
    }
  });

  it("returns recoverable server guidance when the request cannot connect", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const { ApiRequestError, getJob } = await import("./api");

    try {
      await getJob("job-1");
      expect.fail("getJob should reject a network failure");
    } catch (reason) {
      expect(reason).toBeInstanceOf(ApiRequestError);
      expect((reason as InstanceType<typeof ApiRequestError>).feedback).toMatchObject({
        title: "无法连接服务器",
        retryable: true,
      });
    }
  });
});

describe("cancelJob", () => {
  it("posts to the task cancellation endpoint", async () => {
    const canceledJob = {
      id: "job-1",
      status: "CANCELED",
      stage: "CANCELED_BY_USER",
      progress: 15,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(canceledJob), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { cancelJob } = await import("./api");

    await expect(cancelJob("job-1")).resolves.toMatchObject(canceledJob);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/jobs/job-1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
