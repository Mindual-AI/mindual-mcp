# scripts/ingest_one_with_figures.py
"""
PDF 1개를 페이지 이미지로 렌더 → Gemini Flash로 OCR → 텍스트/페이지/도해bbox 메타를 DB에 적재.
* 페이지 크롭(도해 이미지) 저장 없음. (figures.path에는 페이지 이미지 경로 저장)
* RAG 응답 시 해당 페이지 이미지를 그대로 보여줄 수 있도록 page_images/figures/chunks를 채움.
"""

from __future__ import annotations
import argparse, json, os, random, re, sqlite3, time, sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image
import google.generativeai as genai

# --- import path bootstrap ---
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
    """
    upsert 모듈을 여러 경로 후보에서 import.
    - db/upsert.py  → "db.upsert"
    - src/db/upsert.py → "src.db.upsert"
    - 루트/upsert.py → "upsert"
    """
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

    raise RuntimeError(
        "upsert 모듈을 찾을 수 없습니다. db/upsert.py 위치와 __init__.py 여부를 확인하세요."
    ) from last_err

_cfg = _import_config()
_up  = _import_upsert()
GEMINI_API_KEY  = getattr(_cfg, "GEMINI_API_KEY")
GEMINI_MODEL_ID = getattr(_cfg, "GEMINI_MODEL_ID", "gemini-2.0-flash")
DB_PATH         = getattr(_cfg, "DB_PATH", "./manuals.sqlite")

upsert_manual = getattr(_up, "upsert_manual")
insert_chunk  = getattr(_up, "insert_chunk")

DEFAULT_PER_PAGE_SLEEP = 1.0

# ---------- utils ----------
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
                print(f"⏳ {on_msg} 재시도 {attempt+1}/{retries} ... {sleep:.1f}s 대기 (사유: {msg[:80]}...)")
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

# ---------- figure detection (bbox only; no crop saved) ----------
def detect_figures(page: fitz.Page, min_area_pdf: float = 10_000.0) -> List[Tuple[float, float, float, float]]:
    """
    PyMuPDF 텍스트 dict에서 type=1 이미지 블록 bbox(PDF 좌표)를 수집.
    (스캔 PDF의 경우 페이지 전체 1개만 나올 수 있음. 그 외 벡터 도해는 별도 고도화 가능)
    """
    page_dict = page.get_text("dict")
    boxes = []
    for b in page_dict.get("blocks", []):
        if b.get("type") != 1:
            continue
        x0, y0, x1, y1 = b["bbox"]
        if (x1 - x0) * (y1 - y0) >= min_area_pdf:
            boxes.append((x0, y0, x1, y1))
    return boxes

def px_bbox_from_pdf_bbox(pdf_bbox: Tuple[float, float, float, float], page: fitz.Page, dpi: int):
    x0, y0, x1, y1 = pdf_bbox
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    r = fitz.Rect(x0, y0, x1, y1) * mat
    return (int(round(r.x0)), int(round(r.y0)), int(round(r.x1)), int(round(r.y1)))

def detect_nearby_caption(page: fitz.Page,
                          pdf_bbox: Tuple[float, float, float, float],
                          max_vertical_gap: float = 100.0) -> Optional[str]:
    x0, y0, x1, y1 = pdf_bbox
    page_dict = page.get_text("dict")
    best = ""
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        bx0, by0, bx1, by1 = block["bbox"]
        horizontally_overlaps = not (bx1 < x0 or bx0 > x1)
        is_below = by0 >= y1 and (by0 - y1) <= max_vertical_gap
        if horizontally_overlaps and is_below:
            lines = []
            for ln in block.get("lines", []):
                spans = [sp.get("text", "") for sp in ln.get("spans", [])]
                line = "".join(spans).strip()
                if line:
                    lines.append(line)
            cand = "\n".join(lines).strip()
            if len(cand) > len(best):
                best = cand
    return best or None

# ---------- main pipeline ----------
def ingest_one_with_figures(pdf_path: Path,
                            brand: str,
                            language: str,
                            title: str,
                            dpi: int = 300,
                            min_area: float = 10_000.0,
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
    print(f"✅ Upserted manual id={manual_id} models={models} created_at={created_at}")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    merged_parts: List[str] = []

    for i, page in enumerate(doc, start=1):
        # 1) 페이지 렌더 → jpg 저장
        page_jpg = processed_dir / f"page_{i}.jpg"
        pix = page.get_pixmap(dpi=dpi)
        pix.save(str(page_jpg))

        # page_images 테이블에는 ingest 이후 별도 뷰에서 쓰기 좋게 등록
        conn.execute(
            """
            INSERT INTO page_images(manual_id, page, path)
            VALUES(?,?,?)
            ON CONFLICT(manual_id, page) DO UPDATE SET path=excluded.path
            """,
            (manual_id, i, str(page_jpg)),
        )
        conn.commit()

        # 2) OCR (Gemini)
        image = Image.open(page_jpg)
        text = gemini_ocr(model, image)
        if text.strip():
            insert_chunk(manual_id=manual_id, section_id=None, page=i,
                         content=text.strip(), meta={"source": "ocr", "dpi": dpi})
            merged_parts.append(text.strip())

        # 3) 도해 bbox만 기록(크롭 저장 안 함) — figures.path는 페이지 이미지 경로로 저장
        fig_boxes = detect_figures(page, min_area_pdf=min_area) or []
        for fi, box_pdf in enumerate(fig_boxes):
            bbox_px = px_bbox_from_pdf_bbox(box_pdf, page, dpi)
            caption = detect_nearby_caption(page, box_pdf)
            conn.execute(
                """INSERT INTO figures(manual_id,page,bbox_pdf,bbox_px,path,thumb_path,caption,ocr,meta)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    manual_id,
                    i,
                    json.dumps(list(box_pdf), ensure_ascii=False),
                    json.dumps(list(bbox_px), ensure_ascii=False),
                    str(page_jpg),   # ← 크롭 대신 페이지 이미지 경로를 저장
                    None,            # thumb 없음
                    caption or None,
                    None,            # 추후 필요 시 그림 내 OCR
                    json.dumps({"detector": "pymupdf_image_block", "dpi": dpi}, ensure_ascii=False),
                ),
            )

        conn.commit()
        print(f"📄 Page {i}: OCR {len(text)} chars, {len(fig_boxes)} figure-bboxes")
        if per_page_sleep > 0:
            time.sleep(per_page_sleep)

    # 4) 머지 텍스트, FTS 동기화
    merged_path = processed_dir / "merged_manual.txt"
    merged_path.write_text("\n\n".join(merged_parts), encoding="utf-8")
    ensure_fts_sync(conn)
    conn.close()
    print(f"✅ Merged text -> {merged_path}\n🎉 Ingestion complete. DB: {DB_PATH}")

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(description="Ingest one manual PDF (no-crop; store page & figure bbox meta)")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--brand", default="")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--title", default="")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--min_area", type=float, default=10000.0)
    ap.add_argument("--sleep", type=float, default=DEFAULT_PER_PAGE_SLEEP)
    args = ap.parse_args()

    ingest_one_with_figures(Path(args.pdf),
                            args.brand, args.language, args.title,
                            dpi=args.dpi, min_area=args.min_area,
                            per_page_sleep=args.sleep)

if __name__ == "__main__":
    main()