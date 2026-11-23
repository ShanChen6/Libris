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

    # LLM sinh câu trả lời (Task 3.4) qua API tương thích OpenAI. Mặc định: Gemini.
    # Đổi nhà cung cấp chỉ cần đổi base_url + model (VD OpenAI: https://api.openai.com/v1).
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    llm_api_key: str = ""  # trống: không gửi header (proxy của môi trường cloud tự gắn key)
    llm_model: str = "gemini-3.6-flash"
    # Thử lần lượt khi mô hình chính quá tải (429/5xx) hoặc không còn phục vụ (404)
    llm_fallback_models: list[str] = ["gemini-3.5-flash", "gemini-flash-lite-latest"]
    llm_temperature: float = 0.1  # thấp: bám sát văn bản, ít "sáng tạo"
    llm_max_tokens: int = 2048
    llm_reasoning_effort: str | None = "low"  # giảm độ trễ của mô hình có suy luận
    llm_timeout: float = 60.0
    llm_retries: int = 2

    # Chống ảo giác (Task 3.4): từ chối trước khi gọi LLM nếu đoạn liên quan nhất có điểm
    # rerank dưới ngưỡng này (câu trả lời đúng thường >= 0,85; không liên quan gần 0).
    answer_min_rerank_score: float = 0.2

    # Xác thực giữa libris-api và libris-ai (header X-Internal-Token). Trống: không kiểm tra –
    # chỉ dùng khi phát triển trên máy; môi trường triển khai bắt buộc đặt giá trị bí mật.
    internal_api_token: str = ""
    # Văn bản do Admin tải lên (Task 4.1)
    upload_dir: str = "data/uploads"
    max_upload_mb: int = 30

    # Phân tích hợp đồng người dùng tải lên (Task 4.4)
    analysis_max_upload_mb: int = 10
    analysis_max_chars: int = 60_000  # phần vượt quá không đưa cho LLM (báo trong warnings)
    analysis_max_issues: int = 6  # mỗi điểm tốn một lượt tra luật (~8 giây trên CPU)
    analysis_passages_per_issue: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
