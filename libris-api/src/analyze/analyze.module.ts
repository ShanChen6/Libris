import { Module } from '@nestjs/common';
import { AnalyzeController } from './analyze.controller.js';

@Module({ controllers: [AnalyzeController] })
export class AnalyzeModule {}
