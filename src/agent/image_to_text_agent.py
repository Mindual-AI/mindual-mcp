# src/agent/image_to_text_agent.py

import google.generativeai as genai
from PIL import Image
from src.config import GEMINI_API_KEY

# Gemini 초기화
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Vision 지원 모델
VISION_MODEL_ID = "gemini-2.0-flash"
vision_model = genai.GenerativeModel(VISION_MODEL_ID)


def analyze_image(image_path: str) -> str:
    """
    전자기기 실물 사진에 대해 '객관적'인 요소만 묘사하는 분석 함수
    (추론, 기능 설명, 추정 금지)
    """
    try:
        img = Image.open(image_path)
    except:
        return "이미지를 불러올 수 없습니다."

    prompt = """
당신은 전자기기 실물 사진을 '객관적으로' 묘사하는 AI입니다.

⚠️ 절대로 추론, 추정, 기능 설명, 목적 설명을 하지 마세요.
예: "~버튼일 것이다", "~기능으로 보인다", "~을 조작하는 듯 하다" 금지.
오직 '보이는 것'만 묘사하세요.

이미지를 보고 아래 요소를 기술하세요:

1) 기기 외형(모양, 시각적 특징)
2) 눈에 보이는 버튼/레버/포트의 위치와 생김새
3) 텍스트/라벨/아이콘이 있으면 그대로 적기
4) 색상, 형태, 재질 등 순수 시각적 정보

절대로 기능, 역할, 용도를 말하지 마세요.
"""

    resp = vision_model.generate_content([prompt, img])
    return resp.text.strip() if resp.text else "이미지 분석 결과 없음"