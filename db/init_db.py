# db/init_db.py
from pathlib import Path
import sys
import sqlite3

# ✅ 프로젝트 루트(/Users/yubin/Downloads/mindual-mcp)를 sys.path에 추가
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import DB_PATH

def init_db():
    db_path = Path(DB_PATH).resolve()
    schema_path = Path(__file__).with_name("schema.sql")
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.sql not found at: {schema_path}")

    schema_sql = schema_path.read_text(encoding="utf-8")

    print(f"[init_db] Using DB: {db_path}")
    print(f"[init_db] Using schema: {schema_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(schema_sql)
        conn.commit()

        # 테이블 목록 출력
        rows = conn.execute("""
          SELECT name FROM sqlite_master
          WHERE type IN ('table','view')
          ORDER BY name
        """).fetchall()
        print("[init_db] Objects created:")
        for (name,) in rows:
            print(" -", name)
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
