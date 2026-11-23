import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import pg from 'pg';

/** PostgreSQL thật cho e2e: LIBRIS_TEST_DATABASE_URL=postgresql://libris:libris@localhost:5432/libris */
export const TEST_DB_URL = process.env.LIBRIS_TEST_DATABASE_URL;

const MIGRATIONS = join(import.meta.dirname, '..', '..', 'db', 'migrations');

/** Tạo schema tạm, chạy toàn bộ migration (phần up) vào đó; trả về URL trỏ vào schema. */
export async function createTestSchema(): Promise<{
  url: string;
  drop: () => Promise<void>;
}> {
  const schema = `test_${Math.random().toString(16).slice(2, 10)}`;
  const client = new pg.Client({ connectionString: TEST_DB_URL });
  await client.connect();
  await client.query('CREATE EXTENSION IF NOT EXISTS vector');
  await client.query(`CREATE SCHEMA ${schema}`);
  await client.query(`SET search_path TO ${schema}, public`);
  for (const file of readdirSync(MIGRATIONS)
    .filter((f) => f.endsWith('.sql'))
    .sort()) {
    const up = readFileSync(join(MIGRATIONS, file), 'utf8').split(
      /^-- migrate:down/m,
    )[0];
    await client.query(
      up.replace('CREATE EXTENSION IF NOT EXISTS vector;', ''),
    );
  }
  await client.end();
  const sep = TEST_DB_URL!.includes('?') ? '&' : '?';
  return {
    url: `${TEST_DB_URL}${sep}options=${encodeURIComponent(`-c search_path=${schema},public`)}`,
    drop: async () => {
      const c = new pg.Client({ connectionString: TEST_DB_URL });
      await c.connect();
      await c.query(`DROP SCHEMA ${schema} CASCADE`);
      await c.end();
    },
  };
}
