export type ReviewedArtifactKind = "lyrics" | "timeline" | "subtitle";

export type ReviewedArtifactInspection = {
  files: File[];
  kinds: ReviewedArtifactKind[];
  requiresRemoteVideo: boolean;
};

const MAX_ARTIFACT_BYTES = 4 * 1024 * 1024;

function looksLikeSubtitle(text: string): boolean {
  return (
    text.includes("[Script Info]") &&
    text.includes("[V4+ Styles]") &&
    text.includes("[Events]") &&
    text.includes("Dialogue:")
  );
}

function classifyJson(value: unknown): ReviewedArtifactKind | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (
    typeof record.confidence === "number" &&
    Array.isArray(record.lines)
  ) {
    return "timeline";
  }
  if (
    typeof record.provider === "string" &&
    typeof record.source_text === "string" &&
    Array.isArray(record.lines)
  ) {
    return "lyrics";
  }
  return null;
}

async function classifyFile(file: File): Promise<ReviewedArtifactKind> {
  if (file.size > MAX_ARTIFACT_BYTES) {
    throw new Error(`${file.name} 超过 4 MB，无法作为调整数据导入`);
  }
  const text = (await file.text()).replace(/^\uFEFF/, "");
  if (!text.trim()) throw new Error(`${file.name} 是空文件`);
  if (looksLikeSubtitle(text)) return "subtitle";
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`${file.name} 不是本站导出的 JSON 或 ASS 文件`);
  }
  const kind = classifyJson(parsed);
  if (!kind) {
    throw new Error(
      `${file.name} 不是本站导出的调整后注音、mora 时间轴或 ASS 字幕`,
    );
  }
  return kind;
}

export async function inspectReviewedArtifactFiles(
  files: File[],
): Promise<ReviewedArtifactInspection> {
  if (files.length > 3) throw new Error("一次最多导入三个调整数据文件");
  const kinds: ReviewedArtifactKind[] = [];
  for (const file of files) {
    const kind = await classifyFile(file);
    if (kinds.includes(kind)) {
      throw new Error(`检测到重复的${kind === "lyrics" ? "注音" : kind === "timeline" ? "时间轴" : "ASS 字幕"}文件`);
    }
    kinds.push(kind);
  }
  return {
    files: [...files],
    kinds,
    requiresRemoteVideo: kinds.includes("subtitle"),
  };
}
