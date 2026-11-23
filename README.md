# Libris – Trợ lý Pháp luật

Hệ thống hỏi đáp & tra cứu văn bản quy phạm pháp luật Việt Nam dựa trên RAG (Retrieval-Augmented Generation), có trích dẫn điều khoản nguyên văn và kiểm soát hiệu lực văn bản theo thời gian.

## Kiến trúc

| Phân hệ | Công nghệ |
|---|---|
| `libris-web` | Next.js (App Router), TailwindCSS, Shadcn/UI |
| `libris-api` | NestJS, JWT Auth & RBAC |
| `libris-ai` | Python FastAPI, LangChain / LlamaIndex, `BAAI/bge-m3`, `bge-reranker-v2-m3` |
| Database | PostgreSQL + `pgvector` + `tsvector`, Redis |

## Tài liệu

- [Lộ trình triển khai (12 tuần)](docs/ROADMAP.md)

## Quy trình nhánh

- `main`: nhánh ổn định, chỉ nhận merge từ `develop`.
- `develop`: nhánh phát triển, mọi commit được thực hiện tại đây.
