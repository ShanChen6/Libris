import { Injectable, OnApplicationShutdown } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pg from 'pg';
import type { Env } from '../config/env.js';

// date (không giờ) giữ dạng 'YYYY-MM-DD' thay vì Date lúc 00:00 giờ máy chủ
pg.types.setTypeParser(pg.types.builtins.DATE, (v: string) => v);

export type Queryable = Pick<pg.PoolClient, 'query'>;

/**
 * Kết nối PostgreSQL dùng chung. Schema do migration SQL ở db/migrations (dbmate) quản lý;
 * dịch vụ này chỉ chạy truy vấn có tham số.
 */
@Injectable()
export class DatabaseService implements OnApplicationShutdown {
  readonly pool: pg.Pool;

  constructor(config: ConfigService<Env, true>) {
    this.pool = new pg.Pool({
      connectionString: config.get('DATABASE_URL'),
      max: 10,
    });
  }

  query<T extends pg.QueryResultRow>(sql: string, params: unknown[] = []) {
    return this.pool.query<T>(sql, params);
  }

  /** Chạy fn trong một transaction; lỗi thì rollback. Không gọi HTTP bên trong. */
  async transaction<T>(fn: (tx: Queryable) => Promise<T>): Promise<T> {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const result = await fn(client);
      await client.query('COMMIT');
      return result;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async onApplicationShutdown() {
    await this.pool.end();
  }
}

/** Mã lỗi PostgreSQL của vi phạm ràng buộc unique. */
export function isUniqueViolation(error: unknown): boolean {
  return (error as { code?: string } | null)?.code === '23505';
}
