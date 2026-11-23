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

  @Get(':id')
  async get(@Param('id') id: string) {
    const doc = await this.documents.findById(id);
    if (!doc) throw new NotFoundException('Không tìm thấy văn bản');
    return doc;
  }
}
