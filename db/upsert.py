# db/upsert.py
# 기본 upsert/insert 함수 모음
# db/upsert.py
import json
import sqlite3
from typing import Sequence, Mapping, Any, Optional
from src.config import DB_PATH

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def upsert_manual(
    file_name: str,
    model_list: Sequence[str],
    language: str,
    title: str,
    created_at: str
) -> int:
    """
    manuals(file_name) UNIQUE 기준으로 upsert 후 id 반환
    schema.sql에 manuals 테이블이 있어야 함.
    """
    conn = get_conn()
    try:
        conn.execute("""
        INSERT INTO manuals(file_name, model_list, language, title, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(file_name) DO UPDATE SET
          model_list=excluded.model_list,
          language=excluded.language,
          title=excluded.title,
          created_at=excluded.created_at
        """, (file_name, json.dumps(list(model_list), ensure_ascii=False), language, title, created_at))
        conn.commit()
        row = conn.execute("SELECT id FROM manuals WHERE file_name=?", (file_name,)).fetchone()
        return int(row["id"])
    finally:
        conn.close()

def insert_chunk(
    manual_id: int,
    section_id: Optional[int],
    page: Optional[int],
    content: str,
    meta: Mapping[str, Any]
) -> int:
    """
    chunks에 한 건 저장하고 FTS(chunks_fts) 동기화
    schema.sql에 chunks, chunks_fts가 있어야 함.
    """
    conn = get_conn()
    try:
        cur = conn.execute("""
        INSERT INTO chunks(manual_id, section_id, page, content, meta)
        VALUES (?, ?, ?, ?, ?)
        """, (manual_id, section_id, page, content, json.dumps(meta, ensure_ascii=False)))
        chunk_id = cur.lastrowid

        # FTS5 가상테이블에 content 동기화
        conn.execute("INSERT INTO chunks_fts(rowid, content) VALUES(?, ?)", (chunk_id, content))
        conn.commit()
        return chunk_id
    finally:
        conn.close()

