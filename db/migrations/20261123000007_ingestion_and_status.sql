-- migrate:up

-- Văn bản do Admin tải lên qua libris-api -> libris-ai xử lý nền (Task 4.1).
CREATE TABLE ingestion_jobs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status          text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'processing', 'done', 'failed')),
  step            text,                    -- bước đang chạy: extract, chunk, embed...
  filename        text NOT NULL,
  content_type    text,
  size_bytes      integer NOT NULL,
  sha256          text NOT NULL,
  document_number text NOT NULL,
  metadata        jsonb NOT NULL DEFAULT '{}',  -- thông tin Admin nhập kèm file
  document_id     uuid REFERENCES legal_documents (id) ON DELETE SET NULL,
  chunks          integer,
  warnings        jsonb NOT NULL DEFAULT '[]',
  error           text,
  created_by      uuid REFERENCES users (id) ON DELETE SET NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  started_at      timestamptz,
  finished_at     timestamptz
);

CREATE INDEX ingestion_jobs_created_idx ON ingestion_jobs (created_at DESC);

-- Tính lại trạng thái hiệu lực của mọi văn bản từ document_relations / superseded_provisions,
-- để thêm hoặc xóa một văn bản (VD luật mới thay thế luật cũ) cập nhật ngay văn bản liên quan.
CREATE FUNCTION recompute_document_status(as_of date DEFAULT current_date) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  changed integer;
BEGIN
  WITH computed AS (
    SELECT d.id,
      (SELECT min(r.effective_date) FROM document_relations r
        WHERE r.target_number = d.document_number AND r.relation_type = 'replaces'
          AND r.effective_date <= as_of) AS expiry,
      EXISTS (SELECT 1 FROM document_relations r
        WHERE r.target_number = d.document_number AND r.relation_type IN ('amends', 'repeals_part')
          AND r.effective_date <= as_of)
      OR EXISTS (SELECT 1 FROM superseded_provisions sp
        WHERE sp.target_number = d.document_number AND sp.effective_date <= as_of) AS amended
    FROM legal_documents d
  ), next AS (
    SELECT c.id, c.expiry,
      CASE
        WHEN d.effective_date > as_of THEN 'PENDING'
        WHEN c.expiry IS NOT NULL THEN 'EXPIRED'
        WHEN c.amended THEN 'AMENDED'
        ELSE 'ACTIVE'
      END::document_status AS status
    FROM computed c JOIN legal_documents d ON d.id = c.id
  )
  UPDATE legal_documents d
     SET status = n.status, expiry_date = n.expiry, status_as_of = as_of
    FROM next n
   WHERE d.id = n.id
     AND (d.status, d.expiry_date, d.status_as_of) IS DISTINCT FROM (n.status, n.expiry, as_of);
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END;
$$;

-- migrate:down
DROP FUNCTION IF EXISTS recompute_document_status(date);
DROP TABLE IF EXISTS ingestion_jobs;
