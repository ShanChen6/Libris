"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { me, tokenStore, type User } from "./api";

/** Người dùng hiện tại; chưa đăng nhập hoặc token hết hạn thì chuyển về /login. */
export function useRequireUser(): User | null {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    if (!tokenStore.get()) {
      router.replace("/login");
      return;
    }
    me().then(setUser, () => {
      router.replace("/login");
    });
  }, [router]);
  return user;
}
