export type KirakaraExportProfile = {
  codec: string;
  width: number;
  height: number;
  framerate: number;
  bitrate: number;
};

export type KirakaraCapabilities = {
  preview: true;
  export: boolean;
  reason?: "WEBCODECS_UNAVAILABLE" | "H264_UNSUPPORTED";
  profile: KirakaraExportProfile | null;
};

type WebCodecsScope = {
  VideoEncoder?: {
    isConfigSupported?: (
      config: KirakaraExportProfile,
    ) => Promise<{ supported?: boolean }>;
  };
  VideoDecoder?: unknown;
  VideoFrame?: unknown;
};

export async function detectKirakaraCapabilities(
  scope: WebCodecsScope = globalThis as WebCodecsScope,
  mobile = false,
): Promise<KirakaraCapabilities> {
  const encoder = scope.VideoEncoder;
  if (
    !encoder?.isConfigSupported ||
    !scope.VideoDecoder ||
    !scope.VideoFrame
  ) {
    return {
      preview: true,
      export: false,
      reason: "WEBCODECS_UNAVAILABLE",
      profile: null,
    };
  }

  const profile: KirakaraExportProfile = mobile
    ? {
        codec: "avc1.42E01E",
        width: 1280,
        height: 720,
        framerate: 30,
        bitrate: 4_000_000,
      }
    : {
        codec: "avc1.640028",
        width: 1920,
        height: 1080,
        framerate: 30,
        bitrate: 8_000_000,
      };
  const result = await encoder.isConfigSupported(profile);
  return result.supported
    ? { preview: true, export: true, profile }
    : {
        preview: true,
        export: false,
        reason: "H264_UNSUPPORTED",
        profile: null,
      };
}

export function kirakaraSupportMessage(
  capabilities: KirakaraCapabilities,
): string {
  if (capabilities.export) {
    return "本地导出能力检测通过；推荐使用最新版桌面 Chrome 或 Edge。";
  }
  const reason = capabilities.reason === "H264_UNSUPPORTED"
    ? "当前设备无法使用所需的 H.264 编码配置。"
    : "当前浏览器未开放完整的 WebCodecs 视频编解码能力。";
  return `${reason} 推荐最新版桌面 Chrome 或 Edge、Android Chrome；Safari 和 iOS 的实际能力取决于系统版本。你仍可点击云端渲染，由服务器完成视频嵌字。`;
}
