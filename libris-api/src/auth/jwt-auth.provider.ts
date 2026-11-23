import { Injectable } from '@nestjs/common';
import {
  AuthenticationRegistry,
  JwtBearerProvider,
  type JwtClaims,
} from '@nestjs/authentication';
import { UsersRepository } from '../users/users.repository.js';
import type { User } from '../users/user.model.js';

/** Xác thực "Authorization: Bearer <access token>" do chính API phát hành. */
@Injectable()
export class JwtAuth extends JwtBearerProvider<User> {
  constructor(
    private readonly users: UsersRepository,
    registry: AuthenticationRegistry,
  ) {
    super(); // kiểm tra bằng accessToken options của AuthenticationModule
    registry.registerProvider(this);
  }

  // Đọc lại người dùng ở mỗi request: tài khoản bị khóa hoặc đổi vai trò có hiệu lực ngay
  validate({ sub }: JwtClaims) {
    return sub ? this.users.findById(sub) : null;
  }
}
