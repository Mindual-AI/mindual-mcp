# src/integrations/google_calendar.py
from __future__ import annotations
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


# 구글 토큰 파일 위치 (OAuth 수행 후 생성된 파일)
TOKEN_PATH = "token.json"


def get_calendar_service():
    """
    token.json 을 기반으로 구글 캘린더 서비스 객체 생성
    """
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, ["https://www.googleapis.com/auth/calendar.events"])
    return build("calendar", "v3", credentials=creds)


def create_event(summary: str, start_dt: datetime, end_dt: datetime, timezone="Asia/Seoul"):
    """
    Google Calendar 일정 생성 함수
    """
    service = get_calendar_service()

    event_body = {
        "summary": summary,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": timezone,
        }
    }

    event = service.events().insert(
        calendarId="primary",
        body=event_body
    ).execute()

    return event
