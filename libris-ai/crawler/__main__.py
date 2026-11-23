"""CLI thu thập văn bản pháp luật.

Ví dụ:
    uv run python -m crawler crawl                       # crawl theo crawler/seeds.yaml
    uv run python -m crawler fetch 198540                # crawl 1 văn bản theo docid
    uv run python -m crawler list --org quoc-hoi --type luat --pages 2
    uv run python -m crawler normalize               # chuẩn hóa metadata -> data/catalog.json
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from crawler.http import PoliteClient
from crawler.metadata import build_catalog, load_records, write_catalog
from crawler.pipeline import Store, crawl_document, crawl_seeds
from crawler.sources import vanban_chinhphu as vbcp

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEEDS = Path(__file__).resolve().parent / "seeds.yaml"
DEFAULT_DATA = ROOT / "data"


def main() -> None:
    parser = argparse.ArgumentParser(prog="crawler", description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--delay", type=float, default=1.0, help="giây giữa 2 request/host")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_crawl = sub.add_parser("crawl", help="crawl các văn bản trong file seed")
    p_crawl.add_argument("--seeds", type=Path, default=DEFAULT_SEEDS)
    p_crawl.add_argument("--no-ocr", action="store_true")
    p_crawl.add_argument("--force", action="store_true", help="tải và xử lý lại")

    p_fetch = sub.add_parser("fetch", help="crawl văn bản theo docid")
    p_fetch.add_argument("docids", nargs="+")
    p_fetch.add_argument("--no-ocr", action="store_true")
    p_fetch.add_argument("--force", action="store_true")

    p_list = sub.add_parser("list", help="liệt kê văn bản mới nhất (JSON Lines)")
    p_list.add_argument("--org", choices=sorted(vbcp.ORG_GROUPS))
    p_list.add_argument("--type", choices=sorted(vbcp.TYPE_GROUPS))
    p_list.add_argument("--pages", type=int, default=1)

    p_norm = sub.add_parser("normalize", help="chuẩn hóa metadata, suy ra trạng thái hiệu lực")
    p_norm.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.cmd == "crawl":
        summary = crawl_seeds(
            args.seeds, args.data_dir, ocr=not args.no_ocr, force=args.force, delay=args.delay
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.cmd == "fetch":
        store = Store(args.data_dir)
        with PoliteClient(min_interval=args.delay) as client:
            for docid in args.docids:
                rec = crawl_document(client, docid, store, ocr=not args.no_ocr, force=args.force)
                print(store.processed_path(docid), rec["extraction"]["total_pages"], "trang")
    elif args.cmd == "normalize":
        store = Store(args.data_dir)
        entries = build_catalog(load_records(store.processed), args.as_of)
        out = args.data_dir / "catalog.json"
        write_catalog(entries, out, args.as_of)
        for e in entries:
            flags = " ⚠" if e.warnings or e.needs_review else ""
            print(f"{e.status:8} {e.document_number:18} {e.effective_date} {e.title}{flags}")
        print(f"-> {out}")
    elif args.cmd == "list":
        with PoliteClient(min_interval=args.delay) as client:
            for item in vbcp.iter_listing(
                client, org=args.org, doc_type=args.type, max_pages=args.pages
            ):
                row = item.__dict__ | {
                    "issue_date": item.issue_date.isoformat() if item.issue_date else None
                }
                print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
