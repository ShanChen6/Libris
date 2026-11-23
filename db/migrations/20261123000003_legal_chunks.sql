-- migrate:up

-- Đoạn luật đã cắt theo cấu trúc Phần > Chương > Mục > Điều > Khoản > Điểm (Task 2.1).
CREATE TABLE legal_chunks (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id    uuid NOT NULL REFERENCES legal_documents (id) ON DELETE CASCADE,
  chunk_index    integer NOT NULL,
  -- Vị trí trong cấu trúc văn bản (NULL nếu không có cấp tương ứng)
  part           text,              -- Phần thứ nhất
  chapter        text,              -- Chương II
  section        text,              -- Mục 1
  article        text,              -- Điều 7
  article_title  text,              -- Xử phạt người điều khiển xe mô tô...
  clause         text,              -- Khoản 2
  point          text,              -- Điểm a
  -- Tiền tố ngữ cảnh, VD: [Văn bản: Nghị định 168/2024/NĐ-CP | Chương II | Điều 7: ...]
  context_prefix text NOT NULL,
  content        text NOT NULL,
  -- Vị trí của content trong legal_documents.full_text, để bôi vàng đúng đoạn (Task 4.3)
  char_start     integer NOT NULL CHECK (char_start >= 0),
  char_end       integer NOT NULL CHECK (char_end > char_start),
  token_count    integer,
  embedding      vector(1024),      -- BAAI/bge-m3 (Task 2.2)
  -- Full-text search (BM25-like). Cấu hình 'simple' giữ nguyên dấu tiếng Việt:
  -- "đất" và "đặt" là hai từ khác nhau.
  search_vector  tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', context_prefix || ' ' || content)
  ) STORED,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, chunk_index)
);

-- Chỉ mục HNSW (embedding) và GIN (search_vector) được tạo ở Task 2.2, sau khi nạp dữ liệu:
-- dựng HNSW một lần trên dữ liệu đã có nhanh hơn nhiều so với cập nhật dần khi chèn.
CREATE INDEX legal_chunks_document_idx ON legal_chunks (document_id, chunk_index);

-- migrate:down
DROP TABLE IF EXISTS legal_chunks;
