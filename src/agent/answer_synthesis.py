import google.generativeai as genai
from PIL import Image
from src.config import GEMINI_API_KEY


class AnswerSynthesisAgent:
    def __init__(self):
        """
        query + text retrieval + (optional image)를 결합해
        최종 답변을 생성하는 Agent
        """
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    def synthesize(
        self,
        query: str,
        retrieved_sentences: list[str],
        image: Image.Image | None,
        page: int
    ) -> dict:

        # 🔹 Retrieval 출력 텍스트 합치기
        joined_text = "\n".join(retrieved_sentences)

        # 🔹 공통 인스트럭션
        base_prompt = f"""
당신은 가전제품 사용설명서 상담 전문가입니다.

아래 정보를 기반으로 사용자의 질문에 답하세요.

📌 답변 규칙
1) TEXT(설명서 내용)을 최우선적으로 기반으로 답변하세요.
2) IMAGE가 제공된 경우, 질문과 직접 관련 있을 때만 사용하세요.
3) 이미지가 질문과 무관하면 사용하지 말고 TEXT만 기반으로 답하세요.
4) 허구의 정보는 추가하지 마세요.
5) 가능한 명확하고 구체적으로 답변하세요.

🧑‍💬 사용자 질문:
{query}

📄 TEXT (Retrieval 결과):
{joined_text}
"""

        try:
            # ▣ CASE 1 — 이미지도 함께 분석하는 멀티모달 호출
            if image is not None:
                response = self.model.generate_content(
                    [base_prompt, image],
                    generation_config={
                        "temperature": 0.2,
                        "max_output_tokens": 300
                    }
                )
                used_image = True

            # ▣ CASE 2 — 이미지 없이 텍스트만 분석
            else:
                response = self.model.generate_content(
                    base_prompt,
                    generation_config={
                        "temperature": 0.2,
                        "max_output_tokens": 300
                    }
                )
                used_image = False

            final_answer = response.text.strip()

            return {
                "answer": final_answer,
                "used_image": used_image,
                "page": page,
            }

        except Exception as e:
            print("[ERROR] Answer synthesis failed:", e)
            return {
                "answer": "답변 생성 중 오류가 발생했습니다.",
                "used_image": False,
                "page": page
            }
