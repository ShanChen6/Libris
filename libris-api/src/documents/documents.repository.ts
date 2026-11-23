import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../database/database.service.js';
import { isUuid } from '../users/users.repository.js';

export type DocumentStatus = 'ACTIVE' | 'AMENDED' | 'EXPIRED' | 'PENDING';

export interface DocumentFilters {
  status?: DocumentStatus[];
  type?: string;
  q?: string;
  limit: number;
}

const SUMMARY = `
  d.id, d.document_number AS "documentNumber", d.document_type AS "documentType", d.title,
  d.issuing_body AS "issuingBody", d.issue_date AS "issueDate",
  d.effective_date AS "effectiveDate", d.expiry_date AS "expiryDate", d.status,
  d.needs_review AS "needsReview", d.source, d.source_url AS "sourceUrl",
  d.updated_at AS "updatedAt",
  (SELECT count(*)::int FROM legal_chunks c WHERE c.document_id = d.id) AS chunks`;

@Injectable()
export class DocumentsRepository {
  constructor(private readonly db: DatabaseService) {}

  async list(filters: DocumentFilters) {
    const { rows } = await this.db.query(
      `SELECT ${SUMMARY} FROM legal_documents d
       WHERE ($1::text[] IS NULL OR d.status::text = ANY($1))
         AND ($2::text IS NULL OR d.document_type = $2)
         AND ($3::text IS NULL OR d.document_number ILIKE '%' || $3 || '%'
              OR d.title ILIKE '%' || $3 || '%')
       ORDER BY d.issue_date DESC NULLS LAST, d.document_number
       LIMIT $4`,
      [
        filters.status ?? null,
        filters.type ?? null,
        filters.q ?? null,
        filters.limit,
      ],
    );
    return rows;
  }

  /** Chi tiết văn bản kèm quan hệ hiệu lực (không kèm nguyên văn – lấy riêng khi cần). */
  async findById(id: string) {
    if (!isUuid(id)) return null;
    const { rows } = await this.db.query(
      `SELECT ${SUMMARY}, d.signer, d.metadata->'warnings' AS warnings FROM legal_documents d
       WHERE d.id = $1`,
      [id],
    );
    const doc = rows[0];
    if (!doc) return null;
    const relations = await this.db.query(
      `SELECT relation_type AS type, source_number AS "source", target_number AS target,
              effective_date AS "effectiveDate", evidence
       FROM document_relations WHERE source_number = $1 OR target_number = $1
       ORDER BY effective_date NULLS LAST, source_number, target_number`,
      [doc.documentNumber],
    );
    const superseded = await this.db.query(
      `SELECT article, nullif(clause, '') AS clause, kind, source_number AS "source",
              effective_date AS "effectiveDate"
       FROM superseded_provisions WHERE target_number = $1
       ORDER BY source_number, article, clause`,
      [doc.documentNumber],
    );
    return {
      ...doc,
      relations: relations.rows,
      supersededProvisions: superseded.rows,
    };
  }

  /** Nguyên văn văn bản – để xem và bôi vàng đoạn được trích dẫn (Task 4.3). */
  async fullText(id: string): Promise<string | null> {
    if (!isUuid(id)) return null;
    const { rows } = await this.db.query<{ full_text: string }>(
      'SELECT full_text FROM legal_documents WHERE id = $1',
      [id],
    );
    return rows[0]?.full_text ?? null;
  }

  /**
   * Xóa văn bản (đoạn luật xóa theo khóa ngoại) cùng các quan hệ do nó quy định, rồi tính lại
   * trạng thái hiệu lực: VD xóa luật mới thì luật cũ nó thay thế trở lại ACTIVE.
   */
  async delete(id: string): Promise<{ documentNumber: string } | null> {
    if (!isUuid(id)) return null;
    return this.db.transaction(async (tx) => {
      const { rows } = await tx.query<{ document_number: string }>(
        'DELETE FROM legal_documents WHERE id = $1 RETURNING document_number',
        [id],
      );
      if (!rows[0]) return null;
      const number = rows[0].document_number;
      await tx.query(
        'DELETE FROM document_relations WHERE source_number = $1',
        [number],
      );
      await tx.query(
        'DELETE FROM superseded_provisions WHERE source_number = $1',
        [number],
      );
      await tx.query('SELECT recompute_document_status()');
      return { documentNumber: number };
    });
  }

  async listIngestions(limit: number) {
    const { rows } = await this.db.query(
      `SELECT ${INGESTION} FROM ingestion_jobs j
       ORDER BY j.created_at DESC LIMIT $1`,
      [limit],
    );
    return rows;
  }

  async findIngestion(id: string) {
    if (!isUuid(id)) return null;
    const { rows } = await this.db.query(
      `SELECT ${INGESTION} FROM ingestion_jobs j WHERE j.id = $1`,
      [id],
    );
    return rows[0] ?? null;
  }
}

const INGESTION = `
  j.id, j.status, j.step, j.filename, j.size_bytes AS "sizeBytes",
  j.document_number AS "documentNumber", j.metadata, j.document_id AS "documentId", j.chunks,
  j.warnings, j.error, j.created_by AS "createdBy", j.created_at AS "createdAt",
  j.started_at AS "startedAt", j.finished_at AS "finishedAt"`;
