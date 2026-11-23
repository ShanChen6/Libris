"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, Scale, Square } from "lucide-react";

import { CitationViewer } from "@/components/citation-viewer";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  type Citation,
  createSession,
  me,
  streamAnswer,
  tokenStore,
  type AnswerDone,
  type User,
} from "@/lib/api";
import { answerParts, boldParts, citationName, splitTags, type AnswerPart } from "@/lib/citations";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  done?: AnswerDone;
  error?: string;
}

export default function ChatPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [viewing, setViewing] = useState<Citation | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const busy = messages.at(-1)?.streaming ?? false;

  useEffect(() => {
    if (!tokenStore.get()) {
      router.replace("/login");
      return;
    }
    me().then(setUser, () => {
      router.replace("/login");
    });
  }, [router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  function updateLast(change: (m: ChatMessage) => ChatMessage) {
    setMessages((all) => [...all.slice(0, -1), change(all[all.length - 1])]);
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setMessages((all) => [
      ...all,
      { role: "user", content: question },
      { role: "assistant", content: "", streaming: true },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const sid = sessionId ?? (await createSession()).id;
      setSessionId(sid);
      await streamAnswer(
        sid,
        question,
        {
          onDelta: (text) => updateLast((m) => ({ ...m, content: m.content + text })),
          // Bản chính thức: có thể thêm cảnh báo hiệu lực hoặc thay bằng lời từ chối
          onDone: (done) =>
            updateLast((m) => ({
              ...m,
              content: done.answer,
              done,
              streaming: false,
            })),
          onError: (error) => updateLast((m) => ({ ...m, error, streaming: false })),
        },
        controller.signal,
      );
    } catch (err) {
      if (controller.signal.aborted) {
        updateLast((m) => ({ ...m, streaming: false, error: "Đã dừng." }));
      } else {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
        updateLast((m) => ({
          ...m,
          streaming: false,
          error: err instanceof ApiError ? err.message : "Không kết nối được máy chủ",
        }));
      }
    } finally {
      updateLast((m) => (m.streaming ? { ...m, streaming: false } : m));
      abortRef.current = null;
    }
  }

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex shrink-0 items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2 font-semibold">
          <Scale className="size-5" /> Libris
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground hidden sm:inline">{user?.email}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setMessages([]);
              setSessionId(null);
              setViewing(null);
            }}
          >
            Hội thoại mới
          </Button>
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

      <div className="flex min-h-0 flex-1">
        <section className="flex min-w-0 flex-1 flex-col">
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
              {messages.length === 0 && (
                <p className="text-muted-foreground mt-16 text-center">
                  Hỏi Libris về pháp luật Việt Nam, VD: &quot;Đi xe máy không có gương chiếu hậu bên trái có bị phạt
                  không?&quot;
                </p>
              )}
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <div key={i} className="bg-secondary self-end rounded-2xl px-4 py-2 whitespace-pre-wrap">
                    {m.content}
                  </div>
                ) : (
                  <AssistantMessage key={i} message={m} active={viewing} onOpen={setViewing} />
                ),
              )}
              <div ref={bottomRef} />
            </div>
          </main>

          <form onSubmit={send} className="bg-background shrink-0 border-t px-4 py-3">
            <div className="mx-auto flex max-w-3xl gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    e.currentTarget.form?.requestSubmit();
                  }
                }}
                rows={2}
                maxLength={2000}
                placeholder="Nhập câu hỏi pháp luật…"
                aria-label="Câu hỏi"
                className="border-input focus-visible:ring-ring/50 flex-1 resize-none rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-[3px]"
              />
              {busy ? (
                <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>
                  <Square /> Dừng
                </Button>
              ) : (
                <Button type="submit" disabled={!input.trim()}>
                  Gửi
                </Button>
              )}
            </div>
          </form>
        </section>
        {viewing && <CitationViewer citation={viewing} onClose={() => setViewing(null)} />}
      </div>
    </div>
  );
}

function AnswerText({
  parts,
  active,
  onOpen,
}: {
  parts: AnswerPart[];
  active: Citation | null;
  onOpen: (c: Citation) => void;
}) {
  return parts.map((p, i) => {
    if (p.kind === "text")
      return boldParts(p.text).map((b, j) =>
        b.bold ? (
          <strong key={`${i}-${j}`} className="font-semibold">
            {b.text}
          </strong>
        ) : (
          b.text
        ),
      );
    if (p.kind === "unverified")
      return (
        <span
          key={i}
          title="Chưa xác minh được trích dẫn này"
          className="text-muted-foreground rounded border border-dashed px-1 py-0.5 text-[0.85em] whitespace-nowrap"
        >
          {p.text}
        </span>
      );
    const isActive = active?.chunk_id === p.citation.chunk_id && active.start === p.citation.start;
    return (
      <button
        key={i}
        type="button"
        onClick={() => onOpen(p.citation)}
        title="Xem nguyên văn đoạn luật"
        aria-pressed={isActive}
        className={`bg-citation text-citation-foreground cursor-pointer rounded px-1 py-0.5 text-[0.85em] font-medium whitespace-nowrap underline-offset-2 hover:underline ${isActive ? "ring-citation-foreground ring-2" : ""}`}
      >
        {p.text}
      </button>
    );
  });
}

function AssistantMessage({
  message,
  active,
  onOpen,
}: {
  message: ChatMessage;
  active: Citation | null;
  onOpen: (c: Citation) => void;
}) {
  const { done } = message;
  const citations = done?.citations ?? [];
  const unique = [...new Map(citations.map((c) => [c.chunk_id, c])).values()];
  // Đang stream: thẻ chưa xác minh, chưa bấm được. Xong: chỉ thẻ đã xác minh mới mở văn bản gốc.
  const parts = done ? answerParts(message.content, citations) : splitTags(message.content);
  return (
    <article
      aria-busy={message.streaming}
      className={`rounded-2xl border px-4 py-3 ${done?.refused ? "border-dashed" : ""}`}
    >
      {message.content ? (
        <div className="leading-7 whitespace-pre-wrap">
          <AnswerText parts={parts} active={active} onOpen={onOpen} />
          {message.streaming && <span className="bg-foreground ml-0.5 inline-block h-4 w-1.5 animate-pulse" />}
        </div>
      ) : (
        message.streaming && <p className="text-muted-foreground animate-pulse">Đang tra cứu văn bản pháp luật…</p>
      )}
      {message.error && <p className="text-destructive mt-2 text-sm">{message.error}</p>}
      {done && done.warnings.length > 0 && (
        <ul className="text-muted-foreground mt-3 space-y-1 text-sm">
          {done.warnings.map((w) => (
            <li key={w} className="flex gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {w}
            </li>
          ))}
        </ul>
      )}
      {unique.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <p className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">Căn cứ pháp lý</p>
          <ul className="space-y-1 text-sm">
            {unique.map((c) => (
              <li key={c.chunk_id}>
                <button
                  type="button"
                  onClick={() => onOpen(c)}
                  className="group text-left"
                  title="Xem nguyên văn đoạn luật"
                >
                  <span className="bg-citation text-citation-foreground rounded px-1.5 py-0.5 font-medium group-hover:underline">
                    {citationName(c)}
                  </span>{" "}
                  {c.document_number} – {c.document_title}
                  {c.status === "EXPIRED" || c.superseded_by.length ? (
                    <span className="text-destructive ml-1">(không còn hiệu lực)</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
