-- migrate:up
CREATE EXTENSION IF NOT EXISTS vector;

-- Trạng thái hiệu lực (Task 1.3). PENDING: đã ban hành nhưng chưa đến ngày có hiệu lực.
CREATE TYPE document_status AS ENUM ('ACTIVE', 'AMENDED', 'EXPIRED', 'PENDING');

-- Tự cập nhật cột updated_at khi một dòng thay đổi.
CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- migrate:down
DROP FUNCTION IF EXISTS set_updated_at();
DROP TYPE IF EXISTS document_status;
