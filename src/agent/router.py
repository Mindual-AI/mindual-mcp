# src/agent/router.py
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import (
    Literal,
    Dict,
    Any,
    Optional,
    Tuple,
    List,   # 추가
)

from PIL import Image
import google.generativeai as genai

from src.config import GEMINI_API_KEY, GEMINI_MODEL_ID, DB_PATH
from src.index.build_embeddings_and_index import search
from src.agent.query_rag import answer_query  # 텍스트 RAG용
from src.agent.image_to_text_agent import analyze_image
from src.agent.answer_synthesis import AnswerSynthesisAgent


Intent = Literal["manual", "chat"]  # 나중에 "schedule", "image_help" 등 추가 가능


def classify_intent(query: str) -> Intent:
    """
    아주 단순 rule-based 질의 분류.
    - 매뉴얼 / 제품 / 사용법 느낌이면 'manual'
    - 그 외는 일단 'chat'
    """
    q = query.strip()

    # 매뉴얼 관련 키워드들
    manual_keywords = [
        "사용법", "사용 방법", "어떻게 하나", "어떻게 하냐",
        "필터", "청소", "세척", "설정", "버튼", "리셋", "reset",
        "에러", "오류", "점검", "경고등",
        "공기청정기", "청소기", "전자레인지", "세탁기", "에어컨",
        "설명서", "매뉴얼"
    ]

    for kw in manual_keywords:
        if kw in q:
            return "manual"

    # 일단 기본은 chat으로
    return "chat"


def chat_with_gemini(query: str) -> str:
    """
    매뉴얼이 아닌 일반 질문에 대해 Gemini로 바로 답변.
    """
    if not GEMINI_API_KEY:
        return "⚠️ LLM API 키가 설정되어 있지 않아 일반 대화를 처리할 수 없습니다."

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL_ID)

    prompt = (
        "너는 전자기기 사용자 도우미야. 너무 장황하지 않게, 친절하게 답해줘.\n\n"
        f"사용자 질문: {query}"
    )

    try:
        resp = model.generate_content(prompt)
    except Exception as e:
        return f"⚠️ Gemini 호출 중 오류: {repr(e)}"

    text = getattr(resp, "text", None)
    if not text and hasattr(resp, "candidates"):
        try:
            text = resp.candidates[0].content.parts[0].text
        except Exception:
            text = None

    return text or "⚠️ LLM 응답을 가져오지 못했습니다."


def route_query(query: str, k: int = 5) -> Dict[str, Any]:
    """
    메인 라우터 에이전트.
    - intent 분류
    - 항상 RAG를 먼저 시도해서 매뉴얼 DB 기반 답변을 우선 사용
    - RAG에서 의미 있는 페이지를 찾지 못한 경우에만 일반 LLM으로 fallback
    - 항상 answer는 문자열로 반환하고, pages/error는 선택적으로 포함.
    """
    # 1) 간단 intent 분류 (일단 로그용/참고용으로 유지)
    intent: Intent = classify_intent(query)

    # 2) 먼저 RAG 시도 (매뉴얼 DB 기반)
    rag_result = answer_query(query, k=k)

    answer_text: str
    pages: List[Dict[str, Any]] = []
    error: Optional[str] = None

    if isinstance(rag_result, dict):
        answer_text = str(rag_result.get("answer", ""))
        pages = rag_result.get("pages", []) or []

        # --- 페이지 이미지 base64 인코딩 추가 ---
        import base64
        enriched_pages = []
        for p in pages:
            page_data = dict(p)
            img_path = page_data.get("image_path") or page_data.get("image_url")
            if img_path:
                try:
                    from pathlib import Path
                    fs_path = Path(str(img_path))
                    if fs_path.is_file():
                        with fs_path.open("rb") as f:
                            raw = f.read()
                        suffix = fs_path.suffix.lower()
                        if suffix in [".jpg", ".jpeg"]:
                            mime = "image/jpeg"
                        elif suffix == ".png":
                            mime = "image/png"
                        else:
                            mime = "image/*"
                        b64 = base64.b64encode(raw).decode("ascii")
                        page_data["image_base64"] = f"data:{mime};base64,{b64}"
                except Exception:
                    pass
            enriched_pages.append(page_data)
        pages = enriched_pages

        error = rag_result.get("error")
    else:
        # 기존 버전처럼 문자열만 리턴하는 경우도 안전하게 처리
        answer_text = str(rag_result)

    # --- 디버그용 로그: 실제로 매뉴얼 DB가 사용되는지 확인하는 용도 ---
    try:
        print("[RAG][route_query] query:", query)
        print(f"[RAG][route_query] pages_count={len(pages)} error={error}")
        for p in pages[:3]:
            mid = p.get("manual_id")
            pg = p.get("page")
            snippet = (p.get("text") or "")[:80] if isinstance(p, dict) else ""
            print(f"[RAG][route_query] hit manual_id={mid} page={pg} text_snippet={snippet}")
    except Exception:
        # 로깅 실패는 무시
        pass

    # 3) RAG 결과가 의미 있는 경우 → 무조건 매뉴얼 기반으로 처리
    if pages:
        proactive = "필터 청소/교체 주기를 캘린더에 리마인더로 등록해 드릴까요?"
        return {
            "intent": "manual",
            "answer": answer_text,
            "proactive": proactive,
            "source": "rag",   # ✅ DB/RAG 기반 답변
            "pages": pages,
            "error": error,
        }

    # 4) RAG에서 아무 페이지도 못 찾은 경우
    #    - 원래 intent가 manual 이었으면, 그래도 RAG 답변(또는 '정보 없음' 메시지)을 그대로 전달
    #    - intent가 chat 이면, 일반 LLM으로 fallback
    if intent == "chat":
        llm_answer = chat_with_gemini(query)
        return {
            "intent": "chat",
            "answer": llm_answer,
            "proactive": None,
            "source": "llm_only",  # ✅ DB를 사용하지 않은 일반 대화
            "pages": [],
            "error": None,
        }

    # intent == "manual" 이지만 pages가 비어 있는 경우:
    # 매뉴얼 DB에 정보가 없다고 판단하고, RAG에서 온 answer_text를 그대로 노출
    proactive = None
    return {
        "intent": "manual",
        "answer": answer_text or "매뉴얼 DB에서 관련 정보를 찾지 못했습니다.",
        "proactive": proactive,
        "source": "rag",
        "pages": pages,
        "error": error,
    }


ImageIntent = Literal["image_manual", "image_other"]


def classify_image_intent(query: Optional[str]) -> ImageIntent:
    """
    이미지 + 텍스트 질문일 때 intent 분류 (아주 단순 버전).
    나중에 필요하면 세분화하면 됨.
    """
    if not query:
        return "image_other"

    q = query.strip()
    manual_keywords = [
        "사용법", "사용 방법", "어떻게 하나", "어떻게 하냐",
        "필터", "청소", "세척", "설정", "버튼", "리셋", "reset",
        "에러", "오류", "점검", "경고등",
        "공기청정기", "청소기", "전자레인지", "세탁기", "에어컨",
        "설명서", "매뉴얼"
    ]
    if any(kw in q for kw in manual_keywords):
        return "image_manual"
    return "image_other"


synthesis_agent = AnswerSynthesisAgent()


def route_image_query(query: str, image_path: str, k: int = 5) -> Dict[str, Any]:
    """
    (질문 + 이미지)가 들어왔을 때:
    1) 이미지 캡션 생성
    2) 캡션 + 질문을 이용해 RAG 검색
    3) 가장 유사한 매뉴얼 페이지/그림을 찾고
    4) 멀티모달 답변을 생성해서 반환
    """

    # 1. 이미지 열기
    user_image = Image.open(image_path)

    # 2. 이미지 캡션(텍스트 설명) 생성
    try:
        # analyze_image 는 이미지를 받아 설명 문자열을 반환하는 함수라고 가정
        image_desc = analyze_image(user_image)
    except Exception:
        image_desc = ""
        # 실패해도 fallback 으로 텍스트 질문만으로 RAG 진행

    # 3. 텍스트 쿼리 구성
    base_query = query.strip()
    if base_query and image_desc:
        combined_query = f"{base_query}\n이미지 설명: {image_desc}"
    elif image_desc:
        combined_query = image_desc
    else:
        combined_query = base_query or "제품 사진과 관련된 설명을 찾아줘"

    # 4. RAG 검색: chunks에서 관련 텍스트 + 페이지 + 이미지 경로 찾기
    try:
        results: List[Tuple[int, float]] = search("chunks", combined_query, k=k)
    except Exception as e:
        return {
            "intent": "image_query",
            "answer": f"[검색 단계 에러] {e}",
            "source": "image+manual",
            "pages": [],
            "uploaded_image_path": image_path,
            "error": str(e),
        }

    conn = sqlite3.connect(DB_PATH)
    retrieved_sentences: List[str] = []
    pages: List[Dict[str, Any]] = []

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
            retrieved_sentences.append(content)

            image_path_value: Optional[str] = None
            image_url: Optional[str] = None
            if page_img:
                stored = Path(page_img)
                # DB에는 'data/processed/...' 같은 프로젝트 루트 기준 상대 경로가 들어 있다고 가정
                if stored.is_absolute():
                    fs_path = stored
                else:
                    # 이미 프로젝트 루트 기준 상대 경로이므로 그대로 사용
                    fs_path = stored
                image_path_value = str(fs_path)
                # 프론트에서 사용할 URL
                # FastAPI에서 data/processed를 /manual_images 로 마운트한다고 가정
                try:
                    rel = fs_path.relative_to("data/processed")
                    image_url = f"/manual_images/{rel.as_posix()}"
                except ValueError:
                    # 예상 경로 형식이 아니면, 일반 static 프리픽스를 사용 (환경에 맞게 조정 가능)
                    image_url = f"/static/{fs_path.as_posix()}"

            pages.append(
                {
                    "manual_id": manual_id,
                    "page": page,
                    "image_path": image_path_value,
                    "image_url": image_url,
                    "text": content,  # ✅ 해당 페이지에서 가져온 텍스트 (디버깅/출처 표시용)
                }
            )
    finally:
        conn.close()

    # 페이지 중에서 첫 번째를 대표로 사용 (원하면 score 기반으로 더 똑똑하게 고를 수 있음)
    main_page = pages[0] if pages else None
    manual_page_image = None
    if main_page and main_page.get("image_path"):
        page_img_path = Path(main_page["image_path"])
        if page_img_path.exists():
            manual_page_image = Image.open(page_img_path)

    # 5. 멀티모달 답변 합성
    try:
        synth_result = synthesis_agent.synthesize(
            query=base_query or combined_query,
            retrieved_sentences=retrieved_sentences,
            user_image=user_image,          # 사용자가 찍은 사진
            manual_page_image=manual_page_image,  # 매칭된 매뉴얼 페이지 이미지
            page=main_page["page"] if main_page else None,
        )
        answer_text = synth_result.get("answer", "")
    except Exception as e:
        # synthesis 실패하면 텍스트 RAG만 써서 fallback
        fallback = answer_query(combined_query, k=k)
        answer_text = fallback.get("answer", f"[합성 에러] {e}")

    # --- 페이지 이미지 base64 추가 ---
    import base64
    enriched_pages2 = []
    for p in pages:
        page_data = dict(p)
        img_path = page_data.get("image_path") or page_data.get("image_url")
        if img_path:
            try:
                from pathlib import Path
                fs_path = Path(str(img_path))
                if fs_path.is_file():
                    with fs_path.open("rb") as f:
                        raw = f.read()
                    suffix = fs_path.suffix.lower()
                    if suffix in [".jpg", ".jpeg"]:
                        mime = "image/jpeg"
                    elif suffix == ".png":
                        mime = "image/png"
                    else:
                        mime = "image/*"
                    b64 = base64.b64encode(raw).decode("ascii")
                    page_data["image_base64"] = f"data:{mime};base64,{b64}"
            except Exception:
                pass
        enriched_pages2.append(page_data)
    pages = enriched_pages2

    return {
        "intent": "image_query",
        "answer": answer_text,
        "source": "image+manual",
        "pages": pages,  # 프론트에서 관련 페이지 썸네일/링크로 사용할 수 있음
        "uploaded_image_path": image_path,
        "retrieved_sentences": retrieved_sentences,  # ✅ 어떤 텍스트를 근거로 했는지 확인용
        "error": None,
    }