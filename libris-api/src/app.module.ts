import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { AuthenticationModule } from '@nestjs/authentication';
import { AuthorizationModule } from '@nestjs/authorization';
import { ThrottlerModule } from '@nestjs/throttler';
import { AppController } from './app.controller.js';
import { AuthModule } from './auth/auth.module.js';
import { validateEnv, type Env } from './config/env.js';
import { DatabaseModule } from './database/database.module.js';
import { DocumentsModule } from './documents/documents.module.js';
import { UsersModule } from './users/users.module.js';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      validate: validateEnv,
      cache: true,
    }),
    // Thứ tự quan trọng: guard xác thực (gán người dùng) phải chạy trước guard phân quyền
    AuthenticationModule.forRootAsync({
      inject: [ConfigService],
      useFactory: (config: ConfigService<Env, true>) => ({
        accessToken: {
          key: config.get('JWT_SECRET', { infer: true }),
          ttl: config.get('JWT_TTL', { infer: true }),
        },
        refreshToken: false, // chỉ access token: không cần kho lưu refresh token
      }),
    }),
    AuthorizationModule.forRoot(), // mặc định từ chối route không khai báo @Can()/@Public()
    // Giới hạn đăng nhập/đăng ký: 10 lần mỗi phút mỗi IP (ThrottlerGuard trên AuthController)
    ThrottlerModule.forRoot([{ ttl: 60_000, limit: 10 }]),
    DatabaseModule,
    UsersModule,
    AuthModule,
    DocumentsModule,
  ],
  controllers: [AppController],
})
export class AppModule {}
