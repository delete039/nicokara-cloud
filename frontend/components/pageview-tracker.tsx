"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import {
  normalizedAnalyticsPath,
  recordPageview,
} from "@/services/analytics";


export function PageviewTracker() {
  const pathname = usePathname();

  useEffect(() => {
    const path = normalizedAnalyticsPath(pathname);
    if (!path) return;
    void recordPageview(path).catch(() => undefined);
  }, [pathname]);

  return null;
}
