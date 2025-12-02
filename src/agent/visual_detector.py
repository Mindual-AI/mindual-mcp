import google.generativeai as genai
from PIL import Image
from src.config import GEMINI_API_KEY

class VisualContentDetector:
    def __init__(self):
        """
        시각자료(그림/도식/아이콘) 존재 여부를 판단하는 Vision Agent
        """
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    def has_visual_content(self, image: Image.Image) -> bool:
        """
        이미지 안에 '제품 관련 시각자료'가 있는지 YES/NO 판단
        """
        prompt = """
이 페이지에 '제품 관련 시각자료'가 있는지 YES 또는 NO로만 답하세요.

시각자료 정의:
- 제품 또는 부품 그림(라인 드로잉, 일러스트)
- 손동작(버튼 누르기, 분리 등의 조작 이미지)
- 단계 그림(STEP1, STEP2 등)


시각자료 아님:
- 텍스트만 있는 페이지
- 표(테이블)
        """

        try:
            response = self.model.generate_content(
                [prompt, image],
                generation_config={"max_output_tokens": 5}
            )
            ans = response.text.strip().upper()
            return "YES" in ans
        except Exception as e:
            print("[ERROR] Vision 판단 실패:", e)
            return False