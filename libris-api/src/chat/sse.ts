export interface SseEvent {
  event: string;
  data: string;
}

/** Định dạng một sự kiện Server-Sent Events (data JSON một dòng). */
export function formatSse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * Đọc luồng byte SSE thành từng sự kiện. Chịu được việc một sự kiện bị cắt ở giữa các mẩu dữ liệu
 * mạng, xuống dòng CRLF và nhiều dòng `data:`.
 */
export async function* parseSse(
  body: AsyncIterable<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const decoder = new TextDecoder();
  let buffer = '';
  for await (const chunk of body) {
    // Chuẩn hóa sau khi ghép: cặp \r\n có thể bị cắt giữa hai mẩu dữ liệu mạng
    buffer = (buffer + decoder.decode(chunk, { stream: true })).replace(
      /\r\n/g,
      '\n',
    );
    let end: number;
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = parseBlock(block);
      if (event) yield event;
    }
  }
  const last = parseBlock(buffer + decoder.decode());
  if (last) yield last;
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue; // comment / keep-alive
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');
    if (field === 'event') event = value;
    else if (field === 'data') data.push(value);
  }
  return data.length ? { event, data: data.join('\n') } : null;
}
