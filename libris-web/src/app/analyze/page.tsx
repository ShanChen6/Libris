"use client";

import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { AlertTriangle, Check, FileText, Loader2, Square, Upload } from "lucide-react";

import { AnswerText } from "@/components/answer-text";
import { AppHeader } from "@/components/app-header";
import { CitationViewer } from "@/components/citation-viewer";
import { ContractViewer } from "@/components/contract-viewer";
import { Button } from "@/components/ui/button";
import { ApiError, streamAnalysis, type Analysis, type Citation, type Issue, type Quote } from "@/lib/api";
import { answerParts } from "@/lib/citations";
import { useRequireUser } from "@/lib/use-user";

const ACCEPT = ".pdf,.doc,.docx";
const MAX_MB = 10;
const MIN_CHARS = 200;

const SEVERITY: Record<Issue["severity"], { label: string; className: string }> = {
  high: { label: "Rủi ro cao", className: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300" },
  medium: { label: "Cần lưu ý", className: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300" },
  low: { label: "Nên xem lại", className: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300" },
  unclear: { label: "Chưa đủ căn cứ", className: "bg-secondary text-secondary-foreground" },
};

type Pane = { kind: "contract"; quote: Quote } | { kind: "law"; citation: Citation } | null;

export default function AnalyzePage() {
  const user = useRequireUser();
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [progress, setProgress] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Analysis | null>(null);
  const [pane, setPane] = useState<Pane>(null);
  const abortRef = useRef<AbortController | null>(null);

  const ready = mode === "file" ? file !== null : text.trim().length >= MIN_CHARS;

  function pick(f: File | undefined) {
    if (!f) return;
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`File vượt quá ${MAX_MB} MB`);
      return;
    }
    setError(null);
    setFile(f);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || running) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setResult(null);
    setPane(null);
    setProgress([]);
    try {
      await streamAnalysis(
        mode === "file" && file ? { file } : { text },
        {
          onProgress: (p) => setProgress((all) => [...all, p.message]),
          onDone: setResult,
          onError: setError,
        },
        controller.signal,
      );
    } catch (err) {
      setError(
        controller.signal.aborted
          ? "Đã dừng phân tích."
          : err instanceof ApiError
            ? err.message
            : "Không kết nối được máy chủ",
      );
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="flex h-dvh flex-col">
      <AppHeader user={user} />
      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
            <section className="space-y-1">
              <h1 className="text-xl font-semibold tracking-tight">Tóm tắt &amp; phân tích văn bản pháp lý</h1>
              <p className="text-muted-foreground text-sm">
                Tải lên hợp đồng lao động, hợp đồng thuê nhà hoặc văn bản hành chính. Libris tóm tắt các điều khoản quan
                trọng và chỉ ra điểm có thể bất lợi, kèm căn cứ pháp lý.
              </p>
            </section>

            <form onSubmit={submit} className="space-y-3 rounded-2xl border p-4">
              <div role="tablist" className="bg-secondary inline-flex rounded-md p-0.5 text-sm">
                {(["file", "text"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="tab"
                    aria-selected={mode === m}
                    onClick={() => setMode(m)}
                    className="aria-selected:bg-background rounded px-3 py-1 aria-selected:shadow-xs"
                  >
                    {m === "file" ? "Tải file" : "Dán nội dung"}
                  </button>
                ))}
              </div>

              {mode === "file" ? (
                <label
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e: DragEvent) => {
                    e.preventDefault();
                    pick(e.dataTransfer.files[0]);
                  }}
                  className="hover:bg-secondary/50 flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 text-center text-sm"
                >
                  {file ? (
                    <>
                      <FileText className="size-6" />
                      <span className="font-medium break-all">{file.name}</span>
                      <span className="text-muted-foreground text-xs">
                        {(file.size / 1024).toFixed(0)} KB · bấm để chọn file khác
                      </span>
                    </>
                  ) : (
                    <>
                      <Upload className="text-muted-foreground size-6" />
                      <span>Kéo thả hoặc bấm để chọn file</span>
                      <span className="text-muted-foreground text-xs">
                        .pdf, .doc, .docx – tối đa {MAX_MB} MB; bản scan được nhận dạng chữ (OCR)
                      </span>
                    </>
                  )}
                  <input type="file" accept={ACCEPT} className="sr-only" onChange={(e) => pick(e.target.files?.[0])} />
                </label>
              ) : (
                <div className="space-y-1">
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={8}
                    maxLength={200_000}
                    placeholder="Dán nội dung hợp đồng vào đây…"
                    aria-label="Nội dung văn bản"
                    className="border-input focus-visible:ring-ring/50 w-full resize-y rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-[3px]"
                  />
                  {text.trim().length > 0 && text.trim().length < MIN_CHARS && (
                    <p className="text-muted-foreground text-xs">Cần tối thiểu {MIN_CHARS} ký tự.</p>
                  )}
                </div>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-muted-foreground text-xs">
                  Văn bản không được lưu lại. Nội dung được gửi tới dịch vụ AI (Gemini) để phân tích.
                </p>
                {running ? (
                  <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>
                    <Square /> Dừng
                  </Button>
                ) : (
                  <Button type="submit" disabled={!ready}>
                    Phân tích
                  </Button>
                )}
              </div>
            </form>

            {(running || (progress.length > 0 && !result)) && (
              <ol className="space-y-1.5 text-sm" aria-live="polite">
                {progress.map((p, i) => (
                  <li key={i} className="flex items-start gap-2">
                    {running && i === progress.length - 1 ? (
                      <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" />
                    ) : (
                      <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                    )}
                    {p}
                  </li>
                ))}
                {running && progress.length === 0 && (
                  <li className="text-muted-foreground flex items-center gap-2">
                    <Loader2 className="size-4 animate-spin" /> Đang gửi văn bản…
                  </li>
                )}
              </ol>
            )}
            {error && (
              <p role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}

            {result && <Result result={result} pane={pane} onOpen={setPane} />}
          </div>
        </main>
        {pane?.kind === "contract" && result && (
          <ContractViewer text={result.text} quote={pane.quote} onClose={() => setPane(null)} />
        )}
        {pane?.kind === "law" && <CitationViewer citation={pane.citation} onClose={() => setPane(null)} />}
      </div>
    </div>
  );
}

function QuoteButton({ quote, onOpen }: { quote: Quote; onOpen: (p: Pane) => void }) {
  if (quote.start === null)
    return (
      <blockquote className="text-muted-foreground border-l-2 pl-3 text-sm italic">
        “{quote.text}” <span className="not-italic">(không tìm thấy nguyên văn trong văn bản)</span>
      </blockquote>
    );
  return (
    <button
      type="button"
      onClick={() => onOpen({ kind: "contract", quote })}
      title="Xem trong văn bản"
      className="hover:bg-highlight/40 block w-full rounded-r border-l-2 border-amber-400 pl-3 text-left text-sm italic"
    >
      “{quote.text}”
    </button>
  );
}

function Result({ result, pane, onOpen }: { result: Analysis; pane: Pane; onOpen: (p: Pane) => void }) {
  const counts = result.issues.reduce<Record<string, number>>(
    (acc, i) => ({ ...acc, [i.severity]: (acc[i.severity] ?? 0) + 1 }),
    {},
  );
  const activeCitation = pane?.kind === "law" ? pane.citation : null;
  return (
    <div className="space-y-6">
      <p className="text-muted-foreground bg-secondary/60 rounded-lg px-3 py-2 text-xs">{result.disclaimer}</p>
      {result.warnings.map((w) => (
        <p key={w} className="flex gap-2 text-sm text-amber-700 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {w}
        </p>
      ))}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Tổng quan</h2>
          <span className="bg-secondary rounded px-2 py-0.5 text-xs font-medium">{result.document_type}</span>
        </div>
        {result.parties.length > 0 && (
          <ul className="text-sm">
            {result.parties.map((p, i) => (
              <li key={i}>
                <span className="text-muted-foreground">{p.role}:</span> {p.name || "—"}
              </li>
            ))}
          </ul>
        )}
        <p className="leading-7">{result.summary}</p>
      </section>

      {result.key_terms.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Điều khoản chính</h2>
          <dl className="grid gap-3 sm:grid-cols-2">
            {result.key_terms.map((t, i) => (
              <div key={i} className="space-y-1 rounded-xl border p-3">
                <dt className="text-sm font-medium">{t.topic}</dt>
                <dd className="text-sm leading-6">{t.content}</dd>
                {t.quote?.start != null && (
                  <dd>
                    <button
                      type="button"
                      onClick={() => onOpen({ kind: "contract", quote: t.quote! })}
                      className="text-citation-foreground text-xs underline-offset-2 hover:underline"
                    >
                      Xem trong văn bản
                    </button>
                  </dd>
                )}
              </div>
            ))}
          </dl>
        </section>
      )}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Điểm cần lưu ý</h2>
          {(["high", "medium", "low", "unclear"] as const).map(
            (s) =>
              counts[s] > 0 && (
                <span key={s} className={`rounded px-2 py-0.5 text-xs font-medium ${SEVERITY[s].className}`}>
                  {counts[s]} {SEVERITY[s].label.toLowerCase()}
                </span>
              ),
          )}
        </div>
        {result.issues.length === 0 ? (
          <p className="text-muted-foreground text-sm">Libris không phát hiện điều khoản bất lợi rõ ràng.</p>
        ) : (
          <ol className="space-y-4">
            {result.issues.map((issue) => (
              <li key={issue.id} className="space-y-3 rounded-2xl border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded px-2 py-0.5 text-xs font-medium ${SEVERITY[issue.severity].className}`}>
                    {SEVERITY[issue.severity].label}
                  </span>
                  <h3 className="font-medium">{issue.title}</h3>
                  {issue.affected_party && (
                    <span className="text-muted-foreground text-xs">· bất lợi cho {issue.affected_party}</span>
                  )}
                </div>
                {issue.quote && <QuoteButton quote={issue.quote} onOpen={onOpen} />}
                {issue.concern && <p className="text-muted-foreground text-sm">{issue.concern}</p>}
                <div className="text-sm leading-7 whitespace-pre-wrap">
                  <span className="font-medium">Đánh giá: </span>
                  <AnswerText
                    parts={answerParts(issue.verdict, issue.citations)}
                    active={activeCitation}
                    onOpen={(citation) => onOpen({ kind: "law", citation })}
                  />
                </div>
                {issue.recommendation && (
                  <p className="text-sm leading-6">
                    <span className="font-medium">Đề xuất: </span>
                    {issue.recommendation}
                  </p>
                )}
                {issue.related.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-muted-foreground">Quy định liên quan:</span>
                    {issue.related.map((c) => (
                      <button
                        key={c.chunk_id}
                        type="button"
                        onClick={() => onOpen({ kind: "law", citation: c })}
                        aria-pressed={activeCitation === c}
                        title={c.document_title}
                        className="bg-citation text-citation-foreground aria-pressed:ring-citation-foreground rounded px-1.5 py-0.5 font-medium hover:underline aria-pressed:ring-2"
                      >
                        {c.label.replace(/^\[|\]$/g, "")}
                      </button>
                    ))}
                  </div>
                )}
                {issue.warnings.length > 0 && (
                  <ul className="text-muted-foreground space-y-1 text-xs">
                    {issue.warnings.map((w) => (
                      <li key={w} className="flex gap-1.5">
                        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {w}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
