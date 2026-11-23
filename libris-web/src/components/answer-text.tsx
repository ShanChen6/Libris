"use client";

import type { Citation } from "@/lib/api";
import { boldParts, type AnswerPart } from "@/lib/citations";

/**
 * Câu trả lời / nhận định có thẻ trích dẫn: thẻ đã xác minh là nút mở văn bản gốc (Task 4.3), thẻ
 * chưa xác minh hiện viền đứt; **in đậm** kiểu Markdown được hiển thị đậm.
 */
export function AnswerText({
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
    const isActive = active === p.citation;
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
