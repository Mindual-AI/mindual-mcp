# scripts/query_rag.py
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]  # scripts의 부모 = 프로젝트 루트
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.index.build_embeddings_and_index import search
from src.config import GEMINI_API_KEY, GEMINI_MODEL_ID, DB_PATH
import google.generativeai as genai
import sqlite3


def answer_query(query: str, k: int = 5) -> Dict[str, Any]:
    """
    RAG 기반으로 답변을 생성하고,
    참고할 매뉴얼 페이지 정보(페이지 번호 + 이미지 경로)를 함께 반환한다.

    반환 형식 예:
    {
        "answer": "...",
        "intent": "rag",
        "source": "rag",
        "pages": [
            {
                "manual_id": 1,
                "page": 5,
                "image_path": "page_images/manual1_p5.png",
                "score": 0.1234
            },
            ...
        ]
    }
    """
    # 1. FAISS 검색
    try:
        results: List[Tuple[int, float]] = search("chunks", query, k=k)
    except Exception as e:
        return {
            "answer": f"[검색 단계 에러] {repr(e)}",
            "intent": "rag",
            "source": "rag_search_error",
            "pages": [],
        }

    # 2. DB에서 텍스트 + 페이지 이미지 경로 조회
    conn = sqlite3.connect(DB_PATH)
    contexts: list[str] = []
    pages: list[Dict[str, Any]] = []

    try:
        for rid, score in results:
            row = conn.execute(
                """
                SELECT c.content, c.manual_id, c.page, p.path
                FROM chunks c
                LEFT JOIN page_images p
                  ON c.manual_id = p.manual_id AND c.page = p.page
                WHERE c.id = ?
                """,
                (rid,),
            ).fetchone()

            if not row:
                continue

            content, manual_id, page, page_img = row

            # LLM 컨텍스트용 텍스트
            contexts.append(f"[p.{page}] {content}")

            # 프론트에 넘길 페이지/이미지 정보
            # 이 (manual_id, page)에 해당하는 이미지가 존재할 때만 image_path / image_url을 설정한다.
            raw_path: str | None = None
            image_url: str | None = None

            if page_img:
                raw_path = page_img
                fs_path = Path(str(raw_path))

                # DB 경로가 'data/...' 로 시작하면 그대로 '/data/...' 로 매핑한다.
                # 예: raw_path='data/processed/삼성 냉장고/page_16.jpg'
                #     → image_url='/data/processed/삼성 냉장고/page_16.jpg'
                raw_path_str = str(raw_path)
                if raw_path_str.startswith("data/"):
                    image_url = f"/{raw_path_str}"
                else:
                    # 그 외 경로는 /static 아래에 그대로 노출한다.
                    image_url = f"/static/{fs_path.as_posix()}"

            page_entry: Dict[str, Any] = {
                "manual_id": manual_id,
                "page": page,
                "score": float(score),
                "text": content,  # ✅ 해당 페이지의 원문 텍스트 (디버깅/출처 표시용)
            }

            # 실제 이미지가 있는 경우에만 관련 필드를 추가
            if raw_path:
                page_entry["image_path"] = raw_path
            if image_url:
                page_entry["image_url"] = image_url  # ✅ 에이전트 응답에 바로 쓸 수 있는 URL

            pages.append(page_entry)
    finally:
        conn.close()

    if not contexts:
        return {
            "answer": "관련 매뉴얼 내용을 찾지 못했어요.",
            "intent": "rag",
            "source": "rag_nohit",
            "pages": [],
        }

    # 3. Gemini로 RAG 답변 생성
    if not GEMINI_API_KEY:
        return {
            "answer": "GEMINI_API_KEY가 설정되어 있지 않아서 LLM 호출을 할 수 없습니다.",
            "intent": "rag",
            "source": "rag_no_llm_key",
            "pages": pages,
        }

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL_ID)

    prompt = (
        "다음 전자제품 사용설명서 내용을 참고해서, 질문에 한국어로 자세히 답변해줘.\n"
        "단, 매뉴얼에 없는 내용은 추측하지 말고 '매뉴얼에 정보가 없다'고 말해줘.\n\n"
        f"질문: {query}\n\n"
        "관련 매뉴얼 내용:\n" + "\n\n".join(contexts)
    )

    try:
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None)
        if not text and hasattr(resp, "candidates") and resp.candidates:
            # 후보가 있을 경우 첫 번째 후보에서 텍스트 추출
            parts = getattr(resp.candidates[0].content, "parts", None)
            if parts and len(parts) > 0 and hasattr(parts[0], "text"):
                text = parts[0].text
    except Exception as e:
        return {
            "answer": f"[LLM 호출 에러] {repr(e)}",
            "intent": "rag",
            "source": "rag_llm_error",
            "pages": pages,
        }

    return {
        "answer": text or "⚠️ Gemini 응답이 없습니다.",
        "intent": "rag",
        "source": "rag",
        "pages": pages,
    }