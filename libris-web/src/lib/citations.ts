import type { Citation } from "./api";

export type AnswerPart =
  | { kind: "text"; text: string }
  | { kind: "citation"; text: string; citation: Citation }
  | { kind: "unverified"; text: string };

/** Thẻ dạng [Điều X, Khoản Y - Số hiệu] */
const TAG_RE = /\[[^[\]]*?\s[-–—]\s\d{1,4}\/\d{4}\/[^\]\s]+\]/g;

/** Tách các thẻ trích dẫn trong đoạn chữ; các thẻ này chưa (hoặc không) xác minh được. */
export function splitTags(text: string): AnswerPart[] {
  const parts: AnswerPart[] = [];
  let last = 0;
  for (const m of text.matchAll(TAG_RE)) {
    if (m.index > last) parts.push({ kind: "text", text: text.slice(last, m.index) });
    parts.push({ kind: "unverified", text: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

/**
 * Tách câu trả lời đã xác minh thành đoạn chữ và thẻ trích dẫn. Vị trí `start`/`end` do libris-ai
 * (Python) tính theo code point, nên cắt bằng `Array.from`, không dùng `String.slice`. Thẻ có dạng
 * trích dẫn nhưng không nằm trong `citations` là thẻ không xác minh được.
 */
export function answerParts(answer: string, citations: Citation[]): AnswerPart[] {
  const cps = Array.from(answer);
  const sorted = [...citations].sort((a, b) => a.start - b.start);
  const parts: AnswerPart[] = [];
  let pos = 0;
  for (const c of sorted) {
    if (c.start < pos || c.end > cps.length) continue;
    const text = cps.slice(c.start, c.end).join("");
    if (text !== c.label) continue; // vị trí không khớp: bỏ qua, để thẻ hiển thị như chưa xác minh
    parts.push(...splitTags(cps.slice(pos, c.start).join("")));
    parts.push({ kind: "citation", text, citation: c });
    pos = c.end;
  }
  parts.push(...splitTags(cps.slice(pos).join("")));
  return parts.filter((p) => p.text);
}

/** Tách nguyên văn thành [trước, đoạn được trích dẫn, sau] theo code point. */
export function highlightRange(fullText: string, start: number, end: number): [string, string, string] {
  const cps = Array.from(fullText);
  return [cps.slice(0, start).join(""), cps.slice(start, end).join(""), cps.slice(end).join("")];
}

export function citationName(c: Pick<Citation, "article" | "clause" | "point">): string {
  return [c.article, c.clause, c.point].filter(Boolean).join(", ");
}

/** Chữ cái của Điểm trong trích dẫn, VD "[Điều 6, Khoản 8, Điểm e - …]" → "e". */
export function pointLetter(c: Pick<Citation, "point" | "label">): string | null {
  const m = /Điểm\s+([a-zđ]{1,2})\b/i.exec(c.point ?? c.label);
  return m ? m[1].toLowerCase() : null;
}

/**
 * Vị trí Điểm (`e) …`) bên trong đoạn luật, tính đến trước Điểm kế tiếp. Đoạn luật đã lưu thường là
 * cả Khoản, nên khi câu trả lời trích tới Điểm thì làm nổi riêng Điểm đó.
 */
export function pointSpan(text: string, letter: string): [number, number] | null {
  const start = new RegExp(`(?:^|\\n)[ \\t]*${letter}\\)`, "i").exec(text);
  if (!start) return null;
  const from = start.index + (text[start.index] === "\n" ? 1 : 0);
  const next = /\n[ \t]*[a-zđ]{1,2}\)/g;
  next.lastIndex = from + 1;
  const end = next.exec(text);
  return [from, end ? end.index : text.length];
}

/** Câu trả lời của LLM có thể dùng **in đậm** kiểu Markdown. */
export function boldParts(text: string): { text: string; bold: boolean }[] {
  return text
    .split(/\*\*([\s\S]+?)\*\*/g)
    .map((t, i) => ({ text: t.replaceAll("**", ""), bold: i % 2 === 1 }))
    .filter((p) => p.text);
}
