"use client";

import { useEffect, useMemo, useRef } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Quote } from "@/lib/api";
import { highlightRange } from "@/lib/citations";

/** Văn bản người dùng tải lên, bôi vàng đoạn được trích (Task 4.4). */
export function ContractViewer({ text, quote, onClose }: { text: string; quote: Quote; onClose: () => void }) {
  const markRef = useRef<HTMLElement>(null);
  const parts = useMemo(
    () => (quote.start !== null && quote.end !== null ? highlightRange(text, quote.start, quote.end) : null),
    [text, quote],
  );
  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center" });
  }, [parts]);

  return (
    <aside
      aria-label="Văn bản của bạn"
      className="bg-background fixed inset-0 z-40 flex flex-col lg:static lg:z-auto lg:w-1/2 lg:border-l"
    >
      <header className="flex items-center gap-3 border-b px-4 py-3">
        <h2 className="flex-1 text-sm font-semibold">Văn bản của bạn</h2>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Đóng văn bản">
          <X />
        </Button>
      </header>
      <div className="flex-1 overflow-y-auto px-4 py-4 text-[0.95rem] leading-7 whitespace-pre-wrap">
        {parts ? (
          <>
            {parts[0]}
            <mark
              ref={markRef}
              key={`${quote.start}-${quote.end}`}
              className="bg-highlight text-foreground animate-[highlight-in_1.2s_ease-out] rounded-sm px-0.5 ring-2 ring-amber-400/60"
            >
              {parts[1]}
            </mark>
            {parts[2]}
          </>
        ) : (
          text
        )}
      </div>
    </aside>
  );
}
