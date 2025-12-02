from __future__ import annotations

from datetime import datetime, timedelta
from typing import Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# 구글 캘린더 권한 범위
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _get_calendar_service():
    """
    Google Calendar API 서비스 객체 생성.
    token.json 은 Google Calendar Quickstart를 통해 미리 발급 받아 두었다고 가정.
    """
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    service = build("calendar", "v3", credentials=creds)
    return service


def create_reminder_event(
    summary: str,
    start: datetime,
    duration_min: int = 60,
    calendar_id: str = "primary",
) -> Tuple[str, str]:
    """
    구글 캘린더에 이벤트 생성 후 (event_id, html_link) 반환.
    """
    service = _get_calendar_service()
    end = start + timedelta(minutes=duration_min)

    event_body = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Seoul"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Seoul"},
    }

    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return created.get("id"), created.get("htmlLink", "")

if __name__ == "__main__":
    # 단독 실행 시 테스트 일정 생성
    from datetime import datetime

    print("[TEST] Google Calendar 이벤트 생성 테스트 시작")

    event_id, link = create_reminder_event(
        "테스트 일정 생성",
        datetime(2025, 12, 3, 15, 0),
        duration_min=30,
    )

    print("[TEST] 생성된 이벤트 ID:", event_id)
    print("[TEST] 캘린더 링크:", link)
