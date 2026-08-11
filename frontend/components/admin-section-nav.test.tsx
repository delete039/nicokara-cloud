import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AdminSectionNav } from "./admin-section-nav";


describe("AdminSectionNav", () => {
  it("links the monitor to the separate log console", () => {
    const html = renderToStaticMarkup(<AdminSectionNav active="monitor" />);

    expect(html).toContain('href="/admin"');
    expect(html).toContain('href="/admin/logs"');
    expect(html).toContain("监控");
    expect(html).toContain("日志");
  });
});
