"use client";

import {
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  LogOut,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { AdminSectionNav } from "@/components/admin-section-nav";
import { AdminApiError, getAdminLogs } from "@/services/admin-api";
import type {
  AdminLogFilters,
  AdminLogItem,
  AdminLogsResponse,
} from "@/types/admin";


const SESSION_TOKEN_KEY = "nicokara-admin-token";
const PAGE_SIZE = 50;
const EMPTY_FILTERS: AdminLogFilters = {
  level: "",
  category: "",
  referenceId: "",
  query: "",
};


function formatTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}


function levelClass(level: string): string {
  if (level === "ERROR") return "text-destructive";
  if (level === "WARNING") return "text-amber-700";
  return "text-foreground";
}


function LogDetails({ item }: { item: AdminLogItem }) {
  if (Object.keys(item.details).length === 0) return <span className="text-muted-foreground">-</span>;
  return (
    <details>
      <summary className="cursor-pointer text-xs font-medium text-primary">查看</summary>
      <pre className="mt-2 max-w-80 overflow-x-auto whitespace-pre-wrap break-all text-xs leading-5 text-muted-foreground">
        {JSON.stringify(item.details, null, 2)}
      </pre>
    </details>
  );
}


type AdminLogsViewProps = {
  response: AdminLogsResponse;
  loading: boolean;
  page: number;
  onPageChange: (page: number) => void;
  filters?: AdminLogFilters;
  onFiltersChange?: (filters: AdminLogFilters) => void;
  onApplyFilters?: () => void;
};


export function AdminLogsView({
  response,
  loading,
  page,
  onPageChange,
  filters = EMPTY_FILTERS,
  onFiltersChange = () => undefined,
  onApplyFilters = () => undefined,
}: AdminLogsViewProps) {
  const pageCount = Math.max(1, Math.ceil(response.total / response.limit));
  const updateFilter = (key: keyof AdminLogFilters, value: string) => {
    onFiltersChange({ ...filters, [key]: value });
  };

  return (
    <div className="space-y-5">
      <form
        className="grid gap-3 border-y bg-card py-4 sm:grid-cols-2 xl:grid-cols-[10rem_10rem_minmax(12rem,1fr)_minmax(12rem,1fr)_auto] xl:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          onApplyFilters();
        }}
      >
        <label className="text-xs font-medium text-muted-foreground">
          日志级别
          <select value={filters.level ?? ""} onChange={(event) => updateFilter("level", event.target.value)} className="focus-ring mt-1 block min-h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground">
            <option value="">全部级别</option>
            <option value="ERROR">错误</option>
            <option value="WARNING">警告</option>
            <option value="INFO">信息</option>
          </select>
        </label>
        <label className="text-xs font-medium text-muted-foreground">
          事件分类
          <select value={filters.category ?? ""} onChange={(event) => updateFilter("category", event.target.value)} className="focus-ring mt-1 block min-h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground">
            <option value="">全部分类</option>
            <option value="task">任务</option>
            <option value="upload">上传</option>
            <option value="admin">管理员</option>
            <option value="system">系统</option>
          </select>
        </label>
        <label className="text-xs font-medium text-muted-foreground">
          任务或上传 ID
          <input value={filters.referenceId ?? ""} onChange={(event) => updateFilter("referenceId", event.target.value)} className="focus-ring mt-1 block min-h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground" />
        </label>
        <label className="text-xs font-medium text-muted-foreground">
          关键词
          <input value={filters.query ?? ""} onChange={(event) => updateFilter("query", event.target.value)} className="focus-ring mt-1 block min-h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground" />
        </label>
        <button type="submit" disabled={loading} className="focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          <Search className="size-4" aria-hidden="true" />筛选
        </button>
      </form>

      <div className="overflow-x-auto border-y bg-card">
        <table className="w-full min-w-[1120px] text-left text-sm">
          <thead className="border-b bg-muted/70 text-xs text-muted-foreground">
            <tr>
              <th className="p-3">时间</th>
              <th className="p-3">级别</th>
              <th className="p-3">分类</th>
              <th className="p-3">事件</th>
              <th className="p-3">关联 ID</th>
              <th className="p-3">消息</th>
              <th className="p-3">详情</th>
            </tr>
          </thead>
          <tbody>
            {response.items.map((item) => (
              <tr key={item.id} className="border-b align-top last:border-b-0">
                <td className="whitespace-nowrap p-3 text-xs text-muted-foreground">{formatTime(item.created_at)}</td>
                <td className={`p-3 font-semibold ${levelClass(item.level)}`}>{item.level}</td>
                <td className="p-3">{item.category}</td>
                <td className="p-3 font-mono text-xs">{item.event}</td>
                <td className="max-w-56 break-all p-3 font-mono text-xs">{item.reference_id ?? "-"}</td>
                <td className="max-w-80 break-words p-3">{item.message}</td>
                <td className="p-3"><LogDetails item={item} /></td>
              </tr>
            ))}
            {response.items.length === 0 && (
              <tr><td colSpan={7} className="p-12 text-center text-muted-foreground">没有符合条件的日志</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">共 {response.total} 条 · 第 {page} / {pageCount} 页</p>
        <div className="flex gap-2">
          <button type="button" title="上一页" aria-label="上一页" disabled={loading || page <= 1} onClick={() => onPageChange(page - 1)} className="focus-ring inline-flex size-10 items-center justify-center rounded-md border hover:bg-muted disabled:opacity-40"><ChevronLeft className="size-4" /></button>
          <button type="button" title="下一页" aria-label="下一页" disabled={loading || page >= pageCount} onClick={() => onPageChange(page + 1)} className="focus-ring inline-flex size-10 items-center justify-center rounded-md border hover:bg-muted disabled:opacity-40"><ChevronRight className="size-4" /></button>
        </div>
      </div>
    </div>
  );
}


export default function AdminLogsPage() {
  const [tokenInput, setTokenInput] = useState("");
  const [token, setToken] = useState("");
  const [response, setResponse] = useState<AdminLogsResponse | null>(null);
  const [draftFilters, setDraftFilters] = useState<AdminLogFilters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<AdminLogFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const stored = sessionStorage.getItem(SESSION_TOKEN_KEY) ?? "";
      setToken(stored);
      setTokenInput(stored);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const load = useCallback(async (
    adminToken: string,
    activeFilters: AdminLogFilters,
    activePage: number,
  ) => {
    if (!adminToken) return;
    setLoading(true);
    try {
      setResponse(await getAdminLogs(adminToken, {
        ...activeFilters,
        limit: PAGE_SIZE,
        offset: (activePage - 1) * PAGE_SIZE,
      }));
      setError(null);
    } catch (reason) {
      setError(reason instanceof AdminApiError ? reason.message : "管理员日志读取失败。");
      if (reason instanceof AdminApiError && reason.status === 401) {
        sessionStorage.removeItem(SESSION_TOKEN_KEY);
        setToken("");
        setResponse(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    const timer = window.setTimeout(() => void load(token, filters, page), 0);
    return () => window.clearTimeout(timer);
  }, [filters, load, page, token]);

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
    setResponse(null);
    setError(null);
  }

  if (!token) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-5 py-12">
        <form onSubmit={connect} className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
          <ShieldCheck className="size-8 text-primary" />
          <h1 className="mt-4 text-2xl font-bold">管理员日志</h1>
          <label htmlFor="admin-log-token" className="mt-6 block text-sm font-medium">管理员令牌</label>
          <input id="admin-log-token" type="password" autoComplete="current-password" value={tokenInput} onChange={(event) => setTokenInput(event.target.value)} className="focus-ring mt-2 min-h-11 w-full rounded-lg border bg-background px-3" />
          {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
          <button type="submit" className="focus-ring mt-5 min-h-11 w-full rounded-lg bg-primary px-4 font-semibold text-primary-foreground">进入日志</button>
        </form>
      </main>
    );
  }

  return (
    <main className="min-h-dvh pb-12">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div><p className="text-xs text-muted-foreground">NICOKARA CLOUD</p><h1 className="text-xl font-bold">管理员日志</h1></div>
          <div className="flex gap-2">
            <button type="button" title="立即刷新" aria-label="立即刷新" disabled={loading} onClick={() => void load(token, filters, page)} className="focus-ring inline-flex size-10 items-center justify-center rounded-md border hover:bg-muted disabled:opacity-50"><RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} /></button>
            <button type="button" title="退出管理员日志" aria-label="退出管理员日志" onClick={logout} className="focus-ring inline-flex size-10 items-center justify-center rounded-md border hover:bg-muted"><LogOut className="size-4" /></button>
          </div>
        </div>
        <div className="mx-auto max-w-[1500px] px-5 sm:px-8">
          <AdminSectionNav active="logs" />
        </div>
      </header>
      <div className="mx-auto max-w-[1500px] px-5 pt-6 sm:px-8">
        {error && <div role="alert" className="mb-5 border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}
        {response ? (
          <AdminLogsView
            response={response}
            loading={loading}
            page={page}
            onPageChange={setPage}
            filters={draftFilters}
            onFiltersChange={setDraftFilters}
            onApplyFilters={() => {
              setPage(1);
              setFilters({
                level: draftFilters.level?.trim(),
                category: draftFilters.category?.trim(),
                referenceId: draftFilters.referenceId?.trim(),
                query: draftFilters.query?.trim(),
              });
            }}
          />
        ) : loading ? (
          <div className="flex items-center justify-center gap-3 py-24 text-muted-foreground"><LoaderCircle className="size-5 animate-spin" />读取日志</div>
        ) : (
          <div className="py-24 text-center text-sm text-muted-foreground">日志尚未载入，请检查上方提示后重试。</div>
        )}
      </div>
    </main>
  );
}
