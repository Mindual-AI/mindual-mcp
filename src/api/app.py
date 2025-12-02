# src/api/app.py
# FastAPI 진입점

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router as rag_router  # RAG 라우터

app = FastAPI(title="Mindual RAG API")

# 프론트(vite dev 서버)와 CORS 맞추기
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8100",
    "http://localhost:8100",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
# /rag/query 포함 모든 RAG 관련 엔드포인트는 routes.py에서만 관리
app.include_router(rag_router)

# data/processed 폴더를 /manual-pages 아래로 노출
app.mount(
    "/manual-pages",
    StaticFiles(directory="data/processed"),
    name="manual-pages",
)