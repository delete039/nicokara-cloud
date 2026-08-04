import type { Job } from "@/types/job";
import {
  httpErrorFeedback,
  networkErrorFeedback,
  type ErrorContext,
  type ErrorFeedback,
} from "@/lib/error-feedback";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

type CreateJobInput = {
  video: File;
  lyricsText?: string;
  lyricsFile?: File;
  vocalMode?: string;
};

export class ApiRequestError extends Error {
  readonly feedback: ErrorFeedback;

  constructor(feedback: ErrorFeedback) {
    super(`${feedback.title}：${feedback.description}`);
    this.name = "ApiRequestError";
    this.feedback = feedback;
  }
}

function responseDetail(xhr: XMLHttpRequest): string | null {
  try {
    const body = JSON.parse(xhr.responseText) as { detail?: string };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return xhr.responseText?.trim() || null;
  }
}

function retryAfterSeconds(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number.parseInt(value, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : undefined;
}

function xhrRequestError(xhr: XMLHttpRequest): ApiRequestError {
  return new ApiRequestError(
    httpErrorFeedback(
      "upload",
      xhr.status,
      responseDetail(xhr),
      retryAfterSeconds(xhr.getResponseHeader("Retry-After")),
    ),
  );
}

async function fetchResponseDetail(response: Response): Promise<string | null> {
  const text = await response.text();
  if (!text.trim()) return response.statusText || null;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : text.trim();
  } catch {
    return text.trim();
  }
}

function connectionError(context: ErrorContext): ApiRequestError {
  return new ApiRequestError(networkErrorFeedback(context));
}

export function createJob(
  input: CreateJobInput,
  onProgress: (progress: number) => void,
): Promise<Job> {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    data.append("video", input.video);
    if (input.lyricsText?.trim()) {
      data.append("lyrics_text", input.lyricsText.trim());
    }
    if (input.lyricsFile) {
      data.append("lyrics_file", input.lyricsFile);
    }
    if (input.vocalMode) {
      data.append("vocal_mode", input.vocalMode);
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/jobs`);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as Job);
      } else {
        reject(xhrRequestError(xhr));
      }
    });
    xhr.addEventListener("error", () => {
      reject(connectionError("upload"));
    });
    xhr.addEventListener("abort", () => {
      reject(connectionError("upload"));
    });
    xhr.send(data);
  });
}

export async function getJob(jobId: string): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}`, {
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as Job;
}

export async function cancelJob(jobId: string): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/cancel`, {
      method: "POST",
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as Job;
}

export function transcriptUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/transcript`;
}

export function processedLyricsUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/lyrics`;
}

export function timelineUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/timeline`;
}

export function subtitleUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/subtitle`;
}

export function resultVideoUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/result`;
}

export function downloadVideoUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/download`;
}
