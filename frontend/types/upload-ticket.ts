export type UploadTicket = {
  id: string;
  status: "WAITING" | "READY" | "UPLOADING" | "COMPLETED" | "CANCELED" | "EXPIRED";
  video_name: string;
  video_size_bytes: number;
  client_submission_id?: string | null;
  job_id?: string | null;
  queue_position?: number | null;
  queue_size?: number | null;
  created_at: string;
  updated_at: string;
};
