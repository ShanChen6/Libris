import {
  BadRequestException,
  Body,
  Controller,
  Post,
  UploadedFile,
  UseGuards,
  UseInterceptors,
} from '@nestjs/common';
import { Can } from '@nestjs/authorization';
import { FileInterceptor } from '@nestjs/platform-express';
import { Throttle, ThrottlerGuard } from '@nestjs/throttler';
import { extname } from 'node:path';
import { z } from 'zod';
import { AiClient, type UploadedFile as File } from '../ai/ai.client.js';

export const ANALYZE_EXTENSIONS = ['.pdf', '.doc', '.docx'];
const MAX_BYTES = 10 * 1024 * 1024;

const analyzeSchema = z.object({
  text: z.string().trim().max(200_000).optional(),
});

/**
 * Tóm tắt và phân tích rủi ro văn bản người dùng tải lên (Task 4.4). Văn bản không được lưu:
 * libris-api chỉ chuyển tiếp sang libris-ai và trả lại luồng kết quả.
 */
@Controller('analyze')
@Can.Anyone()
export class AnalyzeController {
  constructor(private readonly ai: AiClient) {}

  /**
   * multipart/form-data: `file` (.pdf/.doc/.docx, tối đa 10 MB) HOẶC `text`. Trả luồng SSE:
   * `progress` {step, message}* → `done` {document_type, summary, key_terms, issues, text, ...}
   * | `error` {message}.
   */
  @Post()
  @UseGuards(ThrottlerGuard)
  @Throttle({ default: { limit: 5, ttl: 60_000 } }) // mỗi lần phân tích gọi LLM 2 lượt
  @UseInterceptors(
    FileInterceptor('file', { limits: { fileSize: MAX_BYTES, files: 1 } }),
  )
  async analyze(
    @UploadedFile() file: File | undefined,
    @Body({ schema: analyzeSchema }) body: z.infer<typeof analyzeSchema>,
  ) {
    const text = body.text || undefined;
    if (!file === !text)
      throw new BadRequestException(
        'Gửi một file (trường "file") hoặc nội dung văn bản (trường "text")',
      );
    if (
      file &&
      !ANALYZE_EXTENSIONS.includes(extname(file.originalname).toLowerCase())
    ) {
      throw new BadRequestException(
        `Chỉ nhận file ${ANALYZE_EXTENSIONS.join(', ')}`,
      );
    }
    const stream = await this.ai.analyzeStream({ file, text });
    // Chuyển tiếp nguyên luồng; người dùng đóng trang -> Nest hủy luồng -> đóng kết nối libris-ai
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    });
  }
}
