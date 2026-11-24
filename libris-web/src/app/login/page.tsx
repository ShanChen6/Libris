"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import { ApiError, signIn } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const body: Record<string, string> = {
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    };
    const fullName = String(form.get("fullName") ?? "").trim();
    if (mode === "register" && fullName) body.fullName = fullName;
    setPending(true);
    setError(null);
    try {
      await signIn(mode, body);
      router.replace("/chat");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không kết nối được máy chủ");
    } finally {
      setPending(false);
    }
  }

  const input =
    "border-input bg-background focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-[3px]";

  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-6 px-4 py-16">
      <div className="flex items-center gap-3">
        <Image src="/libris-icon.png" alt="Libris" width={664} height={469} priority className="h-10 w-auto" />
        <h1 className="text-2xl font-semibold tracking-tight">
          {mode === "login" ? "Đăng nhập Libris" : "Tạo tài khoản"}
        </h1>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-3">
        {mode === "register" && (
          <input name="fullName" placeholder="Họ và tên" className={input} autoComplete="name" />
        )}
        <input name="email" type="email" required placeholder="Email" className={input} autoComplete="email" />
        <input
          name="password"
          type="password"
          required
          minLength={mode === "register" ? 8 : 1}
          placeholder={mode === "register" ? "Mật khẩu (tối thiểu 8 ký tự)" : "Mật khẩu"}
          className={input}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
        />
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <Button type="submit" disabled={pending}>
          {pending ? "Đang xử lý…" : mode === "login" ? "Đăng nhập" : "Đăng ký"}
        </Button>
      </form>
      <button
        type="button"
        className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        onClick={() => setMode(mode === "login" ? "register" : "login")}
      >
        {mode === "login" ? "Chưa có tài khoản? Đăng ký" : "Đã có tài khoản? Đăng nhập"}
      </button>
    </main>
  );
}
