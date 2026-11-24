"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { tokenStore, type User } from "@/lib/api";

const NAV = [
  { href: "/chat", label: "Hỏi đáp" },
  { href: "/analyze", label: "Phân tích văn bản" },
];

export function AppHeader({ user, children }: { user: User | null; children?: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
      <div className="flex min-w-0 items-center gap-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <Image src="/libris-icon.png" alt="" width={664} height={469} className="h-6 w-auto" />
          <span className="hidden sm:inline">Libris</span>
        </Link>
        <nav className="flex gap-1 text-sm">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={pathname === item.href ? "page" : undefined}
              className="text-muted-foreground hover:text-foreground aria-[current=page]:bg-secondary aria-[current=page]:text-foreground rounded-md px-2 py-1 whitespace-nowrap"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground hidden lg:inline">{user?.email}</span>
        {children}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            tokenStore.clear();
            router.replace("/login");
          }}
        >
          Đăng xuất
        </Button>
      </div>
    </header>
  );
}
