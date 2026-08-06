import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { JobMetadata } from "./job-metadata";

describe("JobMetadata", () => {
  it("lets long Japanese file names shrink within a mobile grid", () => {
    const html = renderToStaticMarkup(
      <JobMetadata
        job={{
          id: "02c24cf8-efeb-451b-943b-c057cb2c67df",
          original_video_name: "花譜「学園戦線」【オリジナルMV】_720p.mp4",
          video_size_bytes: 50_342_643,
          lyrics_source: "text",
        }}
      />,
    );

    expect(html).toContain("花譜「学園戦線」");
    expect(html.match(/min-w-0/g)).toHaveLength(2);
  });
});
