import { vi } from 'vitest';
import { ChatService } from './chat.service.js';
import type { ChatRepository } from './chat.repository.js';
import type { AiClient } from '../ai/ai.client.js';

function sseBody(text: string, hang = false): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      if (!hang) controller.close(); // hang: luồng mở mãi như LLM đang sinh chữ
    },
  });
}

const DONE = {
  answer: 'Phạt 400.000 đồng [Điều 7, Khoản 2 - 168/2024/NĐ-CP].',
  refused: false,
  refusal_reason: null,
  warnings: [],
  model: 'gemini',
  usage: {},
  timings: { llm: 1 },
  plan: {
    mode: 'current',
    statuses: ['ACTIVE'],
    reasons: ['Mặc định'],
    period: null,
    referenced: [],
  },
  citations: [
    {
      label: '[Điều 7, Khoản 2 - 168/2024/NĐ-CP]',
      chunk_id: 'c1',
      document_number: '168/2024/NĐ-CP',
    },
  ],
  sources: [
    { chunk_id: 'c1', content: 'Phạt tiền từ 400.000 đồng', rerank_score: 0.9 },
  ],
};

describe('ChatService', () => {
  const repo = { addUserMessage: vi.fn(), addAssistantMessage: vi.fn() };
  const ai = { streamAnswer: vi.fn() };
  const service = new ChatService(
    repo as unknown as ChatRepository,
    ai as unknown as AiClient,
  );

  beforeEach(() => {
    vi.resetAllMocks();
    repo.addUserMessage.mockResolvedValue('u1');
    repo.addAssistantMessage.mockResolvedValue({
      id: 'a1',
      documentIds: { c1: 'd1' },
    });
  });

  it('relays the stream and saves the verified answer with its citations', async () => {
    ai.streamAnswer.mockResolvedValue(
      sseBody(
        'event: meta\ndata: {"sources":[]}\n\nevent: delta\ndata: {"text":"Phạt"}\n\n' +
          `event: done\ndata: ${JSON.stringify(DONE)}\n\n`,
      ),
    );
    const events: string[] = [];
    for await (const e of service.ask('s1', 'Không gương?', {})) events.push(e);
    expect(events.map((e) => e.split('\n')[0])).toEqual([
      'event: start',
      'event: meta',
      'event: delta',
      'event: done',
    ]);
    const done = JSON.parse(events[3].split('\n')[1].slice(6));
    expect(done).toMatchObject({ messageId: 'a1', refused: false });
    expect(done.citations[0]).toMatchObject({
      chunk_id: 'c1',
      document_id: 'd1',
    });
    const [sessionId, content, metadata, citations] =
      repo.addAssistantMessage.mock.calls[0];
    expect([sessionId, content]).toEqual(['s1', DONE.answer]);
    expect(metadata).toMatchObject({
      refused: false,
      model: 'gemini',
      plan: { mode: 'current' },
    });
    expect(citations).toEqual([
      {
        position: 1,
        chunkId: 'c1',
        documentNumber: '168/2024/NĐ-CP',
        label: '[Điều 7, Khoản 2 - 168/2024/NĐ-CP]',
        quote: 'Phạt tiền từ 400.000 đồng',
        score: 0.9,
      },
    ]);
  });

  it('aborts libris-ai and saves nothing when the client goes away', async () => {
    let signal: AbortSignal | undefined;
    ai.streamAnswer.mockImplementation(
      async (_q: string, _o: object, s: AbortSignal) => {
        signal = s;
        return sseBody('event: delta\ndata: {"text":"Phạt"}\n\n', true);
      },
    );
    const gen = service.ask('s1', 'Không gương?', {});
    expect((await gen.next()).value).toContain('event: start');
    expect((await gen.next()).value).toContain('event: delta');
    await gen.return(undefined); // client ngắt kết nối
    expect(signal?.aborted).toBe(true);
    expect(repo.addAssistantMessage).not.toHaveBeenCalled();
  });

  it('forwards upstream errors and failures to reach libris-ai', async () => {
    ai.streamAnswer.mockResolvedValueOnce(
      sseBody('event: error\ndata: {"message":"LLM quá tải"}\n\n'),
    );
    const first: string[] = [];
    for await (const e of service.ask('s1', 'x', {})) first.push(e);
    expect(first.at(-1)).toBe(
      'event: error\ndata: {"message":"LLM quá tải"}\n\n',
    );

    ai.streamAnswer.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    const second: string[] = [];
    for await (const e of service.ask('s1', 'x', {})) second.push(e);
    expect(second.at(-1)).toContain('Lỗi xử lý câu hỏi');
    expect(repo.addAssistantMessage).not.toHaveBeenCalled();
  });
});
