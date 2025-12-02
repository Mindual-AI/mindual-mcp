# src/api/routes.py
from __future__ import annotations

from typing import List, Optional
from datetime import datetime
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import google.generativeai as genai

from src.config import DB_PATH, GEMINI_API_KEY, GEMINI_MODEL_ID
from src.index.build_embeddings_and_index import search
from src.calendar.google_calendar_client import list_upcoming_events
from src.parse.rules import extract_reminder
from src.integrations.google_calendar import create_event

from PIL import Image
from src.agent.answer_synthesis import AnswerSynthesisAgent
from src.agent.visual_detector import VisualContentDetector

router = APIRouter()


# ---------- 유틸: 한국어 일정 문장 포맷 ----------

def _format_korean_datetime(dt: datetime, title: str) -> str:
    weekday_names = ["월", "화", "수", "목", "금", "토", "일"]
    w = weekday_names[dt.weekday()]
    day = dt.day

    if dt.minute == 0:
        time_str = f"{dt.hour}시"
    else:
        time_str = f"{dt.hour}시 {dt.minute}분"

    # 예: 일요일(30일) 오전 10시에 "에어컨 청소" 일정이 등록되었습니다.
    return f"{w}요일({day}일) {time_str}에 \"{title}\" 일정이 등록되었습니다."

# ---------- Pydantic 모델 ----------
class RagRequest(BaseModel):
    query: str
    k: int = 5
    intent: Optional[str] = None

class RagContext(BaseModel):
    text: str
    page: Optional[int] = None
    manual_id: Optional[int] = None
    page_image: Optional[str] = None
    score: float


class RagResponse(BaseModel):
    answer: str
    contexts: List[RagContext]
    intent: Optional[str] = "rag"

class CalendarEvent(BaseModel):
    id: str
    title: str
    date: str  # "YYYY-MM-DD"
    time: str  # "HH:MM"
    location: str | None = None


class CalendarEventsResponse(BaseModel):
    events: List[CalendarEvent]


# ---------- Gemini 세팅 (한 번만) ----------

genai.configure(api_key=GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel(GEMINI_MODEL_ID)


def _call_gemini(prompt: str) -> str:
    """Gemini 호출 헬퍼: resp.text 없을 때 candidates 에서 꺼내오기."""
    resp = _gemini_model.generate_content(prompt)
    text = getattr(resp, "text", None)

    if not text and hasattr(resp, "candidates") and resp.candidates:
        parts = resp.candidates[0].content.parts
        if parts and getattr(parts[0], "text", None):
            text = parts[0].text

    return text or "응답 생성에 실패했습니다."

def detect_intent(text: str) -> str:
    """
    사용자의 한국어 문장을 보고
    - 'reminder' : 일정/예약/알림 등록
    - 'rag'      : 매뉴얼 질문
    으로 대충 나눠주는 간단한 규칙 기반 인텐트 감지기
    """
    text = text.strip()

    reminder_keywords = [
        "예약해줘", "예약 해줘",
        "예약해 줘", "예약 해 줘",
        "일정 추가", "일정 잡아줘", "일정 잡아 줘",
        "일정 등록", "일정 넣어줘",
        "알림 설정", "알림 맞춰줘",
        "리마인드", "리마인더",
        "캘린더에", "캘린더 등록",
    ]

    if any(kw in text for kw in reminder_keywords):
        return "reminder"

    # 기본값: RAG 질문
    return "rag"

# 브라우저가 쓸 수 있는 이미지 만들기
def _to_page_image_url(path: str | None) -> str | None:
    if not path:
        return None

    # 윈도우 백슬래시 → 슬래시
    norm = path.replace("\\", "/")

    # 이미 http URL 이면 그대로
    if norm.startswith("http://") or norm.startswith("https://"):
        return norm

    # data/processed/ 이후만 잘라서 사용
    prefix = "data/processed/"
    if norm.startswith(prefix):
        rel = norm[len(prefix):]
    else:
        rel = norm  # 안전하게

    # 백엔드 주소에 맞게
    return f"http://127.0.0.1:8100/manual-pages/{rel}"

answer_agent = AnswerSynthesisAgent()
visual_detector = VisualContentDetector()

# ---------- /rag/query 엔드포인트 ----------

@router.post("/rag/query", response_model=RagResponse)
def rag_query(body: RagRequest) -> RagResponse:
    print(">>> /rag/query called!", body.dict())

    # 0) intent 결정: body.intent가 있으면 우선, 없으면 서버에서 감지
    intent = body.intent or detect_intent(body.query)
    print("[INTENT]", intent, "| query:", body.query)

    # ---------- 리마인더 의도 처리 ----------
    if intent == "reminder":
        reminder = extract_reminder(body.query)
        print("[REMINDER] parsed:", repr(reminder))

        if not reminder:
            raise HTTPException(
                status_code=400,
                detail=(
                    "일정을 추가하는 문장으로 보이지만 날짜/시간을 이해하지 못했습니다. "
                    "예: '이번 주 일요일 오전 10시에 청소 일정 추가해줘'처럼 말해 주세요."
                ),
            )

        title = reminder.get("title") or "리마인더"
        start_dt = reminder.get("start")
        end_dt = reminder.get("end") or start_dt

        if not isinstance(start_dt, datetime):
            raise HTTPException(
                status_code=400,
                detail="날짜/시간 파싱에 실패했습니다.",
            )

        try:
            event = create_event(title, start_dt, end_dt)
            print("[REMINDER] calendar event created:", event.get("id"))
        except Exception as e:
            print("[REMINDER] calendar error:", repr(e))
            raise HTTPException(status_code=500, detail=f"캘린더 연동 오류: {e}")

        answer_text = _format_korean_datetime(start_dt, title)
        print("[REMINDER] answer:", answer_text)
        return RagResponse(answer=answer_text, contexts=[], intent="reminder")

    # rag
    print("[RAG] start:", body.query)

    # 1) FAISS 검색
    results = search("chunks", body.query, k=body.k)
    print("[RAG] search done. hits:", len(results))

    # 2) DB에서 컨텍스트 로드
    conn = sqlite3.connect(DB_PATH)
    contexts: List[RagContext] = []

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
            contexts.append(
                RagContext(
                    text=content,
                    page=page,
                    manual_id=manual_id,
                    page_image=_to_page_image_url(page_img),
                    score=score,
                )
            )
    finally:
        conn.close()

    print("[RAG] context loaded:", len(contexts))

    if not contexts:
        # 관련 문서가 없으면 바로 응답
        return RagResponse(
            answer="관련 문서를 찾지 못했습니다.",
            contexts=[],
            intent="rag",
        )

    # 3) RAG용 텍스트 리스트 만들기
    retrieved_sentences = []
    for c in contexts:
        prefix = f"[p.{c.page}] " if c.page is not None else ""
        retrieved_sentences.append(prefix + c.text)

    # 4) 페이지 이미지 한 장 선택 (가장 상위 컨텍스트 기준)
    top_ctx = contexts[0]
    page_img_path = top_ctx.page_image
    selected_image = None

    if page_img_path:
        try:
            img = Image.open(page_img_path).convert("RGB")
            # 시각 자료가 실제로 있는 페이지인지 확인
            if visual_detector.has_visual_content(img):
                selected_image = img
                print(f"[RAG][IMAGE] using page image: {page_img_path}")
            else:
                print(f"[RAG][IMAGE] no visual content detected for {page_img_path}")
        except Exception as e:
            print("[RAG][IMAGE] failed to open image:", repr(e))

    # 5) 최종 답변 합성 (텍스트 + 선택적 이미지)
    result = answer_agent.synthesize(
        query=body.query,
        retrieved_sentences=retrieved_sentences,
        image=selected_image,
        page=top_ctx.page or -1,
    )

    answer = result.get("answer", "응답 생성에 실패했습니다.")
    used_image = result.get("used_image", False)
    print(f"[RAG] Answer synthesis done. used_image={used_image}")
    print(">>> /rag/query finished")

    return RagResponse(
        answer=answer,
        contexts=contexts,
        intent="rag",
    )


# ---------- /calendar/events 엔드포인트 ----------

@router.get("/calendar/events", response_model=CalendarEventsResponse)
def get_calendar_events(limit: int = 10) -> CalendarEventsResponse:
    """
    Google Calendar에서 다가오는 일정 조회해서 프론트에 전달.
    """
    raw_events = list_upcoming_events(max_results=limit)

    events = [
        CalendarEvent(
            id=e["id"],
            title=e["title"],
            date=e["date"],
            time=e["time"],
            location=e.get("location") or "",
        )
        for e in raw_events
    ]
    return CalendarEventsResponse(events=events)
