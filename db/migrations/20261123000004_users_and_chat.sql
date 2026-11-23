-- migrate:up

CREATE TYPE user_role AS ENUM ('USER', 'ADMIN');
CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         text NOT NULL,
  password_hash text NOT NULL,
  full_name     text,
  role          user_role NOT NULL DEFAULT 'USER',
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Email không phân biệt hoa/thường
CREATE UNIQUE INDEX users_email_key ON users (lower(email));

CREATE TRIGGER users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE chat_sessions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  title       text,
  archived_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Danh sách hội thoại gần nhất của một người dùng
CREATE INDEX chat_sessions_user_idx ON chat_sessions (user_id, updated_at DESC);

CREATE TRIGGER chat_sessions_updated_at
  BEFORE UPDATE ON chat_sessions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE chat_messages (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  uuid NOT NULL REFERENCES chat_sessions (id) ON DELETE CASCADE,
  role        message_role NOT NULL,
  content     text NOT NULL,
  -- Thông tin sinh câu trả lời: mô hình, số token, thời gian, cache hit...
  metadata    jsonb NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX chat_messages_session_idx ON chat_messages (session_id, created_at);

-- Trích dẫn đi kèm từng câu trả lời: thẻ [Điều X, Khoản Y - Số hiệu] trỏ tới đoạn luật gốc.
-- document_number + label được lưu lại để lịch sử hội thoại vẫn hiển thị đúng
-- kể cả khi đoạn luật bị xóa/cắt lại sau này.
CREATE TABLE message_citations (
  message_id      uuid NOT NULL REFERENCES chat_messages (id) ON DELETE CASCADE,
  position        integer NOT NULL,           -- thứ tự thẻ trích dẫn trong câu trả lời
  chunk_id        uuid REFERENCES legal_chunks (id) ON DELETE SET NULL,
  document_id     uuid REFERENCES legal_documents (id) ON DELETE SET NULL,
  document_number text NOT NULL,
  label           text NOT NULL,              -- Điều 7, Khoản 2 - 168/2024/NĐ-CP
  quote           text,                       -- đoạn nguyên văn được dẫn
  score           real,                       -- điểm reranker
  PRIMARY KEY (message_id, position)
);

CREATE INDEX message_citations_chunk_idx ON message_citations (chunk_id);

-- migrate:down
DROP TABLE IF EXISTS message_citations;
DROP TABLE IF EXISTS chat_messages;
DROP TABLE IF EXISTS chat_sessions;
DROP TABLE IF EXISTS users;
DROP TYPE IF EXISTS message_role;
DROP TYPE IF EXISTS user_role;
