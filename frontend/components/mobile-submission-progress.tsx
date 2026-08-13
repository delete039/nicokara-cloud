import { CircleX } from "lucide-react";

import type { MobileSubmissionState } from "@/lib/mobile-submission";

const STAGE_COPY = {
  EXTRACTING_AUDIO: {
    title: "正在本地提取音频",
    detail: "视频不会上传，请保持页面打开。",
  },
  UPLOADING_AUDIO: {
    title: "正在上传音频",
    detail:
      "音频按 8 MiB 分片发送，单片失败会自动重试；再次选择同一素材可从缺失分片继续。原始视频保留在此设备。",
  },
  FALLBACK_VIDEO: {
    title: "已切换完整视频上传",
    detail: "当前音轨或浏览器不兼容本地提取，任务将使用原上传流程。",
  },
  UPLOADING_VIDEO: {
    title: "正在上传完整视频",
    detail: "本地音频提取不可用，正在使用兼容上传路径。",
  },
  COMPLETED: {
    title: "提交完成",
    detail: "任务已创建，正在打开任务状态页。",
  },
} satisfies Record<MobileSubmissionState["stage"], {
  title: string;
  detail: string;
}>;

export function MobileSubmissionProgress({
  state,
  onCancel,
}: {
  state: MobileSubmissionState;
  onCancel?: () => void;
}) {
  const copy = STAGE_COPY[state.stage];
  const cancelable =
    state.stage === "EXTRACTING_AUDIO" || state.stage === "UPLOADING_AUDIO";

  return (
    <div aria-live="polite">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span>{copy.title}</span>
        <span className="shrink-0 font-medium">{state.progress}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-[width]"
          style={{ width: `${state.progress}%` }}
        />
      </div>
      <div className="mt-2 flex items-start justify-between gap-3">
        <p className="text-xs leading-5 text-muted-foreground">{copy.detail}</p>
        {cancelable && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="focus-ring inline-flex shrink-0 items-center gap-1 rounded-sm text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            <CircleX className="size-3.5" />
            取消本地处理
          </button>
        )}
      </div>
    </div>
  );
}
