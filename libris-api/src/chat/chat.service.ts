import { HttpException, Injectable, Logger } from '@nestjs/common';
import { AiClient, type AnswerOptions } from '../ai/ai.client.js';
import { ChatRepository, type SavedCitation } from './chat.repository.js';
import { formatSse, parseSse } from './sse.js';

interface DoneEvent {
  answer: string;
  refused: boolean;
  refusal_reason: string | null;
  warnings: string[];
  model: string | null;
  usage: Record<string, number>;
  timings: Record<string, number>;
  plan: { mode: string; statuses: string[]; reasons: string[] };
  citations: { label: string; chunk_id: string; document_number: string }[];
  sources: { chunk_id: string; content: string; rerank_score: number | null }[];
}

@Injectable()
export class ChatService {
  private readonly logger = new Logger(ChatService.name);

  constructor(
    private readonly chats: ChatRepository,
    private readonly ai: AiClient,
  ) {}

  /**
   * Luồng SSE cho một câu hỏi: `start` → `meta` → `delta`* → `done` (kèm `messageId` của câu trả
   * lời đã lưu và `document_id` của từng trích dẫn) hoặc `error`. Người dùng đóng trang giữa chừng: request tới libris-ai bị hủy và
   * câu trả lời dở dang không được lưu.
   */
  async *ask(
    sessionId: string,
    content: string,
    options: AnswerOptions,
  ): AsyncGenerator<string> {
    const userMessageId = await this.chats.addUserMessage(sessionId, content);
    yield formatSse('start', { sessionId, userMessageId });

    const upstream = new AbortController();
    let finished = false;
    try {
      const body = await this.ai.streamAnswer(
        content,
        options,
        upstream.signal,
      );
      for await (const event of parseSse(body)) {
        if (event.event === 'done') {
          const result = JSON.parse(event.data) as DoneEvent;
          const saved = await this.saveAnswer(sessionId, result);
          finished = true;
          yield formatSse('done', {
            ...result,
            // document_id để giao diện mở nguyên văn văn bản được trích dẫn (Task 4.3)
            citations: result.citations.map((c) => ({
              ...c,
              document_id: saved.documentIds[c.chunk_id] ?? null,
            })),
            messageId: saved.id,
          });
          return;
        }
        if (event.event === 'error') {
          finished = true;
          yield `event: error\ndata: ${event.data}\n\n`;
          return;
        }
        yield `event: ${event.event}\ndata: ${event.data}\n\n`; // meta, delta: chuyển tiếp nguyên văn
      }
      finished = true;
      yield formatSse('error', { message: 'Luồng trả lời bị ngắt giữa chừng' });
    } catch (error) {
      if (upstream.signal.aborted) return;
      finished = true;
      this.logger.error(`Lỗi khi trả lời: ${(error as Error).message}`);
      const message =
        error instanceof HttpException ? error.message : 'Lỗi xử lý câu hỏi';
      yield formatSse('error', { message });
    } finally {
      if (!finished) upstream.abort(); // client ngắt kết nối: dừng libris-ai
    }
  }

  private saveAnswer(sessionId: string, result: DoneEvent) {
    const sources = new Map(result.sources.map((s) => [s.chunk_id, s]));
    const citations: SavedCitation[] = result.citations.map((c, i) => ({
      position: i + 1,
      chunkId: c.chunk_id,
      documentNumber: c.document_number,
      label: c.label,
      quote: sources.get(c.chunk_id)?.content ?? null,
      score: sources.get(c.chunk_id)?.rerank_score ?? null,
    }));
    return this.chats.addAssistantMessage(
      sessionId,
      result.answer,
      {
        refused: result.refused,
        refusalReason: result.refusal_reason,
        warnings: result.warnings,
        model: result.model,
        usage: result.usage,
        timings: result.timings,
        plan: {
          mode: result.plan.mode,
          statuses: result.plan.statuses,
          reasons: result.plan.reasons,
        },
      },
      citations,
    );
  }
}
