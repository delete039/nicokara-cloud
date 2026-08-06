import type { Metadata } from "next";
import { headers } from "next/headers";

import { AnnouncementDialog } from "@/components/announcement-dialog";
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
        {children}
        <AnnouncementDialog />
      </body>
    </html>
  );
}
