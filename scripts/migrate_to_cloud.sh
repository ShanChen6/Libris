#!/usr/bin/env bash
# Chuyển kho văn bản luật từ PostgreSQL trên máy sang PostgreSQL trên cloud (Neon / Supabase) – Task 6.1.
#
#   TARGET_DATABASE_URL='postgresql://USER:PASS@HOST/DB?sslmode=require' scripts/migrate_to_cloud.sh
#
# 1. Chạy migration (dbmate) trên DB đích: tạo extension vector, bảng, chỉ mục.
# 2. Copy dữ liệu kho văn bản: legal_documents, document_relations, superseded_provisions,
#    legal_chunks (kèm embedding). KHÔNG copy tài khoản, lịch sử chat, job nạp văn bản.
# 3. So khớp số dòng hai bên.
# Chỉ cần Docker (dùng image dbmate và pgvector có sẵn pg_dump/psql 17). DB đích phải còn trống.
set -euo pipefail

: "${TARGET_DATABASE_URL:?Đặt TARGET_DATABASE_URL (chuỗi kết nối DB đích, có sslmode=require)}"
SOURCE_DATABASE_URL=${SOURCE_DATABASE_URL:-postgresql://libris:libris@localhost:5432/libris}
TABLES=(legal_documents document_relations superseded_provisions legal_chunks)
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PG="docker run --rm -i --network host pgvector/pgvector:0.8.1-pg17"

count() { $PG psql "$1" -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM $2"; }

echo "1/3 Migration trên DB đích"
docker run --rm --network host -v "$ROOT/db:/db:ro" amacneil/dbmate:2.38.2 \
  --url "$TARGET_DATABASE_URL" --migrations-dir /db/migrations --no-dump-schema --wait up

if [ "$(count "$TARGET_DATABASE_URL" legal_documents)" != "0" ]; then
  echo "DB đích đã có dữ liệu văn bản – dừng để tránh trùng lặp." >&2
  exit 1
fi

echo "2/3 Copy dữ liệu: ${TABLES[*]}"
args=(); for t in "${TABLES[@]}"; do args+=(-t "public.$t"); done
$PG pg_dump "$SOURCE_DATABASE_URL" --data-only --no-owner --no-privileges "${args[@]}" \
  | $PG psql "$TARGET_DATABASE_URL" -q -v ON_ERROR_STOP=1 --single-transaction
$PG psql "$TARGET_DATABASE_URL" -q -v ON_ERROR_STOP=1 -c "ANALYZE"

echo "3/3 Kiểm tra"
ok=1
for t in "${TABLES[@]}"; do
  src=$(count "$SOURCE_DATABASE_URL" "$t"); dst=$(count "$TARGET_DATABASE_URL" "$t")
  printf '  %-24s nguồn %6s  đích %6s\n' "$t" "$src" "$dst"
  [ "$src" = "$dst" ] || ok=0
done
[ $ok = 1 ] && echo "Xong." || { echo "Số dòng không khớp!" >&2; exit 1; }
