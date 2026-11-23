from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, search
from app.core.config import get_settings
from app.pipeline.embedding import get_embedder


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Tải sẵn mô hình embedding (~2,3 GB, mất 1-2 phút) để request đầu tiên không bị chậm
    if get_settings().embedding_preload:
        _ = get_embedder().dim
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Libris AI",
    description="RAG pipeline cho tra cứu và hỏi đáp văn bản pháp luật Việt Nam",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(search.router)
