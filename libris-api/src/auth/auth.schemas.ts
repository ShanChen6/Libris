import { z } from 'zod';

export const registerSchema = z.object({
  email: z.email().max(254),
  // Độ dài tối thiểu áp dụng khi đăng ký (không áp lúc đăng nhập để mật khẩu cũ vẫn dùng được)
  password: z.string().min(8, 'Mật khẩu tối thiểu 8 ký tự').max(200),
  fullName: z.string().trim().min(1).max(200).optional(),
});
export type RegisterInput = z.infer<typeof registerSchema>;

export const loginSchema = z.object({
  email: z.string().trim().min(1).max(254),
  password: z.string().min(1).max(200),
});
export type LoginInput = z.infer<typeof loginSchema>;
