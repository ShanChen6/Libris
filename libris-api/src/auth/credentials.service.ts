import { Injectable } from '@nestjs/common';
import { PasswordHasher } from '@nestjs/authentication';
import { UsersRepository } from '../users/users.repository.js';
import type { Role, User } from '../users/user.model.js';

@Injectable()
export class CredentialsService {
  constructor(
    private readonly users: UsersRepository,
    private readonly passwordHasher: PasswordHasher,
  ) {}

  async register(input: {
    email: string;
    password: string;
    fullName?: string;
    role?: Role;
  }) {
    // Chèn rồi bắt lỗi unique (409) thay vì kiểm tra trước: hai yêu cầu đồng thời không lọt
    return this.users.create({
      email: input.email,
      passwordHash: await this.passwordHasher.hash(input.password),
      fullName: input.fullName,
      role: input.role,
    });
  }

  /** Người dùng, hoặc null khi sai email hoặc mật khẩu (thời gian xử lý như nhau). */
  async verify(email: string, password: string): Promise<User | null> {
    const found = await this.users.findCredentials(email);
    // Không có tài khoản: verify() vẫn kiểm tra một hash giả, nên không lộ email nào đã đăng ký
    const valid = await this.passwordHasher.verify(
      password,
      found?.passwordHash,
    );
    if (!valid || !found) return null;
    if (this.passwordHasher.needsRehash(found.passwordHash)) {
      await this.users.updatePasswordHash(
        found.user.id,
        await this.passwordHasher.hash(password),
      );
    }
    return found.user;
  }
}
