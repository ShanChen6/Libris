import {
  Injectable,
  Logger,
  PayloadTooLargeException,
  ServiceUnavailableException,
  UnprocessableEntityException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Env } from '../config/env.js';

export interface IngestMetadata {
  documentNumber: string;
  title: string;
  documentType?: string;
  issuingBody?: string;
  signer?: string;
  issueDate?: string;
  effectiveDate?: string;
}

export interface UploadedFile {
  originalname: string;
  mimetype: string;
  buffer: Buffer;
}

export interface AnswerOptions {
  includeExpired?: boolean;
  asOf?: string;
}

/** Gọi libris-ai (FastAPI) bằng token nội bộ. */
@Injectable()
export class AiClient {
  private readonly logger = new Logger(AiClient.name);
  private readonly baseUrl: string;
  private readonly token: string;

  constructor(config: ConfigService<Env, true>) {
    this.baseUrl = config
      .get('AI_SERVICE_URL', { infer: true })
      .replace(/\/$/, '');
    this.token = config.get('AI_SERVICE_TOKEN', { infer: true });
  }

  private headers(): Record<string, string> {
    return this.token ? { 'X-Internal-Token': this.token } : {};
  }

  /**
   * Mở luồng SSE hỏi đáp (POST /answer/stream). Trả về body để đọc dần; `signal` hủy request
   * (VD người dùng đóng trang) và libris-ai ngừng sinh câu trả lời.
   */
  async streamAnswer(
    question: string,
    options: AnswerOptions,
    signal: AbortSignal,
  ): Promise<ReadableStream<Uint8Array>> {
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}/answer/stream`, {
        method: 'POST',
        headers: {
          ...this.headers(),
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({
          question,
          include_expired: options.includeExpired ?? null,
          as_of: options.asOf ?? null,
        }),
        signal,
      });
    } catch (error) {
      if (signal.aborted) throw error;
      this.logger.error(
        `Không gọi được libris-ai: ${(error as Error).message}`,
      );
      throw new ServiceUnavailableException(
        'Dịch vụ hỏi đáp (libris-ai) không phản hồi',
      );
    }
    if (!res.ok || !res.body) {
      this.logger.error(`libris-ai /answer/stream trả về HTTP ${res.status}`);
      throw new ServiceUnavailableException('Dịch vụ hỏi đáp (libris-ai) lỗi');
    }
    return res.body;
  }

  /**
   * Phân tích hợp đồng (POST /analyze/stream, Task 4.4): gửi một file hoặc văn bản, nhận luồng
   * SSE `progress`* → `done` | `error`. Lỗi đầu vào libris-ai phát hiện ngay (sai định dạng, quá
   * lớn) thành 422/413 trước khi mở luồng. Hủy luồng trả về = đóng kết nối tới libris-ai.
   */
  async analyzeStream(input: {
    file?: UploadedFile;
    text?: string;
  }): Promise<ReadableStream<Uint8Array>> {
    const form = new FormData();
    if (input.file) {
      form.append(
        'file',
        new Blob([new Uint8Array(input.file.buffer)], {
          type: input.file.mimetype,
        }),
        input.file.originalname,
      );
    }
    if (input.text) form.append('text', input.text);
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}/analyze/stream`, {
        method: 'POST',
        headers: { ...this.headers(), Accept: 'text/event-stream' },
        body: form,
      });
    } catch (error) {
      this.logger.error(
        `Không gọi được libris-ai: ${(error as Error).message}`,
      );
      throw new ServiceUnavailableException(
        'Dịch vụ phân tích văn bản (libris-ai) không phản hồi',
      );
    }
    if (res.status === 422 || res.status === 413) {
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
      const message = describeDetail(body.detail) ?? 'Dữ liệu không hợp lệ';
      throw res.status === 413
        ? new PayloadTooLargeException(message)
        : new UnprocessableEntityException(message);
    }
    if (!res.ok || !res.body) {
      this.logger.error(`libris-ai /analyze/stream trả về HTTP ${res.status}`);
      throw new ServiceUnavailableException(
        'Dịch vụ phân tích văn bản (libris-ai) lỗi',
      );
    }
    return res.body;
  }

  /** Gửi file sang pipeline nạp văn bản; trả về id của job xử lý nền. */
  async ingest(
    file: UploadedFile,
    meta: IngestMetadata,
    createdBy: string,
  ): Promise<{ jobId: string }> {
    const form = new FormData();
    form.append(
      'file',
      new Blob([new Uint8Array(file.buffer)], { type: file.mimetype }),
      file.originalname,
    );
    const fields: Record<string, string | undefined> = {
      document_number: meta.documentNumber,
      title: meta.title,
      document_type: meta.documentType,
      issuing_body: meta.issuingBody,
      signer: meta.signer,
      issue_date: meta.issueDate,
      effective_date: meta.effectiveDate,
      created_by: createdBy,
    };
    for (const [key, value] of Object.entries(fields)) {
      if (value) form.append(key, value);
    }

    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}/ingest`, {
        method: 'POST',
        headers: this.headers(),
        body: form,
        signal: AbortSignal.timeout(60_000),
      });
    } catch (error) {
      this.logger.error(
        `Không gọi được libris-ai: ${(error as Error).message}`,
      );
      throw new ServiceUnavailableException(
        'Dịch vụ xử lý văn bản (libris-ai) không phản hồi',
      );
    }
    const body = (await res.json().catch(() => ({}))) as {
      job_id?: string;
      detail?: unknown;
    };
    if (res.status === 422) {
      throw new UnprocessableEntityException(
        describeDetail(body.detail) ?? 'File không hợp lệ',
      );
    }
    if (!res.ok || !body.job_id) {
      this.logger.error(
        `libris-ai trả về HTTP ${res.status}: ${JSON.stringify(body)}`,
      );
      throw new ServiceUnavailableException(
        'Dịch vụ xử lý văn bản (libris-ai) lỗi',
      );
    }
    return { jobId: body.job_id };
  }
}

/** FastAPI trả `detail` dạng chuỗi (lỗi nghiệp vụ) hoặc danh sách lỗi validation. */
function describeDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map(
        (d: { loc?: unknown[]; msg?: string }) =>
          `${(d.loc ?? []).join('.')}: ${d.msg ?? ''}`,
      )
      .join('; ');
  }
  return undefined;
}
