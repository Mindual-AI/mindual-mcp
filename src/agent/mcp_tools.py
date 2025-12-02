# src/agent/mcp_tools.py
# MCP Tool: RAG 검색, 오류 조회, 제안 기능 호출
from typing import Optional, Dict, Any, List
import sqlite3
from src.config import DB_PATH
from src.index.fts import fts_search

def search_manual(query: str) -> List[Dict[str, Any]]:
    """FTS5 기반 매뉴얼 검색 → 상위 문단 리스트 반환"""
    return fts_search(query)

def lookup_trouble(code: str) -> Optional[Dict[str, Any]]:
    """오류코드 조회 (없으면 None)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT code, symptom, cause, resolution_step_id FROM troubleshooting WHERE code=? LIMIT 1",
            (code,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def propose_next_action(device_state: Dict[str, Any]) -> Optional[str]:
    """아주 간단한 규칙 기반 제안 (MVP)"""
    days = device_state.get("days_since_last_clean", 0)
    if days and days > 30:
        return "최근 30일 이상 통세척을 수행하지 않았습니다. 통세척 코스를 실행하는 것을 권장합니다."
    if device_state.get("error_code"):
        code = device_state["error_code"]
        t = lookup_trouble(code)
        if t:
            return f"[{code}] 증상: {t['symptom']} / 원인: {t['cause']}"
        return f"[{code}] 등록된 오류 코드 정보가 없습니다."
    return None
