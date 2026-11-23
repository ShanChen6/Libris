import {
  StandardSchemaValidationPipe,
  type INestApplication,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Env } from './config/env.js';

/** Cấu hình dùng chung cho main.ts và test e2e. */
export function configureApp(app: INestApplication) {
  const config = app.get<ConfigService<Env, true>>(ConfigService);
  app.useGlobalPipes(new StandardSchemaValidationPipe());
  app.enableCors({
    origin: config.get('WEB_ORIGIN', { infer: true }).split(','),
    credentials: true,
  });
  app.enableShutdownHooks();
  return app;
}
