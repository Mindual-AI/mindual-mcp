# db/register_page_images.py
from pathlib import Path
import re
import sqlite3
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import DB_PATH  # 이미 쓰고 있는 DB_PATH 그대로 사용

DATA_DIR = BASE_DIR / "data"
PAGE_IMAGES_ROOT = DATA_DIR / "page_images"


def ensure_table(conn: sqlite3.Connection) -> None:
    """page_images 테이블이 없으면 생성."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS page_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manual_id INTEGER NOT NULL,
            page INTEGER NOT NULL,
            path TEXT NOT NULL,
            UNIQUE(manual_id, page),
            FOREIGN KEY(manual_id) REFERENCES manuals(id)
        );
        """
    )
    conn.commit()


def register_page_images() -> None:
    if not PAGE_IMAGES_ROOT.exists():
        print(f"⚠️ 디렉토리 없음: {PAGE_IMAGES_ROOT}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    ensure_table(conn)

    inserted = 0

    # ✅ data/page_images 아래의 manual_id 디렉토리들 순회
    for manual_dir in sorted(PAGE_IMAGES_ROOT.iterdir()):
        if not manual_dir.is_dir():
            continue

        try:
            manual_id = int(manual_dir.name)
        except ValueError:
            print(f"⚠️ 디렉토리 이름이 숫자 아님, 건너뜀: {manual_dir}")
            continue

        # ✅ manual_id 디렉토리 안의 이미지 파일들 순회
        for img_path in sorted(manual_dir.iterdir()):
            if not img_path.is_file():
                continue

            # 확장자 체크
            if img_path.suffix.lower() not in [".png", ".jpg", ".jpeg"]:
                print(f"⚠️ 이미지 파일 아님, 건너뜀: {img_path}")
                continue

            # 파일 이름 패턴: page_3.png 또는 3.png 둘 다 허용
            stem = img_path.stem  # "page_3" 또는 "3"
            m = re.match(r"page_(\d+)$", stem, re.IGNORECASE)
            if not m:
                m = re.match(r"(\d+)$", stem)

            if not m:
                print(f"⚠️ page_X 또는 X 형식 아님, 건너뜀: {img_path}")
                continue

            page = int(m.group(1))
            # DB에는 data 기준 상대 경로로 저장 (예: "page_images/1/3.png")
            rel_path = str(img_path.relative_to(DATA_DIR))

            cur.execute(
                """
                INSERT OR REPLACE INTO page_images (manual_id, page, path)
                VALUES (?, ?, ?)
                """,
                (manual_id, page, rel_path),
            )
            inserted += 1

    conn.commit()
    conn.close()
    print(f"✅ page_images 등록 완료: {inserted} rows")


if __name__ == "__main__":
    register_page_images()