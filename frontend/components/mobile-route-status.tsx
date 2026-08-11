import { CloudUpload, Cpu, Music2 } from "lucide-react";

import type { MobileProcessingRoute } from "@/lib/mobile-processing";

const ROUTE_STATUS = {
  LOCAL: {
    icon: Cpu,
    title: "本地处理",
    detail: "素材保留在当前设备，本地素材上限 300 MB。",
  },
  AUDIO_ONLY: {
    icon: Music2,
    title: "仅上传音频",
    detail: "视频保留在当前设备，仅发送音频与歌词；服务器使用 UVR 与 FA-Kara 对齐，本地素材上限 300 MB。",
  },
  REMOTE_VIDEO: {
    icon: CloudUpload,
    title: "完整视频上传",
    detail: "当前浏览器使用远端兼容路径；浏览器本地处理的素材上限为 300 MB。",
  },
} satisfies Record<
  MobileProcessingRoute,
  { icon: typeof Cpu; title: string; detail: string }
>;

export function MobileRouteStatus({
  route,
}: {
  route: MobileProcessingRoute;
}) {
  const status = ROUTE_STATUS[route];
  return (
    <div
      role="status"
      className="mt-3 flex items-start gap-3 border-l-2 border-primary px-3 py-1.5 text-sm"
    >
      <status.icon className="mt-0.5 size-4 shrink-0 text-primary" />
      <div className="min-w-0">
        <p className="font-medium">{status.title}</p>
        <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
          {status.detail}
        </p>
      </div>
    </div>
  );
}
