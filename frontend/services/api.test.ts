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

describe("createAudioOnlyJob", () => {
  it("uploads audio and original video metadata without sending the video", async () => {
    const audioOnlyJob = {
      id: "job-audio-1",
      status: "UPLOADED",
      stage: "UPLOAD_COMPLETE",
      progress: 100,
      original_video_name: "song.mp4",
      video_size_bytes: 120 * 1024 * 1024,
      video_sha256: "audio-sha",
      input_mode: "AUDIO_ONLY",
      source_upload_size_bytes: 5,
      source_upload_sha256: "audio-sha",
      created_at: "2026-08-06T00:00:00Z",
      updated_at: "2026-08-06T00:00:00Z",
    };
    class FakeXMLHttpRequest {
      readonly upload = { addEventListener: vi.fn() };
      readonly open = vi.fn((method: string, url: string) => {
        expect(method).toBe("POST");
        expect(url).toBe("/api/v1/browser/audio-jobs");
      });
      readonly getResponseHeader = vi.fn(() => null);
      readonly send = vi.fn((body: FormData) => {
        expect(body.get("audio")).toBeInstanceOf(File);
        expect(body.get("original_video_name")).toBe("song.mp4");
        expect(body.get("original_video_size_bytes")).toBe(
          String(120 * 1024 * 1024),
        );
        expect(body.has("video")).toBe(false);
        this.listeners.load?.forEach((listener) => listener());
      });
      status = 201;
      responseText = JSON.stringify(audioOnlyJob);
      private readonly listeners: Record<string, Array<() => void>> = {};

      addEventListener(type: string, listener: () => void) {
        this.listeners[type] ??= [];
        this.listeners[type].push(listener);
      }
    }
    vi.stubGlobal(
      "XMLHttpRequest",
      FakeXMLHttpRequest as unknown as typeof XMLHttpRequest,
    );
    const api = await import("./api");

    expect(api.createAudioOnlyJob).toBeTypeOf("function");
    if (typeof api.createAudioOnlyJob !== "function") return;
    await expect(
      api.createAudioOnlyJob(
        {
          audio: new File(["audio"], "song.wav", { type: "audio/wav" }),
          originalVideoName: "song.mp4",
          originalVideoSizeBytes: 120 * 1024 * 1024,
          lyricsText: "lyrics",
        },
        vi.fn(),
      ),
    ).resolves.toMatchObject({ input_mode: "AUDIO_ONLY" });
  });

  it("aborts the audio upload when its signal is canceled", async () => {
    const controller = new AbortController();
    class FakeXMLHttpRequest {
      static instance: FakeXMLHttpRequest;

      readonly upload = { addEventListener: vi.fn() };
      readonly open = vi.fn();
      readonly send = vi.fn();
      readonly abort = vi.fn(() => {
        this.listeners.abort?.forEach((listener) => listener());
      });
      readonly getResponseHeader = vi.fn(() => null);
      status = 0;
      responseText = "";
      private readonly listeners: Record<string, Array<() => void>> = {};

      constructor() {
        FakeXMLHttpRequest.instance = this;
      }

      addEventListener(type: string, listener: () => void) {
        this.listeners[type] ??= [];
        this.listeners[type].push(listener);
      }
    }
    vi.stubGlobal(
      "XMLHttpRequest",
      FakeXMLHttpRequest as unknown as typeof XMLHttpRequest,
    );
    const api = await import("./api");

    const request = api.createAudioOnlyJob(
      {
        audio: new File(["audio"], "song.m4a", { type: "audio/mp4" }),
        originalVideoName: "song.mp4",
        originalVideoSizeBytes: 1024,
        lyricsText: "lyrics",
      },
      vi.fn(),
      controller.signal,
    );
    controller.abort();

    const xhr = FakeXMLHttpRequest.instance;
    expect(xhr.abort).toHaveBeenCalledOnce();
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("recovers an audio-only task by submission ID after a 524 timeout", async () => {
    const clientSubmissionId = "11111111-2222-4333-8444-555555555555";
    const recoveredJob = {
      id: "job-audio-recovered",
      status: "UPLOADED",
      stage: "UPLOAD_COMPLETE",
      progress: 100,
      input_mode: "AUDIO_ONLY",
    };
    class FakeXMLHttpRequest {
      readonly upload = { addEventListener: vi.fn() };
      readonly open = vi.fn();
      readonly getResponseHeader = vi.fn(() => null);
      readonly send = vi.fn((body: FormData) => {
        expect(body.get("client_submission_id")).toBe(clientSubmissionId);
        this.listeners.load?.forEach((listener) => listener());
      });
      status = 524;
      responseText = "<!DOCTYPE html><title>A timeout occurred</title>";
      private readonly listeners: Record<string, Array<() => void>> = {};

      addEventListener(type: string, listener: () => void) {
        this.listeners[type] ??= [];
        this.listeners[type].push(listener);
      }
    }
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => clientSubmissionId) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(recoveredJob), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal(
      "XMLHttpRequest",
      FakeXMLHttpRequest as unknown as typeof XMLHttpRequest,
    );
    const { createAudioOnlyJob } = await import("./api");

    await expect(
      createAudioOnlyJob(
        {
          audio: new File(["audio"], "song.m4a", { type: "audio/mp4" }),
          originalVideoName: "song.mp4",
          originalVideoSizeBytes: 1024,
          lyricsText: "lyrics",
        },
        vi.fn(),
      ),
    ).resolves.toMatchObject(recoveredJob);
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

describe("getTimeline", () => {
  it("loads the cloud mora timeline without caching it", async () => {
    const timeline = { confidence: 1, lines: [], warnings: [] };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(timeline), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { getTimeline } = await import("./api");

    await expect(getTimeline("job-1")).resolves.toEqual(timeline);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/jobs/job-1/timeline",
      { cache: "no-store" },
    );
  });
});

describe("getInstrumentalAudio", () => {
  it("downloads the cloud UVR instrumental for an off-vocal export", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: { "Content-Type": "audio/wav" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { getInstrumentalAudio } = await import("./api");

    const audio = await getInstrumentalAudio("job-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/jobs/job-1/instrumental",
      { cache: "no-store" },
    );
    expect(audio).toMatchObject({ name: "instrumental.wav", type: "audio/wav" });
    expect(audio.size).toBe(3);
  });
});

describe("submitCloudRender", () => {
  it("uploads the original video and reviewed timeline to the render-only queue", async () => {
    const queued = {
      id: "job-1",
      status: "UPLOADED",
      stage: "CLOUD_RENDER_QUEUED",
      progress: 0,
    };
    class FakeXMLHttpRequest {
      readonly upload = { addEventListener: vi.fn() };
      readonly open = vi.fn((method: string, url: string) => {
        expect(method).toBe("POST");
        expect(url).toBe("/api/v1/browser/jobs/job-1/cloud-render");
      });
      readonly getResponseHeader = vi.fn(() => null);
      readonly send = vi.fn((body: FormData) => {
        expect(body.get("video")).toBeInstanceOf(File);
        expect(JSON.parse(String(body.get("timeline_review")))).toMatchObject({
          lines: [{ start_ms: 1000, end_ms: 2000 }],
        });
        this.listeners.load?.forEach((listener) => listener());
      });
      status = 202;
      responseText = JSON.stringify(queued);
      private readonly listeners: Record<string, Array<() => void>> = {};

      addEventListener(type: string, listener: () => void) {
        this.listeners[type] ??= [];
        this.listeners[type].push(listener);
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest as unknown as typeof XMLHttpRequest);
    const { submitCloudRender } = await import("./api");

    await expect(
      submitCloudRender(
        "job-1",
        new File(["video"], "song.mp4", { type: "video/mp4" }),
        { lines: [{ start_ms: 1000, end_ms: 2000, tokens: [] }] },
        vi.fn(),
      ),
    ).resolves.toMatchObject(queued);
  });

  it("recovers the job status when the render was already queued", async () => {
    const queued = {
      id: "job-1",
      status: "UPLOADED",
      stage: "CLOUD_RENDER_QUEUED",
      progress: 10,
    };
    class FakeXMLHttpRequest {
      readonly upload = { addEventListener: vi.fn() };
      readonly open = vi.fn();
      readonly getResponseHeader = vi.fn(() => null);
      readonly send = vi.fn(() => {
        this.listeners.load?.forEach((listener) => listener());
      });
      status = 409;
      responseText = JSON.stringify({
        detail: "当前任务不能进入云端仅渲染队列",
      });
      private readonly listeners: Record<string, Array<() => void>> = {};

      addEventListener(type: string, listener: () => void) {
        this.listeners[type] ??= [];
        this.listeners[type].push(listener);
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest as unknown as typeof XMLHttpRequest);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(queued), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const { submitCloudRender } = await import("./api");

    await expect(
      submitCloudRender(
        "job-1",
        new File(["video"], "song.mp4", { type: "video/mp4" }),
        { lines: [] },
        vi.fn(),
      ),
    ).resolves.toMatchObject(queued);
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
