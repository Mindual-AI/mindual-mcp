# src/index/ocr_ingest.py
"""
OCR 결과 JSON → 문장 단위 split → Chroma 인덱스 빌드.

입력 JSON 예시:
{
  "manual_id": "aircon_samsung_2025_ko",
  "brand": "...",
  "pages": [
    {"page": 1, "text": "..."},
    {"page": 2, "text": "..."}
  ]
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from src.parse.parse_text import split_korean_sentences
from src.index.chroma_store import get_collection


def build_index_from_json(json_path: Path) -> int:
    data = json.loads(json_path.read_text(encoding="utf-8"))

    pages = data.get("pages", [])
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    ids: List[str] = []

    for p in pages:
        page_no = int(p["page"])
        page_text = p.get("text", "") or ""
        sents = split_korean_sentences(page_text)

        for idx, sent in enumerate(sents):
            documents.append(sent)
            metadatas.append(
                {
                    "document": sent,
                    "page": page_no,
                    "index_in_page": idx,
                }
            )
            ids.append(f"{page_no}_{idx}")

    collection = get_collection(reset=True)
    if documents:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)

    print(f"✅ Indexed {len(documents)} sentences from {json_path.name}")
    return len(documents)


def main():
    ap = argparse.ArgumentParser(description="OCR JSON → Chroma 인덱스 빌드")
    ap.add_argument("--json", required=True, help="Step1 JSON 파일 경로")
    args = ap.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        raise SystemExit(f"❌ JSON not found: {json_path}")

    build_index_from_json(json_path)


if __name__ == "__main__":
    main()
