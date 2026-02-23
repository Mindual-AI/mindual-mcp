# src/agent/agent_init.py
# Gemini 기반 에이전트 초기화 및 질의 처리
from typing import Dict, Any, List
import time

import google.generativeai as genai

from src.config import GEMINI_API_KEY, GEMINI_MODEL_ID
from src.agent.system_prompt import SYSTEM_PROMPT
from src.agent.mcp_tools import search_manual, lookup_trouble, propose_next_action

from src.parse.rules import extract_reminder
from src.agent.calendar_client import create_reminder_event


# Gemini 초기화
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

_model = genai.GenerativeModel(GEMINI_MODEL_ID) if GEMINI_API_KEY else None

def _call_gemini(prompt: str) -> str:
    """
    Gemini 호출 래퍼: 로그와 간단한 타임 계측만 추가
    """
    if _model is None:
        # 안전장치: 모델이 없을 때는 바로 리턴
        print("[Gemini] _model is None, skip LLM call")
        return "LLM이 설정되어 있지 않아, 검색된 매뉴얼 내용을 그대로 참고해 주세요."

    print("[Gemini] call start")
    t0 = time.time()

    #  타임아웃: 30초 이상 걸리면 예외
    try:
        resp = _model.generate_content(
            prompt,
        )
    except Exception as e:
        print("[Gemini] exception:", repr(e))
        raise

    dt = time.time() - t0
    print(f"[Gemini] call end, {dt:.2f}s")

    text = getattr(resp, "text", None)
    if not text and getattr(resp, "candidates", None):
        try:
            text = resp.candidates[0].content.parts[0].text
        except Exception:
            text = None

    return text or "Gemini 응답이 비어 있습니다."

# 헬퍼: 검색 컨텍스트 문자열 구성
def _build_context(query: str, hits: List[Dict[str, Any]]) -> str:
    """
    FAISS / manual 검색 결과(hits)를 사람이 읽기 좋은 문자열로 변환.
    hits: [{ "content": ..., "page": ..., ... }, ...]
    """
    if not hits:
        return "검색 결과 없음."

    lines: List[str] = []
    for i, h in enumerate(hits, 1):
        prefix = f"[{i}] (page {h.get('page', '?')})"
        content = h.get("content", "")
        lines.append(f"{prefix}\n{content}\n")

    return "\n".join(lines)


# 메인 엔트리: answer_query
def answer_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    print(">>> answer_query called with:", payload, flush=True)
    """
    payload = {
      "query": "...",            # 사용자의 자연어 질문
      "device_state": {...},     # 선택: 현재 디바이스 상태 정보
      "error_code": "E05"        # 선택: 오류 코드
    }

    반환:
    {
      "answer": str,       # LLM 또는 컨텍스트 기반 응답
      "proactive": str?,   # 능동 제안 텍스트(있다면)
      "trouble": str?,     # 오류 코드 설명(있다면)
      "used_llm": bool     # LLM 사용 여부
    }
    """

    query = (payload.get("query") or "").strip()
    device_state = payload.get("device_state") or {}
    error_code = payload.get("error_code")

    # 자연어 리마인드 → Google Calendar 일정 생성
    reminder = extract_reminder(query) if query else None
    if reminder:
        print("[REMINDER] create event:", reminder.summary, reminder.start, reminder.end)
        event_id, link = create_reminder_event(
            summary=reminder.title,
            start=reminder.start_dt,
        )

        pretty_time = reminder.start_dt.strftime("%m월 %d일 %p %I시").replace("AM", "오전").replace("PM", "오후")

        msg = f"{pretty_time} '{reminder.title}' 일정이 Google Calendar에 추가되었습니다."
        if link:
            msg += f"\n(캘린더에서 보기: {link})"

        return {
            "answer": msg,
            "proactive": None,
            "trouble": None,
            "used_llm": False,
            "calendar_event_id": event_id,
        }

    # 1) 능동 제안 (간단 규칙 기반)
    proactive: str | None = propose_next_action(device_state) if device_state else None

    # 2) 오류 코드가 있으면 관련 트러블슈팅 먼저 조회
    trouble_txt: str | None = None
    if error_code:
        t = lookup_trouble(error_code)
        if t:
            trouble_txt = (
                f"[{error_code}] 증상: {t.get('symptom', '')}\n"
                f"원인: {t.get('cause', '')}"
            )

    # 3) 매뉴얼 검색: 질문이 있으면 질문으로, 없으면 오류코드/기본 사용으로
    search_query = query if query else (error_code or "기본 사용")
    hits = search_manual(search_query)
    context_txt = _build_context(search_query, hits)

    # 4) LLM이 없는 경우: 검색 결과만 그대로 반환
    if not _model:
        return {
            "answer": context_txt,
            "proactive": proactive,
            "trouble": trouble_txt,
            "used_llm": False,
        }

    # 5) 프롬프트 구성 (f-string 대신 리스트로 안전하게 조립)
    prompt_parts: List[str] = []

    # 시스템 프롬프트
    prompt_parts.append(SYSTEM_PROMPT)
    prompt_parts.append("")  # 빈 줄

    # 사용자 질문
    prompt_parts.append("사용자 질문:")
    prompt_parts.append(query or error_code or "질문 없음")
    prompt_parts.append("")

    # 검색 컨텍스트
    prompt_parts.append("검색 컨텍스트(매뉴얼 발췌):")
    prompt_parts.append(context_txt)
    prompt_parts.append("")

    # 오류 코드 정보
    if trouble_txt:
        prompt_parts.append("오류코드 정보:")
        prompt_parts.append(trouble_txt)
        prompt_parts.append("")

    # 능동 제안
    if proactive:
        prompt_parts.append("능동 제안 후보:")
        prompt_parts.append(proactive)
        prompt_parts.append("")

    # 출력 형식 가이드
    prompt_parts.append(
        "위 정보를 바탕으로, 단계형으로 간결히 답변해라. "
        "경고가 있으면 최상단에 '⚠️ 주의'로 강조해라."
    )

    prompt = "\n".join(prompt_parts)

    # 6) Gemini 호출
    resp = _model.generate_content(prompt)
    answer_text = getattr(resp, "text", None) or "응답 생성에 실패했습니다."

    return {
        "answer": answer_text,
        "proactive": proactive,
        "trouble": trouble_txt,
        "used_llm": True,
    }
