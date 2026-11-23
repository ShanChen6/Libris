import { z } from 'zod';

/** Biến để trống trong .env ("ADMIN_EMAIL=") được coi là chưa đặt. */
const optional = <T extends z.ZodType>(schema: T) =>
  z.preprocess((v) => (v === '' ? undefined : v), schema.optional());

/** Biến môi trường của libris-api, kiểm tra khi khởi động: thiếu hoặc sai thì dừng ngay. */
export const envSchema = z.object({
  NODE_ENV: z
    .enum(['development', 'test', 'production'])
    .default('development'),
  PORT: z.coerce.number().int().positive().default(4000),
  WEB_ORIGIN: z.string().default('http://localhost:3000'),
  DATABASE_URL: z.string().min(1),
  // HS256 cần khóa ít nhất 32 byte (openssl rand -base64 32)
  JWT_SECRET: z.string().refine((v) => Buffer.byteLength(v) >= 32, {
    message:
      'JWT_SECRET phải dài ít nhất 32 byte (tạo bằng: openssl rand -base64 32)',
  }),
  JWT_TTL: z.string().default('2h'),
  AI_SERVICE_URL: z.string().url().default('http://localhost:8000'),
  // Trùng với INTERNAL_API_TOKEN của libris-ai
  AI_SERVICE_TOKEN: z.string().default(''),
  MAX_UPLOAD_MB: z.coerce.number().int().positive().default(30),
  // Tạo tài khoản quản trị đầu tiên khi khởi động (nếu chưa có email này)
  ADMIN_EMAIL: optional(z.email()),
  ADMIN_PASSWORD: optional(z.string().min(8)),
});

export type Env = z.infer<typeof envSchema>;

export function validateEnv(config: Record<string, unknown>): Env {
  const result = envSchema.safeParse(config);
  if (!result.success) {
    const issues = result.error.issues.map(
      (i) => `${i.path.join('.')}: ${i.message}`,
    );
    throw new Error(`Cấu hình không hợp lệ:\n- ${issues.join('\n- ')}`);
  }
  return result.data;
}
