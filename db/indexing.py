import re
import sqlite3
from pathlib import Path
import argparse


def parse_pages(text: str):
    """
    규칙:
    - '숫자 한 줄만 있는 줄'을 페이지 번호로 인식
    - 그 숫자 줄 '앞에 있던 텍스트 전체'를 그 페이지의 내용으로 저장
    - 예:
      [텍스트...]
      1
      [텍스트...]
      2
      → 1: 첫 블록, 2: 두 번째 블록
    """
    lines = text.splitlines()

    page_map = {}
    buf = []              # 현재 페이지 텍스트를 임시로 쌓는 버퍼
    page_header_pattern = re.compile(r"^\s*(\d+)\s*$")  # 숫자만 있는 줄

    for line in lines:
        m = page_header_pattern.match(line)
        if m:
            page_num = int(m.group(1))

            # 지금까지 쌓인 텍스트를 page_num으로 저장
            content = "\n".join(buf).strip()
            if content:
                page_map[page_num] = content

            # 다음 페이지 텍스트를 위한 버퍼 초기화
            buf = []
        else:
            buf.append(line)

    # 만약 파일 끝에 숫자가 없이 텍스트가 남아 있으면 (예외 케이스)
    # 마지막 번호 + 1 로 넣을 수도 있지만, 은선 파일은 거의 항상 '숫자로 끝'일 거라
    # 애매하면 그냥 버려도 됨.
    # 필요하면 아래 주석 풀어서 쓸 수 있음.
    #
    # if buf:
    #     last_page = max(page_map.keys()) if page_map else 1
    #     page_map[last_page + 1] = "\n".join(buf).strip()

    return page_map


def main(db_path: str, txt_path: str, manual_id: int):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    print(f"[INFO] merged 텍스트 로딩: {txt_path}")
    text = Path(txt_path).read_text(encoding="utf-8")

    page_map = parse_pages(text)
    print(f"[INFO] 총 {len(page_map)} 페이지 파싱됨: {sorted(page_map.keys())[:10]} ...")

    # 기존 manual_id 데이터 삭제
    cur.execute("DELETE FROM chunks WHERE manual_id = ?", (manual_id,))
    conn.commit()

    # 페이지 순서대로 DB 저장
    for page, content in sorted(page_map.items()):
        if not content.strip():
            continue

        try:
            cur.execute(
                """
                INSERT INTO chunks (manual_id, page, content, embedding)
                VALUES (?, ?, ?, NULL)
                """,
                (manual_id, page, content),
            )
        except sqlite3.OperationalError:
            cur.execute(
                """
                INSERT INTO chunks (manual_id, page, content)
                VALUES (?, ?, ?)
                """,
                (manual_id, page, content),
            )

    conn.commit()
    conn.close()

    print("[INFO] DB 저장 완료!")
    print(f"[INFO] 총 저장된 페이지: {len(page_map)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="db/manuals.sqlite")
    parser.add_argument("--txt", required=True)
    parser.add_argument("--manual-id", type=int, required=True)
    args = parser.parse_args()

    main(args.db, args.txt, args.manual_id)