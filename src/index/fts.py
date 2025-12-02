# src/index/embed.py
# 임베딩/FAISS
import sqlite3
from typing import List, Dict
from src.config import DB_PATH, RAG_MAX_DOCS

def fts_search(query: str, limit: int = RAG_MAX_DOCS) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, manual_id, section_id, page, content FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT ?",
            (query, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
