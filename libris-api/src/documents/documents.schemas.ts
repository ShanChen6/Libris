import { z } from 'zod';

const STATUSES = ['ACTIVE', 'AMENDED', 'EXPIRED', 'PENDING'] as const;

export const listDocumentsSchema = z.object({
  // ?status=ACTIVE,AMENDED
  status: z
    .string()
    .transform((v) => v.split(',').map((s) => s.trim().toUpperCase()))
    .pipe(z.array(z.enum(STATUSES)))
    .optional(),
  type: z.string().trim().min(1).max(50).optional(),
  q: z.string().trim().min(1).max(200).optional(),
  limit: z.coerce.number().int().min(1).max(500).default(200),
});
export type ListDocuments = z.infer<typeof listDocumentsSchema>;

const isoDate = z.iso.date();

/** Trường đi kèm file khi Admin tải văn bản lên (multipart/form-data). */
export const uploadDocumentSchema = z.object({
  documentNumber: z
    .string()
    .trim()
    .regex(
      /^\d{1,4}\/(19|20)\d{2}\/[\p{L}\d-]+$/u,
      'Số hiệu dạng 168/2024/NĐ-CP',
    ),
  title: z.string().trim().min(1).max(1000),
  documentType: z.string().trim().max(50).optional(),
  issuingBody: z.string().trim().max(200).optional(),
  signer: z.string().trim().max(200).optional(),
  issueDate: isoDate.optional(),
  effectiveDate: isoDate.optional(),
});
export type UploadDocument = z.infer<typeof uploadDocumentSchema>;

export const ALLOWED_EXTENSIONS = ['.pdf', '.doc', '.docx'];
