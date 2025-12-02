# src/parse/rules.py
# 정규식/룰 정의
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
import zoneinfo

KST = zoneinfo.ZoneInfo("Asia/Seoul")

WEEKDAY_MAP = {
    "월": 0,
    "화": 1,
    "수": 2,
    "목": 3,
    "금": 4,
    "토": 5,
    "일": 6,
}


@dataclass
class ParsedReminder:
    title: str
    start_dt: datetime


def _parse_korean_datetime(text: str) -> datetime | None:
    """
    '이번주 일요일 오전 10시에 에어컨 청소 예약해줘' 같은 문장에서
    날짜 + 시간을 대충 뽑아 datetime 으로 만든다.
    - 이번주 일요일
    - 오늘 / 내일
    - 30일
    - 오전/오후 10시, 10시 30분
    정도만 처리.
    """
    now = datetime.now()
    base_date = now.date()

    t = text

    # 1) 기준 날짜(오늘/내일/이번주 요일/몇일)
    target_date = None

    if "오늘" in t:
        target_date = base_date
    elif "내일" in t:
        target_date = base_date + timedelta(days=1)
    else:
        # 요일
        weekday_char = None
        for ch in WEEKDAY_MAP.keys():
            if ch + "요일" in t:
                weekday_char = ch
                break

        if weekday_char is not None and ("이번주" in t or "이번 주" in t):
            today_w = base_date.weekday()          # 월=0
            target_w = WEEKDAY_MAP[weekday_char]   # 일=6
            delta = (target_w - today_w) % 7
            target_date = base_date + timedelta(days=delta)

        # "30일" 같은 패턴
        if target_date is None:
            m_day = re.search(r"(\d{1,2})일", t)
            if m_day:
                day = int(m_day.group(1))
                # 같은 달 안에서 처리 (필요하면 더 정교하게)
                try:
                    target_date = base_date.replace(day=day)
                except ValueError:
                    # 이상한 날짜면 그냥 패스
                    target_date = None

    # 위 케이스 아무것도 안 잡히면 오늘 기준
    if target_date is None:
        target_date = base_date

    # 2) 시간 (오전/오후 + 시/분)
    m_time = re.search(r"(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?", t)
    if m_time:
        ampm = m_time.group(1)
        hour = int(m_time.group(2))
        minute = int(m_time.group(3) or 0)

        if ampm == "오후" and hour < 12:
            hour += 12
        if ampm == "오전" and hour == 12:
            hour = 0
    else:
        # 시간 명시 없으면 오전 9시 기본
        hour = 9
        minute = 0

    return datetime(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
        hour=hour,
        minute=minute,
    )


def _extract_title(text: str) -> str:
    """
    날짜/시간/예약 관련 문구를 떼고 남은 부분을 일정 제목으로 사용.
    '이번주 일요일 오전 10시에 에어컨 청소 예약해줘' → '에어컨 청소'
    정도를 목표로 함.
    """
    t = text

    # 날짜/시간 표현 제거
    t = re.sub(r"(이번주|이번 주|오늘|내일|모레)", "", t)
    t = re.sub(r"\d{1,2}일", "", t)
    t = re.sub(r"(오전|오후)\s*\d{1,2}시(\s*\d{1,2}분)?", "", t)

    # 예약/일정/알림 관련 동사 제거
    t = re.sub(r"(일정\s*(추가|등록|잡아줘|잡아 줘)?)", "", t)
    t = re.sub(r"(예약해줘|예약 해줘|예약해 줘|예약 해 줘)", "", t)
    t = re.sub(r"(알림\s*(설정|맞춰줘|맞춰 줘)?)", "", t)
    t = re.sub(r"해줘", "", t)

    # 조사/불필요한 구두점 정리
    t = t.replace("에 ", " ")
    t = t.replace("를 ", " ")
    t = t.replace("을 ", " ")
    t = t.replace("에", " ")
    t = t.strip(" ,.!?\"'")

    if not t:
        return "리마인더"

    return t.strip()


def extract_reminder(text: str):
    """
    routes.py 에서 사용하는 API:
    - 성공 시: {"intent": "reminder", "title": str, "start": datetime, "end": datetime}
    - 실패 시: None
    """
    dt = _parse_korean_datetime(text)
    if not dt:
        return None

    title = _extract_title(text)
    # 기본 1시간짜리 일정으로 가정
    end_dt = dt + timedelta(hours=1)

    return {
        "intent": "reminder",
        "title": title,
        "start": dt,
        "end": end_dt,
    }