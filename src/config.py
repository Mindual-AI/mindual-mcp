# src/config.py
# 경로/환경변수 로딩
import os
from dotenv import load_dotenv
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# DB 경로
DB_PATH = os.getenv("DB_PATH", "./manuals.sqlite")

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.0-flash")

# 검색 기본 파라미터
RAG_MAX_DOCS = int(os.getenv("RAG_MAX_DOCS", "5"))

# === RAG / Chroma 설정 ===
BASE_DIR = Path(__file__).resolve().parents[1]
CHROMA_DIR = BASE_DIR / "indexes"          # ./indexes 디렉토리
CHROMA_COLLECTION_NAME = "manual_sentences"
