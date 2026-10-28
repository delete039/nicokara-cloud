import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createJob, createUploadTicket, submitCloudRender } from "./api";

class UploadRequest {
  static instances: UploadRequest[] = [];
  static pending = false;
  uploadListeners: Record<string, (event: { loaded: number; lengthComputable: boolean }) => void> = {};
  upload = { addEventListener: vi.fn((name: string, callback: (event: { loaded: number; lengthComputable: boolean }) => void) => { this.uploadListeners[name] = callback; }) };
  status = 200;
  responseText = "{}";
  timeout = 0;
  listeners: Record<string, () => void> = {};
  open = vi.fn();
  getResponseHeader = () => null;
  send = vi.fn(() => { if (!UploadRequest.pending) this.listeners.load?.(); });
  abort = vi.fn(() => this.listeners.abort?.());
  addEventListener(name: string, callback: () => void) { this.listeners[name] = callback; }
  constructor() { UploadRequest.instances.push(this); }
}

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const video = new File([new Uint8Array(17)], "resume.mp4", { lastModified: 1 });
const input = { video, lyricsText: "song" };
const ticket = { id: "ticket-1", status: "UPLOADING" };
const session = { ticket_id: ticket.id, status: "UPLOADING", chunk_size_bytes: 8, total_chunks: 3,
  received_chunks: 2, received_chunk_indices: [0, 2], missing_chunk_indices: [1] };

beforeEach(() => {
  UploadRequest.instances = [];
  UploadRequest.pending = false;
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("resumable uploads", () => {
  it("proposes small parts but respects existing server chunk boundaries", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json(ticket)).mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(json({ id: "job-1" }));
    vi.stubGlobal("fetch", fetcher);
    await createJob(input, vi.fn());
    expect(JSON.parse(fetcher.mock.calls[1][1].body).chunk_size_bytes).toBe(512 * 1024);
    const data = UploadRequest.instances[0].send.mock.calls[0] as unknown as [FormData];
    expect((data[0].get("chunk") as Blob).size).toBe(8);
  });

  it("allows continued progress beyond two minutes, then expires a stalled response", async () => {
    vi.useFakeTimers();
    UploadRequest.pending = true;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(ticket)).mockResolvedValueOnce(json(session)));
    const controller = new AbortController();
    const request = createJob(input, vi.fn(), undefined, controller.signal);
    const rejected = expect(request).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(0);
    const xhr = UploadRequest.instances[0];
    expect(xhr.timeout).toBeGreaterThan(180_000);
    for (let loaded = 1; loaded <= 3; loaded++) {
      await vi.advanceTimersByTimeAsync(60_000);
      xhr.uploadListeners.progress({ loaded, lengthComputable: true });
      expect(xhr.abort).not.toHaveBeenCalled();
    }
    xhr.uploadListeners.load({ loaded: 3, lengthComputable: true });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(xhr.abort).toHaveBeenCalledOnce();
    controller.abort();
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not extend inactivity on duplicate progress events", async () => {
    vi.useFakeTimers();
    UploadRequest.pending = true;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(ticket)).mockResolvedValueOnce(json(session)));
    const controller = new AbortController();
    const request = createJob(input, vi.fn(), undefined, controller.signal);
    const rejected = expect(request).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(0);
    const xhr = UploadRequest.instances[0];
    xhr.uploadListeners.progress({ loaded: 1, lengthComputable: false });
    await vi.advanceTimersByTimeAsync(60_000);
    xhr.uploadListeners.progress({ loaded: 1, lengthComputable: false });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(xhr.abort).toHaveBeenCalledOnce();
    controller.abort();
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });
  it("sends only missing video chunks", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json(ticket)).mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(json({ id: "job-1" }));
    vi.stubGlobal("fetch", fetcher);
    await expect(createJob(input, vi.fn())).resolves.toMatchObject({ id: "job-1" });
    expect(UploadRequest.instances).toHaveLength(1);
    expect(UploadRequest.instances[0].open).toHaveBeenCalledWith("POST", "/api/v1/upload-tickets/ticket-1/chunks/part/1");
  });

  it("cancels an active chunk without finalizing, and reuses the submission on retry", async () => {
    UploadRequest.pending = true;
    const ids: string[] = [];
    const recoveredIds: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options: RequestInit) => {
      if (url.includes("by-submission")) { recoveredIds.push(url.split("/").at(-1)!); return json({}, 404); }
      if (url.endsWith("/upload-tickets/ticket-1")) return json(ticket);
      if (url.endsWith("/upload-tickets")) {
        ids.push(JSON.parse(String(options.body)).client_submission_id);
        return json(ticket);
      }
      if (url.endsWith("/start")) return json(session);
      return json({ id: "job-1" });
    }));
    const controller = new AbortController();
    const attempt = createJob(input, vi.fn(), undefined, controller.signal);
    const rejected = expect(attempt).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(UploadRequest.instances).toHaveLength(1));
    controller.abort();
    await rejected;
    expect(UploadRequest.instances[0].abort).toHaveBeenCalledOnce();
    UploadRequest.pending = false;
    await createJob(input, vi.fn());
    expect(ids).toHaveLength(1);
    expect(recoveredIds).toEqual(ids);
  });

  it("stops a stalled chunk after bounded retries", async () => {
    vi.useFakeTimers();
    UploadRequest.pending = true;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(ticket)).mockResolvedValueOnce(json(session)));
    const request = createJob(input, vi.fn());
    const rejected = expect(request).rejects.toMatchObject({ name: "ApiRequestError" });
    await vi.advanceTimersByTimeAsync(0);
    for (let attempt = 0; attempt < 3; attempt++) {
      expect(UploadRequest.instances[attempt].timeout).toBeGreaterThan(0);
      UploadRequest.instances[attempt].listeners.timeout();
      await vi.advanceTimersByTimeAsync(3000);
    }
    await rejected;
    expect(UploadRequest.instances).toHaveLength(3);
  });

  it("cancels while waiting for an upload slot", async () => {
    const controller = new AbortController();
    const fetcher = vi.fn().mockResolvedValue(json({ ...ticket, status: "WAITING" }));
    vi.stubGlobal("fetch", fetcher);
    const request = createJob(input, vi.fn(), () => controller.abort(), controller.signal);
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(UploadRequest.instances).toHaveLength(0);
  });

  it("times out a stalled upload session request", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener("abort", () => reject(new DOMException("Timed out", "AbortError")));
    })));
    const request = createJob(input, vi.fn());
    const rejected = expect(request).rejects.toMatchObject({ name: "ApiRequestError" });
    await vi.advanceTimersByTimeAsync(120_000);
    await rejected;
    expect(UploadRequest.instances).toHaveLength(0);
  });

  it("keeps cancellation active until the response body finishes", async () => {
    let bodyController: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({ start(controller) { bodyController = controller; } });
    const controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn(async (_url: string, options: RequestInit) => {
      options.signal?.addEventListener("abort", () => bodyController.error(new DOMException("Canceled", "AbortError")));
      return new Response(stream);
    }));
    let settled = false;
    const request = createUploadTicket({ videoName: "song.mp4", videoSizeBytes: 10 }, controller.signal)
      .catch(reason => { settled = true; return reason; });
    await new Promise(resolve => setTimeout(resolve, 0));
    controller.abort();
    await new Promise(resolve => setTimeout(resolve, 0));
    try { expect(settled).toBe(true); }
    finally { if (!settled) bodyController!.close(); }
    expect(await request).toMatchObject({ name: "AbortError" });
  });

  it("submits cloud rendering by uploaded ticket and retries an uncertain completion", async () => {
    const completions: FormData[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options: RequestInit) => {
      if (url.endsWith("/upload-tickets")) return json(ticket);
      if (url.endsWith("/start")) return json(session);
      if (url.endsWith("/cloud-render")) {
        completions.push(options.body as FormData);
        return completions.length === 1 ? json({}, 524) : json({ id: "job-1", stage: "CLOUD_RENDER_QUEUED" });
      }
      throw new Error(`Unexpected request ${url}`);
    }));
    await expect(submitCloudRender("job-1", video, { lines: [] }, vi.fn())).resolves.toMatchObject({ stage: "CLOUD_RENDER_QUEUED" });
    expect(completions).toHaveLength(2);
    expect(completions[0].get("upload_ticket_id")).toBe(ticket.id);
    expect(completions[0].get("video")).toBeNull();
    expect(UploadRequest.instances).toHaveLength(1);
  });
});
