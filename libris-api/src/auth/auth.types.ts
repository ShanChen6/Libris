import type { User } from '../users/user.model.js';

// Cho @nestjs/authentication biết kiểu người dùng: @CurrentUser(), AuthenticationContext...
// API chỉ dùng access token ngắn hạn (không refresh token): người dùng đăng nhập lại khi hết hạn.
declare module '@nestjs/authentication' {
  interface AuthenticationTypes {
    user: User;
    refreshTokens: false;
  }
}
