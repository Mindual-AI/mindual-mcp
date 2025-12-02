CREATE TABLE IF NOT EXISTS manuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT UNIQUE,
    model_list TEXT,
    language TEXT,
    title TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_id INTEGER,
    section_id INTEGER,
    page INTEGER,
    content TEXT,
    meta TEXT,
    FOREIGN KEY(manual_id) REFERENCES manuals(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
USING fts5(content, content='chunks', content_rowid='id');

CREATE TABLE IF NOT EXISTS page_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_id INTEGER NOT NULL,
    page INTEGER NOT NULL,
    path TEXT NOT NULL,                -- 예: "page_images/1/page_3.png"
    UNIQUE(manual_id, page),
    FOREIGN KEY(manual_id) REFERENCES manuals(id)
);