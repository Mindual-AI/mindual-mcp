# scripts/build_embeddings_and_index.py
"""
SQLite DB(chunks, figures)을 읽어 텍스트 임베딩 생성 → FAISS 인덱스 구축.
- 임베딩: Google Gemini Embeddings (text-embedding-004)
- 인덱스: cosine(내적) 기반 IndexFlatIP (벡터 L2 정규화)
- 대상: chunks.content + (옵션) figures.caption / (옵션) figures.ocr
- 산출물:
  ./indexes/chunks.faiss,   ./indexes/chunks.map.json
  ./indexes/figures.faiss,  ./indexes/figures.map.json

사전 조건:
- pip install faiss-cpu google-generativeai
- src/config.py에 GEMINI_API_KEY, DB_PATH 정의
- DB 스키마: chunks(id, manual_id, page, content), figures(id, manual_id, page, caption, ocr)
"""

from __future__ import annotations
import argparse
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple, Optional

import faiss  # type: ignore
import numpy as np
import google.generativeai as genai

# --- import path bootstrap (works from any CWD) ---
import sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]  # .../mindual
SRC  = ROOT / "src"
DBP  = ROOT / "db"
for p in (str(ROOT), str(SRC), str(DBP)):
    if p not in sys.path:
        sys.path.insert(0, p)

def _import_config():
    for name in ("src.config", "config"):
        try:
            mod = __import__(name, fromlist=["*"])
            return mod
        except ModuleNotFoundError:
            continue
    raise

_cfg = _import_config()

# --- Project config ---
GEMINI_API_KEY  = getattr(_cfg, "GEMINI_API_KEY")
DB_PATH         = getattr(_cfg, "DB_PATH", "./manuals.sqlite")
# 환경에서 바꾸고 싶으면 .env에 EMBED_MODEL 지정 가능 (없으면 기본값 사용)
EMBED_MODEL     = getattr(_cfg, "EMBED_MODEL", "text-embedding-004")

BATCH = 64  # DB 로우 배치 크기(임베딩 호출은 내부에서 단건씩 백오프)
INDEX_DIR = Path("../agent/indexes")
INDEX_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class Row:
    rid: int
    text: str

# ---------- utils ----------

def l2_normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / norms

def _setup_genai():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set. Put it in .env")
    genai.configure(api_key=GEMINI_API_KEY)

def _embed_one(text: str,
               retries: int = 6,
               base: float = 1.5,
               jitter: float = 0.3) -> np.ndarray:
    """
    text-embedding-004 단건 호출.
    SDK 응답 포맷 변화(embedding dict/list, embeddings 등)를 모두 커버.
    """
    if not text or not text.strip():
        return np.zeros((1, 768), dtype="float32")

    last_err = None

    def _extract_values(out) -> list:
        # dict 형태 응답
        if isinstance(out, dict):
            if "embedding" in out:
                emb = out["embedding"]
                # {"embedding":{"values":[...]}}
                if isinstance(emb, dict) and "values" in emb:
                    return emb["values"]
                # {"embedding":[...float...]}
                if isinstance(emb, list):
                    return emb
            if "embeddings" in out:
                e0 = out["embeddings"][0]
                if isinstance(e0, dict) and "values" in e0:
                    return e0["values"]
        # 객체 형태 응답
        emb = getattr(out, "embedding", None)
        if emb is not None:
            vals = getattr(emb, "values", None)
            if vals is not None:
                return vals
            if isinstance(emb, list):
                return emb
        if hasattr(out, "embeddings"):
            e0 = out.embeddings[0]
            vals = getattr(e0, "values", None)
            if vals is not None:
                return vals
        raise RuntimeError(f"Unexpected embed_content output: {type(out)}")

    for attempt in range(retries):
        try:
            out = genai.embed_content(model=EMBED_MODEL, content=text)
            vals = _extract_values(out)
            vec = np.array(vals, dtype="float32").reshape(1, -1)
            return vec
        except Exception as e:
            msg = str(e)
            last_err = e
            if "Resource exhausted" in msg or "429" in msg or "exceeded" in msg:
                sleep = (base ** attempt) + np.random.uniform(0, jitter)
                print(f"⏳ embed retry {attempt+1}/{retries} ... {sleep:.1f}s ({msg[:80]}...)")
                time.sleep(sleep)
                continue
            raise

    print(f"⚠️ embed failed after retries; using zero vector. err={last_err}")
    return np.zeros((1, 768), dtype="float32")

def gemini_embed_texts(texts: List[str]) -> np.ndarray:
    """
    안전모드: 단건 호출을 반복하여 배치 처리.
    """
    _setup_genai()
    vecs: List[np.ndarray] = []
    for t in texts:
        vecs.append(_embed_one(t))
    return np.vstack(vecs)

def batched(it: List[Row], size: int) -> Iterable[List[Row]]:
    for i in range(0, len(it), size):
        yield it[i : i + size]

# ---------- DB IO ----------

def load_chunks(conn: sqlite3.Connection, manual_id: Optional[int] = None) -> List[Row]:
    cur = conn.cursor()
    if manual_id:
        cur.execute(
            "SELECT id, content FROM chunks "
            "WHERE content IS NOT NULL AND TRIM(content) != '' AND manual_id = ?",
            (manual_id,),
        )
    else:
        cur.execute(
            "SELECT id, content FROM chunks WHERE content IS NOT NULL AND TRIM(content) != ''"
        )
    return [Row(rid=i, text=c) for (i, c) in cur.fetchall()]

def load_figures(conn: sqlite3.Connection,
                 manual_id: Optional[int] = None,
                 use_ocr: bool = False) -> List[Row]:
    cur = conn.cursor()
    sel = "COALESCE(NULLIF(TRIM(ocr),''), NULLIF(TRIM(caption),''))" if use_ocr else "NULLIF(TRIM(caption),'')"
    if manual_id:
        cur.execute(f"SELECT id, {sel} FROM figures WHERE manual_id = ?", (manual_id,))
    else:
        cur.execute(f"SELECT id, {sel} FROM figures")
    rows = []
    for rid, text in cur.fetchall():
        if text:
            rows.append(Row(rid=rid, text=text))
    return rows

# ---------- FAISS save/load ----------

def save_index(name: str, index: faiss.Index, id_map: List[int]):
    path = INDEX_DIR / f"{name}.faiss"
    faiss.write_index(index, str(path))
    (INDEX_DIR / f"{name}.map.json").write_text(
        json.dumps({"ids": id_map}, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"✅ saved index: {path} ({len(id_map)} vectors)")

# ---------- Build ----------

def build_index(rows: List[Row], name: str):
    if not rows:
        print(f"⚠️ no rows for {name}")
        return
    vecs: List[np.ndarray] = []
    id_map: List[int] = []
    for batch in batched(rows, BATCH):
        texts = [r.text for r in batch]
        emb = gemini_embed_texts(texts)
        vecs.append(emb)
        id_map.extend([r.rid for r in batch])
    X = np.vstack(vecs).astype("float32")
    X = l2_normalize(X)
    index = faiss.IndexFlatIP(X.shape[1])  # cosine = inner product on L2-normalized vectors
    index.add(X)
    save_index(name, index, id_map)

# ---------- Query Test ----------

def search(name: str, query: str, k: int = 5) -> List[Tuple[int, float]]:
    _setup_genai()
    path = INDEX_DIR / f"{name}.faiss"
    idfile = INDEX_DIR / f"{name}.map.json"
    index = faiss.read_index(str(path))
    id_map = json.loads(idfile.read_text(encoding="utf-8"))["ids"]
    qv = gemini_embed_texts([query]).astype("float32")
    qv = l2_normalize(qv)
    sims, idxs = index.search(qv, k)
    return [(id_map[i], float(s)) for i, s in zip(idxs[0], sims[0]) if i != -1]

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual_id", type=int, default=0, help="특정 매뉴얼만 인덱싱(0은 전체)")
    ap.add_argument("--include_figures", action="store_true", help="figures.caption/ocr도 인덱싱")
    ap.add_argument("--use_figure_ocr", action="store_true", help="caption 대신 ocr 우선 사용")
    ap.add_argument("--test_query", default="", help="간단 검색 테스트 쿼리")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        # chunks
        chunk_rows = load_chunks(conn, args.manual_id or None)
        print(f"🧱 chunks rows: {len(chunk_rows)}")
        build_index(chunk_rows, "chunks")

        # figures (옵션)
        if args.include_figures:
            fig_rows = load_figures(conn, args.manual_id or None, use_ocr=args.use_figure_ocr)
            print(f"🖼  figures rows: {len(fig_rows)} (use_ocr={args.use_figure_ocr})")
            build_index(fig_rows, "figures")
    finally:
        conn.close()

    if args.test_query:
        print("\n== CHUNKS ==")
        for rid, score in search("chunks", args.test_query, k=5):
            print(rid, f"{score:.4f}")
        if args.include_figures:
            print("\n== FIGURES ==")
            for rid, score in search("figures", args.test_query, k=5):
                print(rid, f"{score:.4f}")

if __name__ == "__main__":
    main()
