import {
  Controller,
  Get,
  NotFoundException,
  Param,
  Query,
} from '@nestjs/common';
import { Can } from '@nestjs/authorization';
import { DocumentsRepository } from './documents.repository.js';
import {
  listDocumentsSchema,
  type ListDocuments,
} from './documents.schemas.js';

/** Kho văn bản: mọi người dùng đã đăng nhập được xem. */
@Controller('documents')
@Can.Anyone()
export class DocumentsController {
  constructor(private readonly documents: DocumentsRepository) {}

  @Get()
  list(@Query({ schema: listDocumentsSchema }) query: ListDocuments) {
    return this.documents.list(query);
  }

  /**
   * Chi tiết văn bản kèm nguyên văn (`fullText`). `char_start`/`char_end` của đoạn luật tính theo
   * code point trong `fullText` (JS: cắt bằng `Array.from`, không dùng `String.slice`).
   */
  @Get(':id/text')
  async text(@Param('id') id: string) {
    const [doc, fullText] = await Promise.all([
      this.documents.findById(id),
      this.documents.fullText(id),
    ]);
    if (!doc || fullText === null)
      throw new NotFoundException('Không tìm thấy văn bản');
    return { ...doc, fullText };
  }

  @Get(':id')
  async get(@Param('id') id: string) {
    const doc = await this.documents.findById(id);
    if (!doc) throw new NotFoundException('Không tìm thấy văn bản');
    return doc;
  }
}
