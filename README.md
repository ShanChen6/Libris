# Libris – Trợ lý Pháp luật

Hệ thống hỏi đáp & tra cứu văn bản quy phạm pháp luật Việt Nam dựa trên RAG (Retrieval-Augmented Generation), có trích dẫn điều khoản nguyên văn và kiểm soát hiệu lực văn bản theo thời gian.

## Kiến trúc

| Phân hệ | Công nghệ |
|---|---|
| `libris-web` | Next.js (App Router), TailwindCSS, Shadcn/UI |
| `libris-api` | NestJS, JWT Auth & RBAC |
| `libris-ai` | Python FastAPI, LangChain / LlamaIndex, `BAAI/bge-m3`, `bge-reranker-v2-m3` |
| Database | PostgreSQL + `pgvector` + `tsvector`, Redis |

## Cấu trúc thư mục

```
Libris/
├── libris-web/          # Next.js 16 (App Router) + TailwindCSS 4 + shadcn/ui
├── libris-api/          # NestJS 12 – Auth, quản lý hội thoại, gateway
├── libris-ai/           # FastAPI (Python 3.12, uv) – RAG pipeline
├── db/                  # Migration SQL (dbmate) + schema.sql – xem db/README.md
├── docker/postgres/     # Script khởi tạo PostgreSQL (CREATE EXTENSION vector)
├── docker-compose.yml   # PostgreSQL 17 + pgvector, Redis
└── docs/ROADMAP.md
```

## Chạy môi trường phát triển

Yêu cầu: Docker, Node.js 22+, [uv](https://docs.astral.sh/uv/).

**1. Hạ tầng (PostgreSQL + pgvector, Redis)**

```bash
cp .env.example .env
docker compose up -d --wait
docker compose run --rm migrate      # tạo bảng (xem db/README.md)
```

**2. libris-ai** – http://localhost:8000 (tài liệu API: `/docs`)

```bash
cd libris-ai
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

**3. libris-api** – http://localhost:4000 (chi tiết API: [libris-api/README.md](libris-api/README.md))

```bash
cd libris-api
cp .env.example .env    # điền JWT_SECRET (openssl rand -base64 32), ADMIN_EMAIL/ADMIN_PASSWORD
npm install             # dùng npm 11+
npm run start:dev
```

**4. libris-web** – http://localhost:3000

```bash
cd libris-web
cp .env.example .env.local
npm install
npm run dev
```

### Kiểm tra sức khỏe dịch vụ

| Dịch vụ | Endpoint |
|---|---|
| libris-ai | `GET :8000/health`, `GET :8000/health/ready` (kiểm tra Postgres/pgvector & Redis) |
| libris-api | `GET :4000/health` |

`libris-api` gọi `libris-ai` bằng token nội bộ: đặt cùng một giá trị cho `AI_SERVICE_TOKEN`
(libris-api) và `INTERNAL_API_TOKEN` (libris-ai), tạo bằng `openssl rand -hex 32`.

### Thu thập dữ liệu pháp luật

```bash
cd libris-ai
uv run python -m crawler crawl       # văn bản trong crawler/seeds.yaml -> libris-ai/data/
uv run python -m crawler normalize   # chuẩn hóa metadata, trạng thái hiệu lực -> data/catalog.json
uv run python -m crawler load-db     # nạp vào PostgreSQL
uv run python -m app.pipeline chunk  # cắt văn bản theo Điều/Khoản/Điểm -> legal_chunks
uv run python -m app.pipeline embed  # sinh embedding bge-m3 (lần đầu tải mô hình ~2,3 GB)
cd .. && docker compose run --rm migrate   # tạo chỉ mục HNSW + GIN
```

Tra thử truy xuất (Router → Hybrid Search → Rerank), chi tiết trong
[libris-ai/app/retrieval/README.md](libris-ai/app/retrieval/README.md):

```bash
cd libris-ai
uv run python -m app.pipeline search "Đi xe máy không có gương chiếu hậu bên trái có bị phạt không?"
```

Hỏi đáp có trích dẫn (cần `LLM_API_KEY` trong `libris-ai/.env`, xem
[libris-ai/app/generation/README.md](libris-ai/app/generation/README.md)):

```bash
uv run python -m app.pipeline ask "Thời gian thử việc tối đa là bao lâu?"
```

Chi tiết nguồn dữ liệu, cách OCR bản scan và định dạng đầu ra: [libris-ai/crawler/README.md](libris-ai/crawler/README.md).

## Tài liệu

- [Lộ trình triển khai (12 tuần)](docs/ROADMAP.md)
- Hỏi đáp có trích dẫn: [libris-ai/app/generation/README.md](libris-ai/app/generation/README.md)
- Phân tích hợp đồng: [libris-ai/app/analysis/README.md](libris-ai/app/analysis/README.md)
- Đánh giá (Golden Dataset, RAGAS, Semantic Cache): [libris-ai/eval/README.md](libris-ai/eval/README.md)
- API cho giao diện: [libris-api/README.md](libris-api/README.md); giao diện: [libris-web/README.md](libris-web/README.md)

## Quy trình nhánh

- `main`: nhánh ổn định, chỉ nhận merge từ `develop`.
- `develop`: nhánh phát triển, mọi commit được thực hiện tại đây.
