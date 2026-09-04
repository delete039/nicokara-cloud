const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";


export function normalizedAnalyticsPath(pathname: string): string | null {
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return null;
  if (pathname.startsWith("/jobs/")) return "/jobs/:jobId";
  return pathname.slice(0, 128) || "/";
}


export async function recordPageview(path: string): Promise<void> {
  await fetch(`${API_BASE}/analytics/pageview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
    cache: "no-store",
    credentials: "same-origin",
    keepalive: true,
  });
}
