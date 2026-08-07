import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { KirakaraProjectDownload } from "./kirakara-project-download";

describe("KirakaraProjectDownload", () => {
  it("replaces the legacy ASS download with a KRL project action", () => {
    const html = renderToStaticMarkup(
      <KirakaraProjectDownload jobId="job-1" videoName="song.mp4" />,
    );

    expect(html).toContain("下载 Kirakara 工程 (.krl)");
    expect(html).toContain('data-kirakara-project-download="true"');
  });
});
