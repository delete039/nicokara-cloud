"use client";

import {
  Activity,
  CircleX,
  Cpu,
  Eye,
  HardDrive,
  ListVideo,
  LoaderCircle,
  LogOut,
  MemoryStick,
  Radio,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Upload,
  Users,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { AdminSectionNav } from "@/components/admin-section-nav";
import {
  AdminApiError,
  cancelAdminJob,
  cancelAdminUploadTicket,
  getAdminOverview,
  requeueAdminJob,
} from "@/services/admin-api";
import type { AdminOverview } from "@/types/admin";


const SESSION_TOKEN_KEY = "nicokara-admin-token";


function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "不可用";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
}


function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
}


function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}


function count(values: Record<string, number>, status: string): number {
  return values[status] ?? 0;
}


type AdminDashboardViewProps = {
  overview: AdminOverview;
  pendingAction: string | null;
  onCancelUpload: (ticketId: string) => void;
  onCancelJob: (jobId: string) => void;
  onRequeueJob: (jobId: string) => void;
};


export function AdminDashboardView({
  overview,
  pendingAction,
  onCancelUpload,
  onCancelJob,
  onRequeueJob,
}: AdminDashboardViewProps) {
  const memory = overview.resources.memory;
  const disk = overview.resources.disk;
  const load = overview.resources.load_average;
  const trafficScale = Math.max(
    1,
    ...overview.traffic.periods.flatMap((period) => [period.pageviews, period.visits]),
  );
  const trafficStats = [
    { label: "近 24 小时浏览", value: overview.traffic.pageviews_24h.toLocaleString("zh-CN"), detail: "Pageviews", icon: Eye },
    { label: "近 24 小时访问", value: overview.traffic.visits_24h.toLocaleString("zh-CN"), detail: "Visits", icon: Users },
    { label: "近 5 分钟活跃", value: overview.traffic.active_visits.toLocaleString("zh-CN"), detail: "访问会话", icon: Radio },
    { label: "平均浏览深度", value: overview.traffic.pages_per_visit.toFixed(2), detail: "页 / 次访问", icon: Activity },
  ];

  return (
    <div className="space-y-8">
      <section className="grid border-y bg-card sm:grid-cols-2 lg:grid-cols-6">
        {[
          ["等待上传", count(overview.upload_counts, "WAITING")],
          ["已获上传名额", count(overview.upload_counts, "READY")],
          ["正在上传", count(overview.upload_counts, "UPLOADING")],
          ["等待处理", count(overview.job_counts, "UPLOADED")],
          ["正在处理", count(overview.job_counts, "PROCESSING")],
          ["最近失败", count(overview.job_counts, "FAILED")],
        ].map(([label, value]) => (
          <div key={label} className="border-b p-4 last:border-b-0 sm:border-r lg:border-b-0">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
          </div>
        ))}
      </section>

      <section aria-labelledby="traffic-heading" className="border-y bg-card py-5">
        <div className="flex flex-wrap items-end justify-between gap-3 px-4 sm:px-5">
          <div>
            <div className="flex items-center gap-2">
              <Activity className="size-5 text-primary" />
              <h2 id="traffic-heading" className="text-lg font-semibold">访问分析</h2>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatTime(overview.traffic.tracking_started_at)} 至今 · 每 5 秒自动更新
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-primary" />Page Views</span>
            <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-emerald-500" />Visits</span>
          </div>
        </div>

        <div className="mt-5 grid border-y sm:grid-cols-2">
          <div className="border-b p-4 sm:border-b-0 sm:border-r sm:p-5">
            <p className="flex items-center gap-2 text-sm font-semibold"><Eye className="size-4 text-primary" />Page Views summary</p>
            <p className="mt-3 text-3xl font-bold tabular-nums">{overview.traffic.pageviews.toLocaleString("zh-CN")}</p>
            <p className="mt-1 text-xs text-muted-foreground">浏览器完成页面加载的累计次数</p>
          </div>
          <div className="p-4 sm:p-5">
            <p className="flex items-center gap-2 text-sm font-semibold"><Users className="size-4 text-emerald-600" />Visits summary</p>
            <p className="mt-3 text-3xl font-bold tabular-nums">{overview.traffic.visits.toLocaleString("zh-CN")}</p>
            <p className="mt-1 text-xs text-muted-foreground">一次访问可包含多个页面浏览</p>
          </div>
        </div>

        <div className="px-4 py-5 sm:px-5">
          <h3 className="text-sm font-semibold">访问趋势</h3>
          <div className="mt-4 space-y-5" aria-label="Page Views 与 Visits 分期趋势">
            {overview.traffic.periods.map((period) => (
              <div key={period.key} data-traffic-period={period.key}>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                  <span className="font-medium">{period.label}</span>
                  <span className="text-muted-foreground">
                    {period.source.startsWith("Cloudflare") ? "Cloudflare 历史数据" : "Nicokara 实时数据"}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-[5rem_minmax(0,1fr)_5rem] items-center gap-2 text-xs">
                  <span className="text-muted-foreground">Page Views</span>
                  <div className="h-2 overflow-hidden rounded-sm bg-muted">
                    <div className="h-full rounded-sm bg-primary" style={{ width: `${(period.pageviews / trafficScale) * 100}%` }} />
                  </div>
                  <span className="text-right font-semibold tabular-nums">{period.pageviews.toLocaleString("zh-CN")}</span>
                  <span className="text-muted-foreground">Visits</span>
                  <div className="h-2 overflow-hidden rounded-sm bg-muted">
                    <div className="h-full rounded-sm bg-emerald-500" style={{ width: `${(period.visits / trafficScale) * 100}%` }} />
                  </div>
                  <span className="text-right font-semibold tabular-nums">{period.visits.toLocaleString("zh-CN")}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-px overflow-hidden border-t bg-border sm:grid-cols-2 lg:grid-cols-4">
          {trafficStats.map(({ label, value, detail, icon: Icon }) => (
            <div key={label} className="bg-card p-4">
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Icon className="size-4" />{label}
              </p>
              <p className="mt-2 text-2xl font-bold tabular-nums">{value}</p>
              <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
            </div>
          ))}
        </div>
        <p className="px-4 pt-3 text-xs text-muted-foreground sm:px-5">
          统计起始：{formatTime(overview.traffic.tracking_started_at)} · 历史 PDF 汇总与实时记录已合并，数据持久保存
        </p>
      </section>

      <section aria-labelledby="runtime-heading">
        <div className="flex items-center gap-2">
          <Activity className="size-5 text-primary" />
          <h2 id="runtime-heading" className="text-lg font-semibold">运行状态</h2>
        </div>
        <div className="mt-3 grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2 lg:grid-cols-4">
          <div className="bg-card p-4">
            <p className="text-xs text-muted-foreground">Worker</p>
            <p className={`mt-2 font-semibold ${overview.runner.healthy ? "text-emerald-700" : "text-destructive"}`}>
              {overview.runner.healthy ? "Worker 正常" : "Worker 异常"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {overview.runner.alive_workers ?? 0} / {overview.runner.worker_count ?? 0} 存活
            </p>
          </div>
          <div className="bg-card p-4">
            <p className="flex items-center gap-2 text-xs text-muted-foreground"><Cpu className="size-4" />CPU</p>
            <p className="mt-2 font-semibold">{overview.resources.cpu_count ?? "-"} 核</p>
            <p className="mt-1 text-xs text-muted-foreground">1 分钟负载 {load?.one_minute?.toFixed(2) ?? "-"}</p>
          </div>
          <div className="bg-card p-4">
            <p className="flex items-center gap-2 text-xs text-muted-foreground"><MemoryStick className="size-4" />内存使用</p>
            <p className="mt-2 font-semibold">{formatBytes(memory?.used_bytes)}</p>
            <p className="mt-1 text-xs text-muted-foreground">总计 {formatBytes(memory?.total_bytes)}</p>
          </div>
          <div className="bg-card p-4">
            <p className="flex items-center gap-2 text-xs text-muted-foreground"><HardDrive className="size-4" />磁盘可用</p>
            <p className="mt-2 font-semibold">{formatBytes(disk?.free_bytes)}</p>
            <p className="mt-1 text-xs text-muted-foreground">总计 {formatBytes(disk?.total_bytes)}</p>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          心跳：{formatTime(overview.runner.last_heartbeat_at)} · 内存队列：{overview.runner.queued_in_memory ?? "-"}
        </p>
      </section>

      <section aria-labelledby="upload-queue-heading">
        <div className="flex items-center gap-2">
          <Upload className="size-5 text-primary" />
          <h2 id="upload-queue-heading" className="text-lg font-semibold">上传队列</h2>
        </div>
        <div className="mt-3 overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b bg-muted/70 text-xs text-muted-foreground">
              <tr><th className="p-3">状态</th><th className="p-3">位置</th><th className="p-3">文件</th><th className="p-3">大小</th><th className="p-3">最后心跳</th><th className="p-3 text-right">操作</th></tr>
            </thead>
            <tbody>
              {overview.upload_tickets.map((ticket) => (
                <tr key={ticket.id} className="border-b last:border-b-0">
                  <td className="p-3 font-medium">{ticket.status}</td>
                  <td className="p-3 tabular-nums">{ticket.queue_position ? `第 ${ticket.queue_position} 位` : "-"}</td>
                  <td className="max-w-64 truncate p-3" title={ticket.video_name}>{ticket.video_name}</td>
                  <td className="p-3 tabular-nums">{formatBytes(ticket.video_size_bytes)}</td>
                  <td className="p-3 text-xs text-muted-foreground">{formatTime(ticket.last_seen_at)}</td>
                  <td className="p-3 text-right">
                    <button type="button" title="取消上传票据" aria-label={`取消 ${ticket.video_name}`} disabled={pendingAction === `upload:${ticket.id}`} onClick={() => onCancelUpload(ticket.id)} className="focus-ring inline-flex size-9 items-center justify-center rounded-lg border text-destructive hover:bg-destructive/10 disabled:opacity-50">
                      {pendingAction === `upload:${ticket.id}` ? <LoaderCircle className="size-4 animate-spin" /> : <CircleX className="size-4" />}
                    </button>
                  </td>
                </tr>
              ))}
              {overview.upload_tickets.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-muted-foreground">当前没有活跃上传</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="job-queue-heading">
        <div className="flex items-center gap-2">
          <ListVideo className="size-5 text-primary" />
          <h2 id="job-queue-heading" className="text-lg font-semibold">处理队列</h2>
        </div>
        <div className="mt-3 overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="border-b bg-muted/70 text-xs text-muted-foreground">
              <tr><th className="p-3">状态</th><th className="p-3">阶段</th><th className="p-3">进度</th><th className="p-3">文件</th><th className="p-3">阶段耗时</th><th className="p-3">错误</th><th className="p-3 text-right">操作</th></tr>
            </thead>
            <tbody>
              {overview.jobs.map((job) => (
                <tr key={job.id} className="border-b last:border-b-0">
                  <td className="p-3 font-medium">{job.status}</td>
                  <td className="p-3 font-mono text-xs">{job.stage}</td>
                  <td className="p-3 tabular-nums">{job.progress}%</td>
                  <td className="max-w-56 truncate p-3" title={job.original_video_name}>{job.original_video_name}</td>
                  <td className="p-3 tabular-nums">{formatDuration(job.stage_age_seconds)}</td>
                  <td className="max-w-56 truncate p-3 text-xs text-destructive" title={job.error_message ?? ""}>{job.error_code ?? "-"}</td>
                  <td className="p-3 text-right">
                    {job.status === "FAILED" ? (
                      <button type="button" disabled={pendingAction === `job:${job.id}`} onClick={() => onRequeueJob(job.id)} className="focus-ring inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs font-semibold hover:bg-muted disabled:opacity-50"><RotateCcw className="size-4" />重新入队</button>
                    ) : (
                      <button type="button" title="取消任务" aria-label={`取消 ${job.original_video_name}`} disabled={pendingAction === `job:${job.id}`} onClick={() => onCancelJob(job.id)} className="focus-ring inline-flex size-9 items-center justify-center rounded-lg border text-destructive hover:bg-destructive/10 disabled:opacity-50"><CircleX className="size-4" /></button>
                    )}
                  </td>
                </tr>
              ))}
              {overview.jobs.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-muted-foreground">当前没有等待、处理或失败任务</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="audit-heading">
        <h2 id="audit-heading" className="text-lg font-semibold">管理员操作记录</h2>
        <div className="mt-3 overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b bg-muted/70 text-xs text-muted-foreground"><tr><th className="p-3">时间</th><th className="p-3">操作</th><th className="p-3">目标</th><th className="p-3">结果</th></tr></thead>
            <tbody>
              {overview.audit_events.map((event) => <tr key={event.id} className="border-b last:border-b-0"><td className="p-3 text-xs text-muted-foreground">{formatTime(event.created_at)}</td><td className="p-3">{event.action}</td><td className="max-w-64 truncate p-3 font-mono text-xs" title={event.target_id}>{event.target_id}</td><td className="p-3">{event.outcome}</td></tr>)}
              {overview.audit_events.length === 0 && <tr><td colSpan={4} className="p-8 text-center text-muted-foreground">暂无管理员操作</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}


export default function AdminPage() {
  const [tokenInput, setTokenInput] = useState("");
  const [token, setToken] = useState("");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const stored = sessionStorage.getItem(SESSION_TOKEN_KEY) ?? "";
      setToken(stored);
      setTokenInput(stored);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const load = useCallback(async (adminToken: string) => {
    if (!adminToken) return;
    setLoading(true);
    try {
      setOverview(await getAdminOverview(adminToken));
      setError(null);
    } catch (reason) {
      const message = reason instanceof AdminApiError ? reason.message : "后台监控刷新失败。";
      setError(message);
      if (reason instanceof AdminApiError && reason.status === 401) {
        sessionStorage.removeItem(SESSION_TOKEN_KEY);
        setToken("");
        setOverview(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    const initialRefresh = window.setTimeout(() => void load(token), 0);
    const refreshInterval = window.setInterval(() => void load(token), 5_000);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(refreshInterval);
    };
  }, [load, token]);

  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = tokenInput.trim();
    if (!value) return;
    sessionStorage.setItem(SESSION_TOKEN_KEY, value);
    setToken(value);
  }

  function logout() {
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
    setToken("");
    setTokenInput("");
    setOverview(null);
    setError(null);
  }

  async function runAction(key: string, action: () => Promise<unknown>) {
    if (!token) return;
    setPendingAction(key);
    try {
      await action();
      await load(token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "管理员操作失败。");
    } finally {
      setPendingAction(null);
    }
  }

  if (!token) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-5 py-12">
        <form onSubmit={connect} className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
          <ShieldCheck className="size-8 text-primary" />
          <h1 className="mt-4 text-2xl font-bold">管理员监控</h1>
          <label htmlFor="admin-token" className="mt-6 block text-sm font-medium">管理员令牌</label>
          <input id="admin-token" type="password" autoComplete="current-password" value={tokenInput} onChange={(event) => setTokenInput(event.target.value)} className="focus-ring mt-2 min-h-11 w-full rounded-lg border bg-background px-3" />
          {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
          <button type="submit" className="focus-ring mt-5 min-h-11 w-full rounded-lg bg-primary px-4 font-semibold text-primary-foreground">进入监控</button>
        </form>
      </main>
    );
  }

  return (
    <main className="min-h-dvh pb-12">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div><p className="text-xs text-muted-foreground">NICOKARA CLOUD</p><h1 className="text-xl font-bold">管理员监控</h1></div>
          <div className="flex gap-2">
            <button type="button" title="立即刷新" aria-label="立即刷新" disabled={loading} onClick={() => void load(token)} className="focus-ring inline-flex size-10 items-center justify-center rounded-lg border hover:bg-muted disabled:opacity-50"><RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} /></button>
            <button type="button" title="退出管理员监控" aria-label="退出管理员监控" onClick={logout} className="focus-ring inline-flex size-10 items-center justify-center rounded-lg border hover:bg-muted"><LogOut className="size-4" /></button>
          </div>
        </div>
        <div className="mx-auto max-w-[1500px] px-5 sm:px-8">
          <AdminSectionNav active="monitor" />
        </div>
      </header>
      <div className="mx-auto max-w-[1500px] px-5 pt-6 sm:px-8">
        {error && <div role="alert" className="mb-5 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}
        {overview ? (
          <AdminDashboardView
            overview={overview}
            pendingAction={pendingAction}
            onCancelUpload={(id) => void runAction(`upload:${id}`, () => cancelAdminUploadTicket(token, id))}
            onCancelJob={(id) => void runAction(`job:${id}`, () => cancelAdminJob(token, id))}
            onRequeueJob={(id) => void runAction(`job:${id}`, () => requeueAdminJob(token, id))}
          />
        ) : loading ? (
          <div className="flex items-center justify-center gap-3 py-24 text-muted-foreground"><LoaderCircle className="size-5 animate-spin" />读取监控数据</div>
        ) : (
          <div className="py-24 text-center text-sm text-muted-foreground">监控数据尚未载入，请检查上方提示后重试。</div>
        )}
      </div>
    </main>
  );
}
