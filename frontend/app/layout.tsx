import type { Metadata } from "next";
import { headers } from "next/headers";
import Link from "next/link";

import { HOME_COPY } from "@/lib/ui-copy";

import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "https";
  const metadataBase = new URL(host ? `${protocol}://${host}` : "https://localhost");
  const title = "ニコカラ自动生成器";
  const description = HOME_COPY.metadataDescription;

  return {
    metadataBase,
    title,
    description,
    openGraph: {
      title,
      description,
      type: "website",
      images: [{ url: "/og.png", width: 1731, height: 907, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen">
        <header className="border-b bg-background/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
            <Link href="/" className="focus-ring rounded-sm">
              <span className="font-display text-lg font-bold tracking-[0.08em]">
                ニコカラ
              </span>
              <span className="ml-2 text-xs text-muted-foreground">LOCAL</span>
            </Link>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
