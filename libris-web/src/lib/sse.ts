export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Đọc luồng byte Server-Sent Events thành từng sự kiện. Dùng thay EventSource vì cần POST và
 * header Authorization. Chịu được sự kiện bị cắt giữa các mẩu dữ liệu mạng, CRLF, nhiều dòng data.
 */
export async function* parseSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const event = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) yield event;
      }
    }
    const last = parseBlock(buffer + decoder.decode());
    if (last) yield last;
  } finally {
    reader.releaseLock();
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}
