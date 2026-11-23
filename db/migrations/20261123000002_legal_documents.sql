-- migrate:up

-- Văn bản quy phạm pháp luật: nguyên văn + metadata đã chuẩn hóa (Task 1.2, 1.3).
CREATE TABLE legal_documents (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_number text NOT NULL UNIQUE,             -- 168/2024/NĐ-CP
  document_type   text,                             -- Luật / Nghị định / Thông tư / Quyết định
  title           text NOT NULL,
  issuing_body    text,
  signer          text,
  issue_date      date,
  effective_date  date,
  expiry_date     date,
  status          document_status NOT NULL DEFAULT 'ACTIVE',
  status_as_of    date,                             -- ngày tính trạng thái hiệu lực
  full_text       text NOT NULL,                    -- nguyên văn đã làm sạch (dùng cho Citation Viewer)
  needs_review    boolean NOT NULL DEFAULT false,   -- có trang OCR / thiếu chữ, cần rà soát
  source          text NOT NULL,                    -- vanban.chinhphu.vn
  source_id       text NOT NULL,                    -- docid trên nguồn
  source_url      text,
  metadata        jsonb NOT NULL DEFAULT '{}',      -- trường gốc, cảnh báo, căn cứ trạng thái
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, source_id),
  CHECK (expiry_date IS NULL OR effective_date IS NULL OR expiry_date >= effective_date)
);

CREATE INDEX legal_documents_status_idx ON legal_documents (status);
CREATE INDEX legal_documents_type_idx ON legal_documents (document_type);

CREATE TRIGGER legal_documents_updated_at
  BEFORE UPDATE ON legal_documents
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Quan hệ giữa các văn bản, suy ra từ điều khoản thi hành (Task 1.3).
-- Dùng số hiệu (không dùng khóa ngoại) vì văn bản đích có thể chưa có trong kho.
CREATE TABLE document_relations (
  source_number   text NOT NULL,   -- văn bản quy định (VD: 31/2024/QH15)
  target_number   text NOT NULL,   -- văn bản bị tác động (VD: 45/2013/QH13)
  relation_type   text NOT NULL
    CHECK (relation_type IN ('replaces', 'repeals_part', 'amends', 'sets_effective_date')),
  effective_date  date,            -- thời điểm quan hệ phát sinh hiệu lực
  evidence        text NOT NULL,   -- câu nguyên văn làm căn cứ
  PRIMARY KEY (source_number, target_number, relation_type)
);

CREATE INDEX document_relations_target_idx ON document_relations (target_number);

-- migrate:down
DROP TABLE IF EXISTS document_relations;
DROP TABLE IF EXISTS legal_documents;
