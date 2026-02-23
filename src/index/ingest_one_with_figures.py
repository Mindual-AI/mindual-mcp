# scripts/ingest_one_with_figures.py
"""
PDF 1개를 페이지 이미지로 렌더 → Gemini Flash로 OCR → 텍스트/페이지를 DB에 적재.
(그림 bbox/figures 테이블 관련 기능은 제거됨)
"""

from __future__ import annotations
import argparse, json, os, random, re, sqlite3, time, sys
from pathlib import Path
from typing import List

import fitz  # PyMuPDF
from PIL import Image
import google.generativeai as genai

ROOT = Path(__file__).resolve().parents[2]
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


def _import_upsert():
    candidates = ("db.upsert", "src.db.upsert", "upsert")
    last_err = None

    for name in candidates:
        try:
            mod = __import__(name, fromlist=["*"])
            print(f"[debug] loaded upsert module: {name}")
            return mod
        except ModuleNotFoundError as e:
            last_err = e
            continue

    raise RuntimeError("upsert 모듈을 찾을 수 없습니다.") from last_err


_cfg = _import_config()
_up  = _import_upsert()

GEMINI_API_KEY  = getattr(_cfg, "GEMINI_API_KEY")
GEMINI_MODEL_ID = getattr(_cfg, "GEMINI_MODEL_ID", "gemini-2.0-flash")
DB_PATH         = getattr(_cfg, "DB_PATH", "./manuals.sqlite")

upsert_manual = getattr(_up, "upsert_manual")
insert_chunk  = getattr(_up, "insert_chunk")

DEFAULT_PER_PAGE_SLEEP = 1.0


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def setup_gemini():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set. Put it in .env")
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(GEMINI_MODEL_ID)


def retry_with_backoff(fn, *, retries=6, base=1.5, jitter=0.3, on_msg=""):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if "Resource exhausted" in msg or "429" in msg or "exceeded" in msg:
                sleep = (base ** attempt) + random.uniform(0, jitter)
                print(f"{on_msg} 재시도 {attempt+1}/{retries} ... {sleep:.1f}s 대기 (사유: {msg[:80]}...)")
                time.sleep(sleep); continue
            raise
    raise RuntimeError(f"재시도 초과: {on_msg}")


def gemini_ocr(model, image: Image.Image) -> str:
    prompt = (
        "이 이미지는 전자기기 사용설명서의 한 페이지입니다. "
        "보이는 모든 텍스트를 가능한 정확도로 추출해 주세요. "
        "줄바꿈과 리스트, 표 구조(가능하면 마크다운 테이블)를 보존해 주세요."
    )
    def _call():
        return model.generate_content([prompt, image])
    resp = retry_with_backoff(_call, on_msg="Gemini OCR")
    return resp.text or ""


def infer_meta_from_filename(stem: str):
    tokens = re.split(r"[^A-Za-z0-9\-]+", stem)
    models = [t for t in tokens if re.search(r"[A-Za-z]{2,}\d{2,}", t)]
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", stem)
    created_at = m.group(1) if m else ""
    return list(dict.fromkeys(models)), created_at


def ensure_fts_sync(conn: sqlite3.Connection):
    conn.execute("""
        INSERT INTO chunks_fts(rowid, content)
        SELECT id, content FROM chunks
        WHERE id NOT IN (SELECT rowid FROM chunks_fts);
    """)
    conn.commit()


def ingest_one_with_figures(pdf_path: Path,
                            brand: str,
                            language: str,
                            title: str,
                            dpi: int = 300,
                            per_page_sleep: float = DEFAULT_PER_PAGE_SLEEP):
    stem = pdf_path.stem
    processed_dir = Path("data/processed") / stem
    ensure_dir(processed_dir)

    model = setup_gemini()
    doc = fitz.open(str(pdf_path))

    models, created_at = infer_meta_from_filename(stem)
    manual_id = upsert_manual(
        file_name=pdf_path.name,
        model_list=models or [],
        language=language,
        title=title or stem,
        created_at=created_at or ""
    )
    print(f"Upserted manual id={manual_id}")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    merged_parts: List[str] = []

    for i, page in enumerate(doc, start=1):
        page_jpg = processed_dir / f"page_{i}.jpg"
        pix = page.get_pixmap(dpi=dpi)
        pix.save(str(page_jpg))

        conn.execute("""
            INSERT INTO page_images(manual_id, page, path)
            VALUES(?,?,?)
            ON CONFLICT(manual_id, page) DO UPDATE SET path=excluded.path
        """, (manual_id, i, str(page_jpg)))
        conn.commit()

        image = Image.open(page_jpg)
        text = gemini_ocr(model, image)

        if text.strip():
            insert_chunk(manual_id, None, i, text.strip(), meta={"source": "ocr", "dpi": dpi})
            merged_parts.append(text.strip())

        conn.commit()
        print(f"Page {i}: OCR {len(text)} chars")
        if per_page_sleep > 0:
            time.sleep(per_page_sleep)

    merged_path = processed_dir / "merged_manual.txt"
    merged_path.write_text("\n\n".join(merged_parts), encoding="utf-8")
    ensure_fts_sync(conn)
    conn.close()
    print(f"Ingestion complete. DB: {DB_PATH}")


def main():
    ap = argparse.ArgumentParser(description="Ingest one manual PDF (no figures)")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--brand", default="")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--title", default="")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--sleep", type=float, default=DEFAULT_PER_PAGE_SLEEP)
    args = ap.parse_args()

    ingest_one_with_figures(
        Path(args.pdf),
        args.brand, args.language, args.title,
        dpi=args.dpi,
        per_page_sleep=args.sleep
    )


if __name__ == "__main__":
    main()
