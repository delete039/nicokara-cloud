import type { AdminAction, AdminOverview } from "@/types/admin";


const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";


export class AdminApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
  }
}


async function adminRequest<T>(
  token: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        ...init.headers,
        Authorization: `Bearer ${token}`,
      },
    });
  } catch {
    throw new AdminApiError(0, "无法连接后台监控接口。");
  }

  if (!response.ok) {
    let detail = response.statusText || "请求失败";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the HTTP status text when the response is not JSON.
    }
    throw new AdminApiError(response.status, detail);
  }
  return (await response.json()) as T;
}


export function getAdminOverview(token: string): Promise<AdminOverview> {
  return adminRequest<AdminOverview>(token, "/admin/overview");
}


export function cancelAdminUploadTicket(
  token: string,
  ticketId: string,
): Promise<AdminAction> {
  return adminRequest<AdminAction>(
    token,
    `/admin/upload-tickets/${ticketId}/cancel`,
    { method: "POST" },
  );
}


export function cancelAdminJob(
  token: string,
  jobId: string,
): Promise<AdminAction> {
  return adminRequest<AdminAction>(token, `/admin/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}


export function requeueAdminJob(
  token: string,
  jobId: string,
): Promise<AdminAction> {
  return adminRequest<AdminAction>(token, `/admin/jobs/${jobId}/requeue`, {
    method: "POST",
  });
}
