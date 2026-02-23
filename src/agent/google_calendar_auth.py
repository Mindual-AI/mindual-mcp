# scripts/google_calendar_auth.py
from __future__ import annotations

import os.path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Calendar에 일정 추가/수정 권한
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def main():
    creds = None

    # 이미 저장된 token.json이 있다면 재사용
    if os.path.exists("../../token.json"):
        creds = Credentials.from_authorized_user_file("../../token.json", SCOPES)

    # token.json이 없거나, 만료/유효하지 않으면 새로 인증
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 인증 결과를 token.json으로 저장
        with open("../../token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    print("Google Calendar 인증 완료")
    print("token.json 생성 서버에서 자동 사용")


if __name__ == "__main__":
    main()
