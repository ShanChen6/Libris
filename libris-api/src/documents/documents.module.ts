import { Module } from '@nestjs/common';
import { AdminDocumentsController } from './admin-documents.controller.js';
import { DocumentsController } from './documents.controller.js';
import { DocumentsRepository } from './documents.repository.js';

@Module({
  controllers: [DocumentsController, AdminDocumentsController],
  providers: [DocumentsRepository],
})
export class DocumentsModule {}
