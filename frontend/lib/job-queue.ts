export function queueStatusLabel(
  position: number | null | undefined,
  size: number | null | undefined,
): string | null {
  if (!position || position < 1 || !size || size < 1) return null;
  return `当前排在第 ${position} 位，队列中共有 ${size} 个等待任务。`;
}

export function canCancelJob(status: string): boolean {
  return status === "UPLOADED" || status === "PROCESSING";
}

export function cancelJobLabel(status: string): string | null {
  if (status === "UPLOADED") return "退出排队";
  if (status === "PROCESSING") return "取消生成";
  return null;
}

export function jobPollDelay(
  status: string,
  consecutiveErrors: number,
  hidden: boolean,
): number {
  if (hidden) return 15000;
  if (consecutiveErrors > 0) {
    return Math.min(5000 * 2 ** (consecutiveErrors - 1), 30000);
  }
  return status === "UPLOADED" ? 4000 : 2000;
}
