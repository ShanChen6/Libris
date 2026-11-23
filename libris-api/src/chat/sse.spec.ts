import { formatSse, parseSse } from './sse.js';

async function* chunks(...parts: string[]) {
  const enc = new TextEncoder();
  for (const p of parts) yield enc.encode(p);
}

async function collect(...parts: string[]) {
  const out = [];
  for await (const e of parseSse(chunks(...parts))) out.push(e);
  return out;
}

describe('SSE', () => {
  it('formats one event', () => {
    expect(formatSse('delta', { text: 'Xin chào' })).toBe(
      'event: delta\ndata: {"text":"Xin chào"}\n\n',
    );
  });

  it('parses events split across network chunks, CRLF, comments and multi-line data', async () => {
    const all =
      'event: meta\ndata: {"a":1}\n\n: keep-alive\n\nevent: delta\r\ndata: x\r\ndata: y\r\n\r\ndata: z';
    for (const parts of [
      [all],
      all.split(''), // từng ký tự: mô phỏng mạng gửi lắt nhắt (chuỗi chỉ có ký tự ASCII)
      [all.slice(0, 7), all.slice(7, 30), all.slice(30)],
    ]) {
      expect(await collect(...parts)).toEqual([
        { event: 'meta', data: '{"a":1}' },
        { event: 'delta', data: 'x\ny' },
        { event: 'message', data: 'z' },
      ]);
    }
  });

  it('decodes multi-byte characters split between chunks', async () => {
    const bytes = new TextEncoder().encode('event: delta\ndata: Điều 7\n\n');
    async function* split() {
      yield bytes.slice(0, 20);
      yield bytes.slice(20);
    }
    const out = [];
    for await (const e of parseSse(split())) out.push(e);
    expect(out).toEqual([{ event: 'delta', data: 'Điều 7' }]);
  });
});
