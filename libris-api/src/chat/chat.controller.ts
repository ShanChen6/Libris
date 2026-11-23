import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  NotFoundException,
  Param,
  Patch,
  Post,
  Query,
  UseGuards,
} from '@nestjs/common';
import { CurrentUser } from '@nestjs/authentication';
import { Can } from '@nestjs/authorization';
import { Throttle, ThrottlerGuard } from '@nestjs/throttler';
import type { z } from 'zod';
import type { User } from '../users/user.model.js';
import { ChatRepository } from './chat.repository.js';
import {
  askSchema,
  createSessionSchema,
  listSessionsSchema,
  renameSessionSchema,
  type AskInput,
} from './chat.schemas.js';
import { ChatService } from './chat.service.js';

/** Hội thoại của chính người dùng: phiên của người khác trả 404. */
@Controller('chat/sessions')
@Can.Anyone()
export class ChatController {
  constructor(
    private readonly chats: ChatRepository,
    private readonly chat: ChatService,
  ) {}

  @Post()
  create(
    @CurrentUser() user: User,
    @Body({ schema: createSessionSchema })
    body: z.infer<typeof createSessionSchema>,
  ) {
    return this.chats.createSession(user.id, body.title);
  }

  @Get()
  async list(
    @CurrentUser() user: User,
    @Query({ schema: listSessionsSchema })
    query: z.infer<typeof listSessionsSchema>,
  ) {
    const items = await this.chats.listSessions(
      user.id,
      query.limit + 1,
      query.cursor,
    );
    const page = items.slice(0, query.limit);
    const last = page.at(-1);
    return {
      items: page,
      nextCursor:
        items.length > query.limit && last
          ? `${last.updatedAt.toISOString()}|${last.id}`
          : null,
    };
  }

  @Get(':id')
  async get(@CurrentUser() user: User, @Param('id') id: string) {
    const session = await this.chats.findSession(user.id, id);
    if (!session) throw new NotFoundException('Không tìm thấy hội thoại');
    return { ...session, messages: await this.chats.listMessages(id) };
  }

  @Patch(':id')
  async rename(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body({ schema: renameSessionSchema })
    body: z.infer<typeof renameSessionSchema>,
  ) {
    const session = await this.chats.renameSession(user.id, id, body.title);
    if (!session) throw new NotFoundException('Không tìm thấy hội thoại');
    return session;
  }

  @Delete(':id')
  @HttpCode(204)
  async remove(@CurrentUser() user: User, @Param('id') id: string) {
    if (!(await this.chats.deleteSession(user.id, id)))
      throw new NotFoundException('Không tìm thấy hội thoại');
  }

  /**
   * Gửi câu hỏi; trả lời là luồng Server-Sent Events (Task 4.2):
   * `start` {sessionId, userMessageId} → `meta` {plan, sources} → `delta` {text}* →
   * `done` {answer, citations, refused, warnings, messageId, ...} | `error` {message}.
   */
  @Post(':id/messages')
  @UseGuards(ThrottlerGuard)
  @Throttle({ default: { limit: 20, ttl: 60_000 } }) // gọi LLM tốn quota: 20 câu hỏi/phút/IP
  async ask(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body({ schema: askSchema }) body: AskInput,
  ) {
    // Kiểm tra trước khi mở luồng: sau khi đã gửi header thì không trả 404 được nữa
    if (!(await this.chats.findSession(user.id, id)))
      throw new NotFoundException('Không tìm thấy hội thoại');
    const events = this.chat.ask(id, body.content, {
      includeExpired: body.includeExpired,
      asOf: body.asOf,
    });
    return new Response(toStream(events), {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no', // không để proxy gom luồng
      },
    });
  }
}

/**
 * Luồng byte từ generator. Client ngắt kết nối -> Nest hủy luồng -> cancel() kết thúc generator,
 * khối finally của nó hủy request tới libris-ai.
 */
function toStream(events: AsyncGenerator<string>): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { value, done } = await events.next();
      if (done) controller.close();
      else controller.enqueue(encoder.encode(value));
    },
    async cancel() {
      await events.return(undefined);
    },
  });
}
