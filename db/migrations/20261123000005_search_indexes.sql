-- migrate:up

-- Task 2.2: chỉ mục tìm kiếm. Nên chạy sau khi đã sinh embedding (python -m app.pipeline embed):
-- dựng HNSW một lần trên dữ liệu có sẵn nhanh hơn cập nhật dần; chunk thêm sau vẫn được đánh chỉ mục.

-- Tìm kiếm ngữ nghĩa: vector đã chuẩn hóa L2, dùng khoảng cách cosine (toán tử <=>).
CREATE INDEX legal_chunks_embedding_hnsw_idx ON legal_chunks
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Tìm kiếm từ khóa: số hiệu văn bản, thuật ngữ pháp lý (toán tử @@).
CREATE INDEX legal_chunks_search_vector_idx ON legal_chunks USING gin (search_vector);

-- migrate:down
DROP INDEX IF EXISTS legal_chunks_search_vector_idx;
DROP INDEX IF EXISTS legal_chunks_embedding_hnsw_idx;
