import {
  Body,
  Controller,
  Get,
  HttpCode,
  Post,
  UnauthorizedException,
  UseGuards,
} from '@nestjs/common';
import { CurrentUser, Public, TokenService } from '@nestjs/authentication';
import { Can } from '@nestjs/authorization';
import { ThrottlerGuard } from '@nestjs/throttler';
import {
  loginSchema,
  registerSchema,
  type LoginInput,
  type RegisterInput,
} from './auth.schemas.js';
import { CredentialsService } from './credentials.service.js';
import type { User } from '../users/user.model.js';

@Controller('auth')
@UseGuards(ThrottlerGuard) // chống dò mật khẩu: giới hạn số lần gọi mỗi IP
export class AuthController {
  constructor(
    private readonly credentials: CredentialsService,
    private readonly tokens: TokenService,
  ) {}

  @Public()
  @Post('register')
  async register(@Body({ schema: registerSchema }) body: RegisterInput) {
    const user = await this.credentials.register(body);
    return {
      user,
      ...(await this.tokens.issue(user.id, { method: 'password' })),
    };
  }

  @Public()
  @Post('login')
  @HttpCode(200) // đăng nhập không tạo tài nguyên mới
  async login(@Body({ schema: loginSchema }) body: LoginInput) {
    const user = await this.credentials.verify(body.email, body.password);
    // Cùng một câu trả lời cho email không tồn tại và mật khẩu sai
    if (!user)
      throw new UnauthorizedException('Email hoặc mật khẩu không đúng');
    return {
      user,
      ...(await this.tokens.issue(user.id, { method: 'password' })),
    };
  }

  @Get('me')
  @Can.Anyone()
  me(@CurrentUser() user: User) {
    return user;
  }
}
