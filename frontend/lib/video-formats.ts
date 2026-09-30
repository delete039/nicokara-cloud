export const SUPPORTED_VIDEO_EXTENSIONS = [
  ".mp4",
  ".m4v",
  ".mov",
  ".3gp",
  ".3g2",
  ".mkv",
  ".webm",
  ".avi",
  ".wmv",
  ".asf",
  ".flv",
  ".f4v",
  ".mpeg",
  ".mpg",
  ".mpe",
  ".m2v",
  ".ts",
  ".mts",
  ".m2ts",
  ".vob",
  ".ogv",
] as const;

export const SUPPORTED_VIDEO_ACCEPT = [
  "video/mp4",
  "video/x-m4v",
  "video/quicktime",
  "video/3gpp",
  "video/3gpp2",
  "video/x-matroska",
  "video/webm",
  "video/x-msvideo",
  "video/avi",
  "video/x-ms-wmv",
  "video/x-ms-asf",
  "video/x-flv",
  "video/x-f4v",
  "video/mpeg",
  "video/mp2t",
  "video/ogg",
  ...SUPPORTED_VIDEO_EXTENSIONS,
].join(",");

export const SUPPORTED_VIDEO_LABEL =
  "MP4、MOV、M4V、MKV、WebM、AVI、WMV、FLV、MPEG、TS、3GP、OGV";

export function isSupportedVideoName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  return SUPPORTED_VIDEO_EXTENSIONS.some((extension) =>
    normalized.endsWith(extension),
  );
}
