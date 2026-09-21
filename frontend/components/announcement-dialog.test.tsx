import { describe, expect, it } from "vitest";

import { isAnnouncementHeadline } from "./announcement-dialog";

describe("announcement headline styling", () => {
  it("recognizes the major update headline", () => {
    expect(isAnnouncementHeadline("！！！！！重大更新！！！！！")).toBe(true);
    expect(isAnnouncementHeadline("更新内容：")).toBe(false);
  });
});
