from fastapi import FastAPI

from app.api import health

app = FastAPI(
    title="Libris AI",
    description="RAG pipeline cho tra cứu và hỏi đáp văn bản pháp luật Việt Nam",
    version="0.1.0",
)

app.include_router(health.router)
