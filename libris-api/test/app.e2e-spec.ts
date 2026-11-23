import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { PasswordHasher } from '@nestjs/authentication';
import pg from 'pg';
import request from 'supertest';
import { vi } from 'vitest';
import { configureApp } from '../src/app.setup.js';
import { AiClient } from '../src/ai/ai.client.js';
import { createTestSchema, TEST_DB_URL } from './db.js';

const ADMIN = { email: 'admin@libris.test', password: 'admin-password-123' };

describe.skipIf(!TEST_DB_URL)('libris-api (e2e)', () => {
  let app: INestApplication;
  let db: pg.Client;
  let drop: () => Promise<void>;
  const ai = { ingest: vi.fn(), streamAnswer: vi.fn() };

  beforeAll(async () => {
    const schema = await createTestSchema();
    drop = schema.drop;
    Object.assign(process.env, {
      DATABASE_URL: schema.url,
      JWT_SECRET: 'test-secret-that-is-at-least-32-bytes-long!!',
      ADMIN_EMAIL: ADMIN.email,
      ADMIN_PASSWORD: ADMIN.password,
      AI_SERVICE_URL: 'http://ai.test',
    });
    const { AppModule } = await import('../src/app.module.js'); // sau khi đặt biến môi trường
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(PasswordHasher)
      .useValue(new PasswordHasher({ logN: 10 })) // băm nhanh cho test
      .overrideProvider(AiClient)
      .useValue(ai)
      .compile();
    app = configureApp(moduleRef.createNestApplication());
    await app.init();
    db = new pg.Client({ connectionString: schema.url });
    await db.connect();
  });

  afterAll(async () => {
    await db?.end();
    await app?.close();
    await drop?.();
  });

  const http = () => request(app.getHttpServer());
  const login = async (email: string, password: string) =>
    (await http().post('/auth/login').send({ email, password }).expect(200))
      .body.accessToken as string;

  it('health is public', async () => {
    await http()
      .get('/health')
      .expect(200, { status: 'ok', service: 'libris-api' });
  });

  it('registers, rejects duplicates and weak passwords', async () => {
    const res = await http()
      .post('/auth/register')
      .send({
        email: 'An@Example.test',
        password: 'mat-khau-123',
        fullName: 'Nguyễn An',
      })
      .expect(201);
    expect(res.body.user).toMatchObject({
      email: 'An@Example.test',
      role: 'USER',
      fullName: 'Nguyễn An',
    });
    expect(res.body.user).not.toHaveProperty('passwordHash');
    expect(res.body.accessToken).toEqual(expect.any(String));

    await http()
      .post('/auth/register')
      .send({ email: 'an@example.TEST', password: 'mat-khau-456' })
      .expect(409);
    const weak = await http()
      .post('/auth/register')
      .send({ email: 'b@example.test', password: '123' });
    expect(weak.status).toBe(400);
    expect(weak.body.message[0]).toContain('password');
  });

  it('logs in and answers the same for unknown email and wrong password', async () => {
    const token = await login('an@example.test', 'mat-khau-123');
    const me = await http()
      .get('/auth/me')
      .set('Authorization', `Bearer ${token}`)
      .expect(200);
    expect(me.body.email).toBe('An@Example.test');

    const wrong = await http()
      .post('/auth/login')
      .send({ email: 'an@example.test', password: 'x' });
    const unknown = await http()
      .post('/auth/login')
      .send({ email: 'nobody@x.test', password: 'x' });
    expect([wrong.status, unknown.status]).toEqual([401, 401]);
    expect(wrong.body.message).toBe(unknown.body.message);

    await http().get('/auth/me').expect(401);
    await http()
      .get('/auth/me')
      .set('Authorization', 'Bearer not-a-token')
      .expect(401);
  });

  it('creates the first admin from ADMIN_EMAIL and enforces roles', async () => {
    const admin = await login(ADMIN.email, ADMIN.password);
    const user = await login('an@example.test', 'mat-khau-123');

    await http()
      .get('/documents')
      .set('Authorization', `Bearer ${user}`)
      .expect(200);
    await http()
      .get('/admin/users')
      .set('Authorization', `Bearer ${user}`)
      .expect(403);
    await http()
      .get('/admin/ingestions')
      .set('Authorization', `Bearer ${user}`)
      .expect(403);

    const users = await http()
      .get('/admin/users')
      .set('Authorization', `Bearer ${admin}`)
      .expect(200);
    expect(
      users.body.items.map((u: { email: string }) => u.email).sort(),
    ).toEqual(['An@Example.test', ADMIN.email]);
    const adminId = users.body.items.find(
      (u: { role: string }) => u.role === 'ADMIN',
    ).id;
    const userId = users.body.items.find(
      (u: { role: string }) => u.role === 'USER',
    ).id;

    // Không hạ quyền admin cuối cùng
    await http()
      .patch(`/admin/users/${adminId}/role`)
      .set('Authorization', `Bearer ${admin}`)
      .send({ role: 'USER' })
      .expect(409);
    // Vai trò đọc lại ở mỗi request: token cũ có quyền mới ngay sau khi được cấp
    await http()
      .patch(`/admin/users/${userId}/role`)
      .set('Authorization', `Bearer ${admin}`)
      .send({ role: 'ADMIN' })
      .expect(200);
    await http()
      .get('/admin/users')
      .set('Authorization', `Bearer ${user}`)
      .expect(200);
    await http()
      .patch(`/admin/users/${userId}/role`)
      .set('Authorization', `Bearer ${admin}`)
      .send({ role: 'USER' })
      .expect(200);
    await http()
      .get('/admin/users')
      .set('Authorization', `Bearer ${user}`)
      .expect(403);
  });

  it('uploads a document to libris-ai and tracks the ingestion', async () => {
    const admin = await login(ADMIN.email, ADMIN.password);
    const auth = { Authorization: `Bearer ${admin}` };
    ai.ingest.mockResolvedValue({
      jobId: '11111111-1111-4111-8111-111111111111',
    });

    const res = await http()
      .post('/admin/documents')
      .set(auth)
      .field('documentNumber', '168/2024/NĐ-CP')
      .field(
        'title',
        'Quy định xử phạt vi phạm hành chính về giao thông đường bộ',
      )
      .field('effectiveDate', '2025-01-01')
      .attach('file', Buffer.from('%PDF-1.4 test'), 'nd-168.pdf')
      .expect(202);
    expect(res.body).toEqual({
      jobId: '11111111-1111-4111-8111-111111111111',
      status: 'queued',
      statusUrl: '/admin/ingestions/11111111-1111-4111-8111-111111111111',
    });
    const [file, meta, createdBy] = ai.ingest.mock.calls[0];
    expect(file.originalname).toBe('nd-168.pdf');
    expect(meta).toMatchObject({
      documentNumber: '168/2024/NĐ-CP',
      effectiveDate: '2025-01-01',
    });
    expect(createdBy).toEqual(expect.any(String));

    await http()
      .post('/admin/documents')
      .set(auth)
      .field('documentNumber', '1/2024/QH15')
      .field('title', 'X')
      .attach('file', Buffer.from('x'), 'notes.txt')
      .expect(400);
    await http()
      .post('/admin/documents')
      .set(auth)
      .field('documentNumber', 'không hợp lệ')
      .field('title', 'X')
      .attach('file', Buffer.from('x'), 'a.pdf')
      .expect(400);
    await http()
      .post('/admin/documents')
      .set(auth)
      .field('documentNumber', '1/2024/QH15')
      .field('title', 'X')
      .expect(400);

    // libris-ai ghi tiến trình vào ingestion_jobs; API đọc trực tiếp từ DB
    const { rows } = await db.query(
      `INSERT INTO ingestion_jobs (filename, size_bytes, sha256, document_number, status, step)
       VALUES ('nd-168.pdf', 10, 'abc', '168/2024/NĐ-CP', 'processing', 'embed') RETURNING id`,
    );
    const job = await http()
      .get(`/admin/ingestions/${rows[0].id}`)
      .set(auth)
      .expect(200);
    expect(job.body).toMatchObject({
      status: 'processing',
      step: 'embed',
      documentNumber: '168/2024/NĐ-CP',
    });
    await http().get('/admin/ingestions/not-a-uuid').set(auth).expect(404);
    expect(
      (await http().get('/admin/ingestions').set(auth).expect(200)).body,
    ).toHaveLength(1);
  });

  it('lists, shows and deletes documents, recomputing validity', async () => {
    const admin = await login(ADMIN.email, ADMIN.password);
    const auth = { Authorization: `Bearer ${admin}` };
    await db.query(`
      INSERT INTO legal_documents (document_number, document_type, title, status, effective_date,
        expiry_date, issue_date, full_text, source, source_id) VALUES
      ('23/2008/QH12', 'Luật', 'Luật Giao thông đường bộ', 'EXPIRED', '2009-07-01', '2025-01-01',
       '2008-11-13', 'Điều 1.', 't', '1'),
      ('36/2024/QH15', 'Luật', 'Luật Trật tự, an toàn giao thông đường bộ', 'ACTIVE', '2025-01-01',
       NULL, '2024-06-27', 'Điều 1.', 't', '2');
      INSERT INTO document_relations VALUES ('36/2024/QH15', '23/2008/QH12', 'replaces',
        '2025-01-01', 'Luật Giao thông đường bộ số 23/2008/QH12 hết hiệu lực');
    `);

    const all = await http().get('/documents').set(auth).expect(200);
    expect(
      all.body.map((d: { documentNumber: string }) => d.documentNumber),
    ).toEqual(['36/2024/QH15', '23/2008/QH12']);
    const active = await http()
      .get('/documents?status=active&q=trật tự')
      .set(auth)
      .expect(200);
    expect(active.body).toHaveLength(1);
    await http().get('/documents?status=bogus').set(auth).expect(400);

    const oldId = all.body[1].id;
    const old = await http().get(`/documents/${oldId}`).set(auth).expect(200);
    expect(old.body).toMatchObject({
      status: 'EXPIRED',
      expiryDate: '2025-01-01',
      chunks: 0,
    });
    expect(old.body.relations[0]).toMatchObject({
      type: 'replaces',
      source: '36/2024/QH15',
    });
    await http()
      .get('/documents/00000000-0000-4000-8000-000000000000')
      .set(auth)
      .expect(404);

    // Xóa luật mới -> luật cũ không còn bị thay thế, trở lại ACTIVE
    await http()
      .delete(`/admin/documents/${all.body[0].id}`)
      .set(auth)
      .expect(204);
    const revived = await http()
      .get(`/documents/${oldId}`)
      .set(auth)
      .expect(200);
    expect(revived.body).toMatchObject({
      status: 'ACTIVE',
      expiryDate: null,
      relations: [],
    });
    await http()
      .delete(`/admin/documents/${all.body[0].id}`)
      .set(auth)
      .expect(404);
  });

  it('chats: streams the answer, stores history with citations, scoped to the owner', async () => {
    const token = await login('an@example.test', 'mat-khau-123');
    const auth = { Authorization: `Bearer ${token}` };
    const { rows: chunk } = await db.query(
      `INSERT INTO legal_documents (document_number, title, full_text, source, source_id)
       VALUES ('168/2024/NĐ-CP', 'Nghị định', 'xxx Phạt tiền 400.000 đồng', 't', 'c') RETURNING id`,
    );
    const { rows: c } = await db.query(
      `INSERT INTO legal_chunks (document_id, chunk_index, article, clause, context_prefix, content,
         char_start, char_end) VALUES ($1, 0, 'Điều 7', 'Khoản 2', '[NĐ 168]', 'Phạt tiền 400.000 đồng', 4, 26)
       RETURNING id`,
      [chunk[0].id],
    );
    const done = {
      answer: 'Phạt tiền 400.000 đồng [Điều 7, Khoản 2 - 168/2024/NĐ-CP].',
      refused: false,
      refusal_reason: null,
      warnings: [],
      model: 'gemini',
      usage: {},
      timings: {},
      plan: { mode: 'current', statuses: ['ACTIVE', 'AMENDED'], reasons: [] },
      citations: [
        {
          label: '[Điều 7, Khoản 2 - 168/2024/NĐ-CP]',
          chunk_id: c[0].id,
          document_number: '168/2024/NĐ-CP',
        },
      ],
      sources: [
        {
          chunk_id: c[0].id,
          content: 'Phạt tiền 400.000 đồng',
          rerank_score: 0.93,
        },
      ],
    };
    ai.streamAnswer.mockImplementation(async () => {
      const enc = new TextEncoder();
      return new ReadableStream({
        start(ctrl) {
          ctrl.enqueue(
            enc.encode(
              'event: meta\ndata: {"sources":[]}\n\nevent: delta\ndata: {"text":"Phạt tiền"}\n\n',
            ),
          );
          ctrl.enqueue(
            enc.encode(`event: done\ndata: ${JSON.stringify(done)}\n\n`),
          );
          ctrl.close();
        },
      });
    });

    const session = await http()
      .post('/chat/sessions')
      .set(auth)
      .send({})
      .expect(201);
    const sessionId = session.body.id as string;
    const res = await http()
      .post(`/chat/sessions/${sessionId}/messages`)
      .set(auth)
      .send({ content: 'Xe máy không có gương chiếu hậu bị phạt bao nhiêu?' })
      .buffer(true)
      .parse((r, cb) => {
        let text = '';
        r.setEncoding('utf8');
        r.on('data', (chunk: string) => (text += chunk));
        r.on('end', () => cb(null, text));
      })
      .expect(200);
    expect(res.headers['content-type']).toContain('text/event-stream');
    const events = (res.body as string)
      .trim()
      .split('\n\n')
      .map((block) => {
        const [event, data] = block.split('\n');
        return { event: event.slice(7), data: JSON.parse(data.slice(6)) };
      });
    expect(events.map((e) => e.event)).toEqual([
      'start',
      'meta',
      'delta',
      'done',
    ]);
    expect(events[0].data).toMatchObject({ sessionId });
    expect(events[3].data.messageId).toEqual(expect.any(String));
    expect(events[3].data.citations[0].document_id).toBe(chunk[0].id);

    // Ngăn xem văn bản gốc: nguyên văn + vị trí đoạn được trích dẫn (Task 4.3)
    const source = await http()
      .get(`/documents/${chunk[0].id}/text`)
      .set(auth)
      .expect(200);
    expect(source.body).toMatchObject({
      documentNumber: '168/2024/NĐ-CP',
      fullText: 'xxx Phạt tiền 400.000 đồng',
    });
    expect([...source.body.fullText].slice(4, 26).join('')).toBe(
      'Phạt tiền 400.000 đồng',
    );
    await http()
      .get('/documents/00000000-0000-4000-8000-000000000000/text')
      .set(auth)
      .expect(404);
    await http().get(`/documents/${chunk[0].id}/text`).expect(401);
    expect(ai.streamAnswer.mock.calls[0][0]).toBe(
      'Xe máy không có gương chiếu hậu bị phạt bao nhiêu?',
    );

    const history = await http()
      .get(`/chat/sessions/${sessionId}`)
      .set(auth)
      .expect(200);
    expect(history.body.title).toBe(
      'Xe máy không có gương chiếu hậu bị phạt bao nhiêu?',
    );
    expect(history.body.messages.map((m: { role: string }) => m.role)).toEqual([
      'user',
      'assistant',
    ]);
    expect(history.body.messages[1].citations).toEqual([
      expect.objectContaining({
        position: 1,
        chunkId: c[0].id,
        documentId: chunk[0].id,
        label: '[Điều 7, Khoản 2 - 168/2024/NĐ-CP]',
        charStart: 4,
        charEnd: 26,
        score: 0.93,
      }),
    ]);
    expect(history.body.messages[1].metadata).toMatchObject({
      refused: false,
      model: 'gemini',
    });

    const list = await http().get('/chat/sessions').set(auth).expect(200);
    expect(list.body.items.map((s: { id: string }) => s.id)).toEqual([
      sessionId,
    ]);

    // Người khác không thấy và không hỏi được trong phiên này
    const other = await login(ADMIN.email, ADMIN.password);
    await http()
      .get(`/chat/sessions/${sessionId}`)
      .set('Authorization', `Bearer ${other}`)
      .expect(404);
    await http()
      .post(`/chat/sessions/${sessionId}/messages`)
      .set('Authorization', `Bearer ${other}`)
      .send({ content: 'x' })
      .expect(404);
    await http()
      .post(`/chat/sessions/${sessionId}/messages`)
      .set(auth)
      .send({ content: ' ' })
      .expect(400);

    await http()
      .patch(`/chat/sessions/${sessionId}`)
      .set(auth)
      .send({ title: 'Giao thông' })
      .expect(200);
    await http().delete(`/chat/sessions/${sessionId}`).set(auth).expect(204);
    await http().get(`/chat/sessions/${sessionId}`).set(auth).expect(404);
  });

  it('throttles repeated sign-in attempts', async () => {
    const statuses: number[] = [];
    for (let i = 0; i < 12; i++) {
      statuses.push(
        (
          await http()
            .post('/auth/login')
            .send({ email: 'x@x.test', password: 'x' })
        ).status,
      );
    }
    expect(statuses).toContain(429);
  });
});
