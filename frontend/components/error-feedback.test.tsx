import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ErrorFeedbackPanel } from "./error-feedback";

describe("ErrorFeedbackPanel", () => {
  it("renders the problem, solutions, and support details", () => {
    const html = renderToStaticMarkup(
      <ErrorFeedbackPanel
        feedback={{
          title: "服务器网关暂时不可用",
          description: "Nginx 暂时无法连接后端服务。",
          solutions: ["等待一分钟后重新检查。", "请管理员检查服务状态。"],
          technicalDetails: ["HTTP 状态码：502", "任务 ID：job-123"],
          retryable: true,
        }}
        onRetry={() => undefined}
      />,
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("服务器网关暂时不可用");
    expect(html).toContain("建议处理");
    expect(html).toContain("等待一分钟后重新检查。");
    expect(html).toContain("技术信息");
    expect(html).toContain("任务 ID：job-123");
    expect(html).toContain("重新检查");
  });

  it("renders a task-specific retry action", () => {
    const html = renderToStaticMarkup(
      <ErrorFeedbackPanel
        feedback={{
          title: "处理失败",
          description: "任务未完成。",
          solutions: ["重新加入队列。"],
          technicalDetails: ["任务 ID：job-123"],
          retryable: false,
        }}
        onRetry={() => undefined}
        retryLabel="重新加入队列"
      />,
    );

    expect(html).toContain("重新加入队列");
  });
});
