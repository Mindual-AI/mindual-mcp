# scripts/retrieval_poc.py
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import sys

# --- import path bootstrap ---
ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "src"), str(ROOT / "db")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.index.build_embeddings_and_index import search  # search("chunks", query, k)
from src.config import DB_PATH


def load_contexts(rids, manual_id: int | None = None):
    """
    chunks.id 리스트를 받아서
    [{text, page, score, index_in_page}] 형태로 반환하는 헬퍼.
    (지금은 페이지 전체 텍스트 = 1 청크라서 index_in_page=0으로 둠)
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    results = []
    for rid, score in rids:
        row = cur.execute(
            "SELECT manual_id, page, content FROM chunks WHERE id = ?",
            (rid,),
        ).fetchone()
        if not row:
            continue

        man_id, page, content = row
        if manual_id and man_id != manual_id:
            # 혹시 인덱스가 전체 매뉴얼 기준으로 만들어졌을 때 필터링
            continue

        results.append(
            {
                "text": content,
                "page": int(page) if page is not None else None,
                "score": float(score),
                "index_in_page": 0,  # 아직 문장 단위 split 안 했으므로 0으로 고정
            }
        )

    conn.close()
    return results


def main():
    ap = argparse.ArgumentParser(description="Simple RAG Retrieval POC (chunks 기반)")
    ap.add_argument("--query", required=True, help="사용자 질문 텍스트")
    ap.add_argument("--top_k", type=int, default=5, help="Top-K 반환 개수")
    ap.add_argument("--manual_id", type=int, default=0, help="특정 manuals.id만 필터링(0이면 전체)")
    args = ap.parse_args()

    # 1) FAISS 검색
    rids_scores = search("chunks", args.query, k=args.top_k)

    # 2) DB에서 content/page 로드 → 지정된 출력 포맷으로 정리
    ctxs = load_contexts(
        rids_scores,
        manual_id=(args.manual_id or None),
    )

    # 3) JSON 형태로 출력 (다른 에이전트/프론트에서 그대로 파싱해서 쓰기 좋게)
    print(json.dumps(ctxs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
