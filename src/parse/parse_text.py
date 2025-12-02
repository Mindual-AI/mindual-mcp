# src/parse/parse_text.py
# OCR 결과 → 구조화
import os
from typing import List
import kss


def merge_ocr_text(input_folder="data/processed", output_file="data/processed/merged_manual.txt"):
    texts = []
    for fname in sorted(os.listdir(input_folder)):
        if fname.endswith(".txt"):
            with open(os.path.join(input_folder, fname), encoding="utf-8") as f:
                texts.append(f.read().strip())
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(texts))
    print(f"✅ Merged OCR text saved: {output_file}")


def split_korean_sentences(text: str) -> List[str]:
    """
    한국어 문장을 줄바꿈 + KSS 기준으로 나눠준다.
    너무 짧은 / 공백 문장은 버린다.
    """
    chunks = [t.strip() for t in text.split("\n") if t.strip()]
    sentences: List[str] = []

    for ch in chunks:
        for sent in kss.split_sentences(ch):
            s = sent.strip()
            if s:
                sentences.append(s)

    return sentences
