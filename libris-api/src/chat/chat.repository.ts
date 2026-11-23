import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../database/database.service.js';
import { isUuid } from '../users/users.repository.js';

export interface SessionSummary {
  id: string;
  title: string | null;
  createdAt: Date;
  updatedAt: Date;
}

export interface SavedCitation {
  position: number;
  chunkId: string | null;
  documentNumber: string;
  label: string;
  quote: string | null;
  score: number | null;
}

const SESSION = `s.id, s.title, s.created_at AS "createdAt", s.updated_at AS "updatedAt"`;

/** Phiên hội thoại và tin nhắn: mọi truy vấn lọc theo chủ sở hữu (phiên người khác = không có). */
@Injectable()
export class ChatRepository {
  constructor(private readonly db: DatabaseService) {}

  async createSession(userId: string, title?: string): Promise<SessionSummary> {
    const { rows } = await this.db.query<SessionSummary>(
      `INSERT INTO chat_sessions AS s (user_id, title) VALUES ($1, $2) RETURNING ${SESSION}`,
      [userId, title ?? null],
    );
    return rows[0];
  }

  /** Phiên gần nhất trước; con trỏ là `updatedAt|id` của phần tử cuối trang trước. */
  async listSessions(
    userId: string,
    limit: number,
    before?: { updatedAt: string; id: string },
  ) {
    const { rows } = await this.db.query<SessionSummary>(
      `SELECT ${SESSION} FROM chat_sessions s
       WHERE s.user_id = $1 AND s.archived_at IS NULL
         AND ($3::timestamptz IS NULL OR (s.updated_at, s.id) < ($3, $4::uuid))
       ORDER BY s.updated_at DESC, s.id DESC LIMIT $2`,
      [userId, limit, before?.updatedAt ?? null, before?.id ?? null],
    );
    return rows;
  }

  async findSession(
    userId: string,
    id: string,
  ): Promise<SessionSummary | null> {
    if (!isUuid(id)) return null;
    const { rows } = await this.db.query<SessionSummary>(
      `SELECT ${SESSION} FROM chat_sessions s WHERE s.id = $1 AND s.user_id = $2 AND s.archived_at IS NULL`,
      [id, userId],
    );
    return rows[0] ?? null;
  }

  /** Tin nhắn của phiên kèm trích dẫn; vị trí đoạn luật lấy từ legal_chunks nếu đoạn còn tồn tại. */
  async listMessages(sessionId: string) {
    const { rows } = await this.db.query(
      `SELECT m.id, m.role, m.content, m.metadata, m.created_at AS "createdAt",
         coalesce(json_agg(json_build_object(
           'position', mc.position, 'label', mc.label, 'chunkId', mc.chunk_id,
           'documentId', mc.document_id, 'documentNumber', mc.document_number,
           'quote', mc.quote, 'score', mc.score,
           'charStart', c.char_start, 'charEnd', c.char_end) ORDER BY mc.position)
           FILTER (WHERE mc.message_id IS NOT NULL), '[]') AS citations
       FROM chat_messages m
       LEFT JOIN message_citations mc ON mc.message_id = m.id
       LEFT JOIN legal_chunks c ON c.id = mc.chunk_id
       WHERE m.session_id = $1
       GROUP BY m.id ORDER BY m.created_at, m.id`,
      [sessionId],
    );
    return rows;
  }

  async renameSession(
    userId: string,
    id: string,
    title: string,
  ): Promise<SessionSummary | null> {
    if (!isUuid(id)) return null;
    const { rows } = await this.db.query<SessionSummary>(
      `UPDATE chat_sessions s SET title = $3 WHERE s.id = $1 AND s.user_id = $2 RETURNING ${SESSION}`,
      [id, userId, title],
    );
    return rows[0] ?? null;
  }

  async deleteSession(userId: string, id: string): Promise<boolean> {
    if (!isUuid(id)) return false;
    const { rowCount } = await this.db.query(
      'DELETE FROM chat_sessions WHERE id = $1 AND user_id = $2',
      [id, userId],
    );
    return (rowCount ?? 0) > 0;
  }

  /** Lưu câu hỏi; đặt tiêu đề phiên từ câu hỏi đầu tiên nếu chưa có. */
  async addUserMessage(sessionId: string, content: string): Promise<string> {
    return this.db.transaction(async (tx) => {
      const { rows } = await tx.query<{ id: string }>(
        `INSERT INTO chat_messages (session_id, role, content) VALUES ($1, 'user', $2) RETURNING id`,
        [sessionId, content],
      );
      await tx.query(
        `UPDATE chat_sessions SET title = coalesce(title, $2), updated_at = now() WHERE id = $1`,
        [
          sessionId,
          content.length > 80 ? `${content.slice(0, 79).trimEnd()}…` : content,
        ],
      );
      return rows[0].id;
    });
  }

  async addAssistantMessage(
    sessionId: string,
    content: string,
    metadata: Record<string, unknown>,
    citations: SavedCitation[],
  ): Promise<string> {
    return this.db.transaction(async (tx) => {
      const { rows } = await tx.query<{ id: string }>(
        `INSERT INTO chat_messages (session_id, role, content, metadata)
         VALUES ($1, 'assistant', $2, $3) RETURNING id`,
        [sessionId, content, metadata],
      );
      const messageId = rows[0].id;
      for (const c of citations) {
        await tx.query(
          `INSERT INTO message_citations
             (message_id, position, chunk_id, document_id, document_number, label, quote, score)
           VALUES ($1, $2,
             (SELECT id FROM legal_chunks WHERE id = $3::uuid),
             (SELECT id FROM legal_documents WHERE document_number = $4), $4, $5, $6, $7)`,
          [
            messageId,
            c.position,
            c.chunkId,
            c.documentNumber,
            c.label,
            c.quote,
            c.score,
          ],
        );
      }
      await tx.query(
        'UPDATE chat_sessions SET updated_at = now() WHERE id = $1',
        [sessionId],
      );
      return messageId;
    });
  }
}
