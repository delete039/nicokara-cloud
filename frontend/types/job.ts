export type Job = {
  id: string;
  status: string;
  stage: string;
  progress: number;
  original_video_name: string;
  video_size_bytes: number;
  video_sha256: string;
  lyrics_source: "text" | "file" | null;
  vocal_mode?: "on" | "off";
  client_submission_id?: string | null;
  input_mode?: "VIDEO" | "AUDIO_ONLY";
  source_upload_size_bytes?: number | null;
  source_upload_sha256?: string | null;
  error_code: string | null;
  error_message: string | null;
  queue_position?: number | null;
  queue_size?: number | null;
  created_at: string;
  updated_at: string;
};

