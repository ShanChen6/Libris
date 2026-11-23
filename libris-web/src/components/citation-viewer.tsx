"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ExternalLink, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, getDocumentText, type Citation, type DocumentText } from "@/lib/api";
import { highlightRange, pointLetter, pointSpan } from "@/lib/citations";

const STATUS: Record<DocumentText["status"], { label: string; className: string }> = {
  ACTIVE: {
    label: "Còn hiệu lực",
    className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  },
  AMENDED: {
    label: "Còn hiệu lực, đã được sửa đổi",
    className: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  },
  EXPIRED: {
    label: "Hết hiệu lực",
    className: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  },
  PENDING: {
    label: "Chưa có hiệu lực",
    className: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  },
};

function vnDate(iso: string | null) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

type Loaded = { id: string; doc: DocumentText } | { id: string; error: string };

/**
 * Ngăn xem văn bản gốc (Task 4.3): mở nguyên văn văn bản được trích dẫn và bôi vàng đúng đoạn luật
 * (`char_start`–`char_end`) để người dùng tự kiểm chứng.
 */
export function CitationViewer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const documentId = citation.document_id;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const markRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    getDocumentText(documentId).then(
      (doc) => !cancelled && setLoaded({ id: documentId, doc }),
      (err) =>
        !cancelled &&
        setLoaded({
          id: documentId,
          error: err instanceof ApiError ? err.message : "Không tải được văn bản",
        }),
    );
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const current = loaded?.id === documentId ? loaded : null;
  const doc = current && "doc" in current ? current.doc : null;
  const parts = useMemo(
    () => (doc ? highlightRange(doc.fullText, citation.char_start, citation.char_end) : null),
    [doc, citation.char_start, citation.char_end],
  );

  // Trích dẫn tới Điểm mà đoạn luật đã lưu là cả Khoản: làm nổi riêng Điểm đó
  const letter = pointLetter(citation);
  const point = parts && letter ? pointSpan(parts[1], letter) : null;

  useEffect(() => {
    // scrollIntoView có thể trả về Promise: không để nó thành giá trị trả về của effect
    markRef.current?.scrollIntoView({ block: "center" });
  }, [parts, citation]); // mỗi lần bấm một thẻ (kể cả cùng đoạn luật) đều cuộn tới

  // Điều/Khoản được trích dẫn đã bị bãi bỏ hoặc sửa đổi bởi văn bản khác
  const superseded =
    doc?.supersededProvisions.filter(
      (p) => p.article === citation.article && (!p.clause || p.clause === citation.clause),
    ) ?? [];
  const status = doc ? STATUS[doc.status] : null;

  return (
    <aside
      aria-label="Văn bản gốc"
      className="bg-background fixed inset-0 z-40 flex flex-col lg:static lg:z-auto lg:w-1/2 lg:border-l"
    >
      <header className="flex items-start gap-3 border-b px-4 py-3">
        <div className="min-w-0 flex-1 space-y-1">
          <span className="bg-citation text-citation-foreground inline-block rounded px-1.5 py-0.5 text-sm font-medium">
            {citation.label.replace(/^\[|\]$/g, "")}
          </span>
          <h2 className="text-sm leading-snug font-semibold">{doc?.title ?? citation.document_title}</h2>
          {doc && (
            <p className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <span className={`rounded px-1.5 py-0.5 font-medium ${status?.className}`}>{status?.label}</span>
              {doc.effectiveDate && <span>Hiệu lực từ {vnDate(doc.effectiveDate)}</span>}
              {doc.expiryDate && <span>· hết hiệu lực {vnDate(doc.expiryDate)}</span>}
              {doc.sourceUrl && (
                <a
                  href={doc.sourceUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-0.5 underline-offset-2 hover:underline"
                >
                  Nguồn <ExternalLink className="size-3" />
                </a>
              )}
            </p>
          )}
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Đóng văn bản gốc">
          <X />
        </Button>
      </header>

      {(superseded.length > 0 || doc?.needsReview) && (
        <ul className="space-y-1 border-b bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {superseded.map((p) => (
            <li key={`${p.source}-${p.article}-${p.clause}`} className="flex gap-1.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              {p.clause ? `${p.article}, ${p.clause}` : p.article}{" "}
              {p.kind === "repealed" ? "đã bị bãi bỏ" : "đã được sửa đổi"} bởi {p.source}
            </li>
          ))}
          {doc?.needsReview && (
            <li className="flex gap-1.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              Văn bản được nhận dạng từ bản scan (OCR), có thể sai chính tả hoặc số liệu.
            </li>
          )}
        </ul>
      )}

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {!documentId ? (
          <p className="text-muted-foreground text-sm">Văn bản này không còn trong kho dữ liệu.</p>
        ) : current && "error" in current ? (
          <p className="text-destructive text-sm">{current.error}</p>
        ) : !parts ? (
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="size-4 animate-spin" /> Đang tải văn bản…
          </p>
        ) : (
          <div className="text-[0.95rem] leading-7 whitespace-pre-wrap">
            {parts[0]}
            <mark
              ref={point ? undefined : markRef}
              key={`${citation.char_start}-${citation.char_end}`}
              className={`text-foreground rounded-sm px-0.5 ${
                point ? "bg-highlight/45" : "bg-highlight animate-[highlight-in_1.2s_ease-out] ring-2 ring-amber-400/60"
              }`}
            >
              {point ? (
                <>
                  {parts[1].slice(0, point[0])}
                  <mark
                    ref={markRef}
                    className="bg-highlight text-foreground animate-[highlight-in_1.2s_ease-out] rounded-sm ring-2 ring-amber-400/60"
                  >
                    {parts[1].slice(point[0], point[1])}
                  </mark>
                  {parts[1].slice(point[1])}
                </>
              ) : (
                parts[1]
              )}
            </mark>
            {parts[2]}
          </div>
        )}
      </div>
    </aside>
  );
}
