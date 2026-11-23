import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  NotFoundException,
  Param,
  Post,
  Query,
  UploadedFile,
  UseInterceptors,
} from '@nestjs/common';
import { CurrentUser } from '@nestjs/authentication';
import { Can } from '@nestjs/authorization';
import { FileInterceptor } from '@nestjs/platform-express';
import { extname } from 'node:path';
import { z } from 'zod';
import { AdminPolicy } from '../auth/admin.policy.js';
import type { User } from '../users/user.model.js';
import { AiClient, type UploadedFile as File } from '../ai/ai.client.js';
import { DocumentsRepository } from './documents.repository.js';
import {
  ALLOWED_EXTENSIONS,
  uploadDocumentSchema,
  type UploadDocument,
} from './documents.schemas.js';

const MAX_UPLOAD_BYTES = Number(process.env.MAX_UPLOAD_MB ?? 30) * 1024 * 1024;
const limitSchema = z.object({
  limit: z.coerce.number().int().min(1).max(200).default(50),
});

/** Quản trị kho văn bản: chỉ ADMIN. */
@Controller('admin')
@Can(AdminPolicy, 'manage')
export class AdminDocumentsController {
  constructor(
    private readonly documents: DocumentsRepository,
    private readonly ai: AiClient,
  ) {}

  /**
   * Tải lên văn bản (.pdf, .doc, .docx) kèm thông tin cơ bản. libris-ai xử lý nền (OCR nếu là bản
   * scan, cắt đoạn, embedding); theo dõi tiến trình ở GET /admin/ingestions/:id.
   */
  @Post('documents')
  @HttpCode(202)
  @UseInterceptors(
    FileInterceptor('file', {
      limits: { fileSize: MAX_UPLOAD_BYTES, files: 1 },
    }),
  )
  async upload(
    @UploadedFile() file: File | undefined,
    @Body({ schema: uploadDocumentSchema }) body: UploadDocument,
    @CurrentUser() user: User,
  ) {
    if (!file)
      throw new BadRequestException('Thiếu file văn bản (trường "file")');
    if (
      !ALLOWED_EXTENSIONS.includes(extname(file.originalname).toLowerCase())
    ) {
      throw new BadRequestException(
        `Chỉ nhận file ${ALLOWED_EXTENSIONS.join(', ')}`,
      );
    }
    const { jobId } = await this.ai.ingest(file, body, user.id);
    return { jobId, status: 'queued', statusUrl: `/admin/ingestions/${jobId}` };
  }

  @Delete('documents/:id')
  @HttpCode(204)
  async remove(@Param('id') id: string) {
    if (!(await this.documents.delete(id)))
      throw new NotFoundException('Không tìm thấy văn bản');
  }

  @Get('ingestions')
  listIngestions(
    @Query({ schema: limitSchema }) query: z.infer<typeof limitSchema>,
  ) {
    return this.documents.listIngestions(query.limit);
  }

  @Get('ingestions/:id')
  async getIngestion(@Param('id') id: string) {
    const job = await this.documents.findIngestion(id);
    if (!job) throw new NotFoundException('Không tìm thấy lượt tải lên');
    return job;
  }
}
