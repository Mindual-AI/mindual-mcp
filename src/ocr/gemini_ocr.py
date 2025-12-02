# src/ocr/gemini_ocr.py
# Gemini로 OCR
import google.generativeai as genai
from PIL import Image
import os
from src.config import GEMINI_API_KEY, GEMINI_MODEL_ID

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL_ID)

def ocr_page(img_path: str, output_path: str):
    image = Image.open(img_path)
    response = model.generate_content([
        "이 이미지의 텍스트를 가능한 정확하게 추출해줘. 줄바꿈을 유지하고 표 구조는 그대로 표현해줘.",
        image
    ])
    text = response.text or ""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"✅ OCR complete: {output_path}")

def ocr_all_images(input_folder="data/interim", output_folder="data/processed"):
    os.makedirs(output_folder, exist_ok=True)
    for fname in sorted(os.listdir(input_folder)):
        if fname.endswith(".jpg"):
            ocr_page(os.path.join(input_folder, fname),
                     os.path.join(output_folder, fname.replace(".jpg", ".txt")))
