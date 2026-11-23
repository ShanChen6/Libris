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


@lru_cache
def get_settings() -> Settings:
    return Settings()
