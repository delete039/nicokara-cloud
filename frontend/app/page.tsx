import { FileUp, Zap, Download } from "lucide-react";

import { UploadForm } from "@/components/upload-form";
import { HOME_COPY } from "@/lib/ui-copy";

const steps = [
  {
    icon: FileUp,
    ...HOME_COPY.steps[0],
  },
  {
    icon: Zap,
    ...HOME_COPY.steps[1],
  },
  {
    icon: Download,
    ...HOME_COPY.steps[2],
  },
];

export default function Home() {
  return (
    <main>
      <section className="mx-auto grid max-w-6xl gap-12 px-5 py-12 sm:px-8 sm:py-16 lg:grid-cols-[0.9fr_1.1fr] lg:items-start lg:py-24">
        <div className="lg:sticky lg:top-10">
          <h1 className="font-display text-4xl font-bold leading-tight tracking-tight sm:text-6xl">
            ニコカラ
            <br />
            自动生成器
          </h1>
          <p className="mt-7 max-w-xl text-base leading-8 text-muted-foreground sm:text-lg">
            喜欢的歌太冷门，找不到ニコカラ版本？
            <br />
            {HOME_COPY.introduction}
          </p>

          <ol className="mt-10 space-y-5">
            {steps.map((step) => (
              <li key={step.title} className="flex gap-4">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-full border bg-card">
                  <step.icon className="size-4 text-primary" />
                </div>
                <div>
                  <p className="font-medium">{step.title}</p>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    {step.text}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          <a
            href="#upload-form"
            className="mt-10 inline-block text-lg font-semibold text-primary hover:underline"
          >
            {HOME_COPY.callToAction} →
          </a>
        </div>

        <div
          id="upload-form"
          className="rounded-3xl border bg-card/92 p-5 shadow-[0_24px_80px_-48px_color-mix(in_oklab,var(--color-foreground)_45%,transparent)] sm:p-8"
        >
          <UploadForm />
        </div>
      </section>
    </main>
  );
}
