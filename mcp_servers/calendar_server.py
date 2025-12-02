# src/agent/calendar_server.py
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from pathlib import Path
import os

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
REDIRECT_URI = "http://localhost:8100/calendar/oauth2callback"

app = FastAPI()

@app.get("/calendar/auth")
def calendar_auth():
    # 구글 OAuth 시작
    flow = Flow.from_client_secrets_file(
        "credentials.json",
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(prompt="consent")
    os.environ["OAUTH_STATE"] = state
    return RedirectResponse(auth_url)


@app.get("/calendar/oauth2callback")
def calendar_callback(code: str):
    # 구글이 되돌려준 code로 토큰 발급받고 token.json 저장
    state = os.environ.get("OAUTH_STATE")
    flow = Flow.from_client_secrets_file(
        "credentials.json",
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    flow.fetch_token(code=code)

    creds = flow.credentials
    Path("token.json").write_text(creds.to_json(), encoding="utf-8")

    # 토큰 저장 후 웹 앱으로 리다이렉트
    return RedirectResponse("http://localhost:5173/")