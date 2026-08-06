const localVideos = new Map<string, File>();

export function rememberLocalVideo(jobId: string, video: File): void {
  localVideos.set(jobId, video);
}

export function getLocalVideo(jobId: string): File | null {
  return localVideos.get(jobId) ?? null;
}

export function forgetLocalVideo(jobId: string): void {
  localVideos.delete(jobId);
}

export function clearLocalMediaSessions(): void {
  localVideos.clear();
}
