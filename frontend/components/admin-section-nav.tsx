import { Activity, ScrollText } from "lucide-react";
import Link from "next/link";


export function AdminSectionNav({ active }: { active: "monitor" | "logs" }) {
  const links = [
    { id: "monitor" as const, href: "/admin", label: "监控", icon: Activity },
    { id: "logs" as const, href: "/admin/logs", label: "日志", icon: ScrollText },
  ];

  return (
    <nav aria-label="管理员页面" className="flex min-h-11 items-end gap-6">
      {links.map(({ id, href, label, icon: Icon }) => (
        <Link
          key={id}
          href={href}
          aria-current={active === id ? "page" : undefined}
          className={`focus-ring flex min-h-10 items-center gap-2 border-b-2 px-1 text-sm font-semibold ${
            active === id
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <Icon className="size-4" aria-hidden="true" />
          {label}
        </Link>
      ))}
    </nav>
  );
}
