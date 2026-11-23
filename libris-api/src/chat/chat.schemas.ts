import { z } from 'zod';

export const createSessionSchema = z.object({
  title: z.string().trim().min(1).max(200).optional(),
});
export const renameSessionSchema = z.object({
  title: z.string().trim().min(1).max(200),
});

export const listSessionsSchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(30),
  // con trỏ "updatedAt|id" lấy từ nextCursor của trang trước
  cursor: z
    .string()
    .regex(/^[^|]+\|[0-9a-f-]{36}$/i)
    .transform((v) => {
      const [updatedAt, id] = v.split('|');
      return { updatedAt, id };
    })
    .optional(),
});

export const askSchema = z.object({
  content: z.string().trim().min(1, 'Câu hỏi không được để trống').max(2000),
  // Ghi đè Query Router: xem cả văn bản đã hết hiệu lực / theo một ngày cụ thể
  includeExpired: z.boolean().optional(),
  asOf: z.iso.date().optional(),
});

export type AskInput = z.infer<typeof askSchema>;
