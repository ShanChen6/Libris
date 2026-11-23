import { Global, Module } from '@nestjs/common';
import { AiClient } from './ai.client.js';

/** Client gọi libris-ai (FastAPI), dùng chung cho quản lý văn bản và hỏi đáp. */
@Global()
@Module({
  providers: [AiClient],
  exports: [AiClient],
})
export class AiModule {}
