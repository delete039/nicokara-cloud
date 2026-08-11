export type AdminUploadTicket = {
  id: string;
  status: string;
  video_name: string;
  video_size_bytes: number;
  job_id: string | null;
  created_at: string;
  updated_at: string;
  last_seen_at: string;
  queue_position: number | null;
  queue_size: number | null;
};

export type AdminJob = {
  id: string;
  status: string;
  stage: string;
  progress: number;
  original_video_name: string;
  video_size_bytes: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  stage_age_seconds: number;
};

export type AdminRunner = {
  healthy: boolean;
  worker_count: number | null;
  alive_workers: number | null;
  queued_in_memory: number | null;
  last_heartbeat_at: string | null;
  active_jobs: Array<{
    worker_index: number;
    job_id: string;
    started_at: string;
  }>;
};

export type AdminResources = {
  cpu_count?: number | null;
  load_average?: {
    one_minute: number | null;
    five_minutes: number | null;
    fifteen_minutes: number | null;
  };
  memory?: {
    total_bytes: number | null;
    available_bytes: number | null;
    used_bytes: number | null;
  };
  disk?: {
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
  };
};

export type AdminAuditEvent = {
  id: number;
  action: string;
  target_type: string;
  target_id: string;
  outcome: string;
  details: string | null;
  created_at: string;
};

export type AdminOverview = {
  generated_at: string;
  upload_counts: Record<string, number>;
  job_counts: Record<string, number>;
  upload_tickets: AdminUploadTicket[];
  jobs: AdminJob[];
  runner: AdminRunner;
  resources: AdminResources;
  audit_events: AdminAuditEvent[];
};

export type AdminAction = {
  id: string;
  status: string;
};

export type AdminLogItem = {
  id: number;
  level: string;
  category: string;
  event: string;
  message: string;
  reference_type: string | null;
  reference_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type AdminLogsResponse = {
  items: AdminLogItem[];
  total: number;
  limit: number;
  offset: number;
};

export type AdminLogFilters = {
  level?: string;
  category?: string;
  referenceId?: string;
  query?: string;
  limit?: number;
  offset?: number;
};
