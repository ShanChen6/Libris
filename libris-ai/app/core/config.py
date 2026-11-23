from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "libris-ai"
    database_url: str = "postgresql://libris:libris@localhost:5432/libris"
    redis_url: str = "redis://localhost:6379/0"

    # Mô hình embedding (Task 2.2). Số chiều phải khớp cột legal_chunks.embedding vector(1024).
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_device: str = "cpu"  # "cuda" nếu có GPU
    # Đoạn luật dài nhất ~1800 ký tự + tiền tố ~700 ký tự ≈ 800 token; 1024 là đủ và nhanh hơn
    # nhiều so với mức tối đa 8192 của bge-m3.
    embedding_max_seq_length: int = 1024
    embedding_batch_size: int = 16
    embedding_preload: bool = False  # tải mô hình ngay khi khởi động API

    # Cross-encoder reranker (Task 3.3): chấm lại Top `rerank_candidates` từ Hybrid Search,
    # giữ Top `rerank_top_n` đưa cho LLM. Trên CPU 4 nhân mất ~0,8 giây / cặp (câu hỏi, đoạn):
    # 20 ứng viên ~16 giây, 10 ứng viên ~9 giây -> chạy CPU nên đặt RERANK_CANDIDATES=10.
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "cpu"
    reranker_max_length: int = 1024
    reranker_batch_size: int = 10
    rerank_candidates: int = 20
    rerank_top_n: int = 5
    reranker_preload: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
