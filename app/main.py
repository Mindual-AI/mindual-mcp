# app/main.py

from fastapi import FastAPI, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Optional, List, Dict
from pathlib import Path

from src.agent.router import route_query, route_image_query  # 🔥 라우터 에이전트

app = FastAPI()

# CORS 설정 (이미 있다면 중복되지만 큰 문제는 아님)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 필요하면 도메인 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskResponse(BaseModel):
    answer: str
    intent: str
    source: str
    proactive: Optional[str] = None
    error: Optional[str] = None
    pages: List[Dict] = []
    uploaded_image_path: Optional[str] = None


# 🔧 Pydantic v2: "class not fully defined" 방지용
AskResponse.model_rebuild()


@app.post("/ask", response_model=AskResponse)
async def ask(
    query: str = Form(...),
    k: int = Form(5),
    file: Any = File(None),
) -> AskResponse:
    """
    - 텍스트만 오면: route_query() 사용 (RAG)
    - 이미지 + 텍스트 오면: route_image_query() 사용 (이미지 에이전트 + RAG)
    """
    # 1) 이미지가 같이 온 경우 → 파일 저장 후 이미지 라우팅
    if isinstance(file, UploadFile) and getattr(file, "filename", None):
        upload_dir = Path("data/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)

        save_path = upload_dir / file.filename
        with save_path.open("wb") as f:
            f.write(await file.read())

        result = route_image_query(
            query=query,
            image_path=str(save_path),
            k=k,
        ) or {}
    else:
        # 2) 텍스트만 온 경우 또는 file 필드가 비어 있는 경우 → 기존 RAG 라우터
        result = route_query(query=query, k=k) or {}

    # 3) 라우터 결과를 AskResponse 형태로 정리
    return AskResponse(
        answer=result.get("answer", ""),
        intent=result.get("intent", "manual"),
        source=result.get("source", "rag"),
        proactive=result.get("proactive"),
        error=result.get("error"),
        pages=result.get("pages", []),
        uploaded_image_path=result.get("uploaded_image_path"),
    )


@app.get("/health")
def health():
    return {"status": "ok"}