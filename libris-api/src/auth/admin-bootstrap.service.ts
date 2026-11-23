import { Injectable, Logger, OnApplicationBootstrap } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Env } from '../config/env.js';
import { UsersRepository } from '../users/users.repository.js';
import { CredentialsService } from './credentials.service.js';

/** Tạo tài khoản quản trị đầu tiên từ ADMIN_EMAIL / ADMIN_PASSWORD nếu email đó chưa có. */
@Injectable()
export class AdminBootstrapService implements OnApplicationBootstrap {
  private readonly logger = new Logger(AdminBootstrapService.name);

  constructor(
    private readonly config: ConfigService<Env, true>,
    private readonly users: UsersRepository,
    private readonly credentials: CredentialsService,
  ) {}

  async onApplicationBootstrap() {
    const email = this.config.get('ADMIN_EMAIL', { infer: true });
    const password = this.config.get('ADMIN_PASSWORD', { infer: true });
    if (!email || !password) return;
    if (await this.users.existsByEmail(email)) return;
    try {
      await this.credentials.register({
        email,
        password,
        fullName: 'Quản trị viên',
        role: 'ADMIN',
      });
      this.logger.log(`Đã tạo tài khoản quản trị ${email}`);
    } catch (error) {
      // Nhiều tiến trình cùng khởi động: tiến trình khác đã tạo trước
      this.logger.warn(
        `Không tạo được tài khoản quản trị: ${(error as Error).message}`,
      );
    }
  }
}
