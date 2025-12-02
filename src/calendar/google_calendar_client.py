# src/calendar/google_calendar_client.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict, Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _get_service():
    """
    token.json + SCOPES 기반으로 Calendar 서비스 클라이언트 생성.
    (scripts/google_calendar_auth.py에서 이미 token.json 발급했다고 가정)
    """
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    service = build("calendar", "v3", credentials=creds)
    return service


def list_upcoming_events(max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Google Calendar 'primary'에서 앞으로 다가오는 일정 목록 조회.
    React에서 쓰기 좋게 날짜/시간을 잘라서 반환.
    """
    service = _get_service()

    now = datetime.now(timezone.utc).isoformat()  # RFC3339
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])

    parsed: List[Dict[str, Any]] = []
    for ev in events:
        start = ev.get("start", {})
        # 종종 dateTime / date 둘 중 하나만 온다
        dt_str = start.get("dateTime") or start.get("date")  # e.g. 2025-11-17T09:00:00+09:00
        date_str = ""
        time_str = ""

        if dt_str:
            # "2025-11-17" or "2025-11-17T09:00:00+09:00"
            date_str = dt_str[0:10]
            if "T" in dt_str:
                time_str = dt_str.split("T")[1][0:5]  # "09:00"

        parsed.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary") or "(제목 없음)",
                "location": ev.get("location") or "",
                "date": date_str,
                "time": time_str,
            }
        )

    return parsed
