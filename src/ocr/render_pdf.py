# src/ocr/render_pdf.py
# PDF → PIL 이미지
from pdf2image import convert_from_path
import os

def render_pdf(pdf_path: str, output_folder: str):
    os.makedirs(output_folder, exist_ok=True)
    pages = convert_from_path(pdf_path, dpi=200)
    for i, page in enumerate(pages, start=1):
        out_path = os.path.join(output_folder, f"page_{i}.jpg")
        page.save(out_path, "JPEG")
    print(f"✅ Render complete: {len(pages)} pages saved to {output_folder}")

# 사용 예시
# render_pdf("data/raw/WW90T3000KW.pdf", "data/interim")
