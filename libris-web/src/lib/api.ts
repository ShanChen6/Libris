import { parseSse } from "./sse";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:4000";
const TOKEN_KEY = "libris.token";

export interface User {
  id: string;
  email: string;
  fullName: string | null;
  role: "USER" | "ADMIN";
}

export interface Citation {
  label: string;
  start: number;
  end: number;
  chunk_id: string;
  document_number: string;
  document_title: string;
  status: string;
  article: string | null;
  clause: string | null;
  point: string | null;
  char_start: number;
  char_end: number;
  superseded_by: string[];
  /** Văn bản chứa đoạn được trích dẫn – để mở nguyên văn (Task 4.3) */
  document_id: string | null;
}

export interface Source {
  chunk_id: string;
  citation: string;
  document_number: string;
  document_title: string;
  status: string;
  content: string;
  rerank_score: number | null;
}

export interface AnswerDone {
  messageId: string;
  answer: string;
  refused: boolean;
  refusal_reason: string | null;
  citations: Citation[];
  warnings: string[];
  sources: Source[];
  model: string | null;
  plan: { mode: string; statuses: string[]; reasons: string[] };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// Lưu token ở localStorage cho đơn giản. Khi triển khai thật nên chuyển sang cookie httpOnly
// (giảm rủi ro bị lấy token nếu trang dính XSS).
export const tokenStore = {
  get: () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY)),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (res.status === 401 && token) tokenStore.clear();
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { message?: string | string[] };
    const message = Array.isArray(body.message) ? body.message.join("; ") : body.message;
    throw new ApiError(res.status, message ?? `Lỗi ${res.status}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export async function signIn(mode: "login" | "register", body: Record<string, string>) {
  const res = await request<{ user: User; accessToken: string }>(`/auth/${mode}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  tokenStore.set(res.accessToken);
  return res.user;
}

export const me = () => request<User>("/auth/me");

export type DocumentStatus = "ACTIVE" | "AMENDED" | "EXPIRED" | "PENDING";

export interface DocumentText {
  id: string;
  documentNumber: string;
  documentType: string | null;
  title: string;
  issuingBody: string | null;
  issueDate: string | null;
  effectiveDate: string | null;
  expiryDate: string | null;
  status: DocumentStatus;
  needsReview: boolean;
  sourceUrl: string | null;
  relations: {
    type: string;
    source: string;
    target: string;
    effectiveDate: string | null;
  }[];
  supersededProvisions: {
    article: string;
    clause: string | null;
    kind: string;
    source: string;
  }[];
  /** Nguyên văn; `char_start`/`char_end` tính theo code point */
  fullText: string;
}

const documentCache = new Map<string, Promise<DocumentText>>();

/** Nguyên văn văn bản (lưu tạm trong phiên làm việc: bấm nhiều trích dẫn cùng văn bản chỉ tải một lần). */
export function getDocumentText(id: string): Promise<DocumentText> {
  let doc = documentCache.get(id);
  if (!doc) {
    doc = request<DocumentText>(`/documents/${id}/text`);
    doc.catch(() => documentCache.delete(id));
    documentCache.set(id, doc);
  }
  return doc;
}

export const createSession = () =>
  request<{ id: string; title: string | null }>("/chat/sessions", {
    method: "POST",
    body: "{}",
  });

export interface StreamHandlers {
  onStart?: (data: { sessionId: string; userMessageId: string }) => void;
  onMeta?: (data: { sources: Source[] }) => void;
  onDelta: (text: string) => void;
  onDone: (data: AnswerDone) => void;
  onError: (message: string) => void;
}

/** Gửi câu hỏi và nhận câu trả lời dạng luồng SSE (Task 4.2). `signal` để dừng giữa chừng. */
export async function streamAnswer(sessionId: string, content: string, handlers: StreamHandlers, signal?: AbortSignal) {
  const res = await fetch(`${API_URL}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      Authorization: `Bearer ${tokenStore.get() ?? ""}`,
    },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => ({}))) as { message?: string | string[] };
    const message = Array.isArray(body.message) ? body.message.join("; ") : body.message;
    throw new ApiError(res.status, message ?? `Lỗi ${res.status}`);
  }
  for await (const event of parseSse(res.body)) {
    const data = JSON.parse(event.data);
    if (event.event === "start") handlers.onStart?.(data);
    else if (event.event === "meta") handlers.onMeta?.(data);
    else if (event.event === "delta") handlers.onDelta(data.text);
    else if (event.event === "done") handlers.onDone(data);
    else if (event.event === "error") handlers.onError(data.message);
  }
}
