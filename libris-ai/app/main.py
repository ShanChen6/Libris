from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, search
from app.core.config import get_settings
from app.pipeline.embedding import get_embedder
from app.retrieval.rerank import get_reranker


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Tải sẵn mô hình (~2,3 GB mỗi mô hình, 1-2 phút) để request đầu tiên không bị chậm
    settings = get_settings()
    if settings.embedding_preload:
        _ = get_embedder().dim
    if settings.reranker_preload:
        get_reranker().score("khởi động", ["mô hình"])
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Libris AI",
    description="RAG pipeline cho tra cứu và hỏi đáp văn bản pháp luật Việt Nam",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(search.router)
