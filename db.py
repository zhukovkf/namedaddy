"""
Слой работы с базой данных (SQLite).

Хранит нормализованную выборку из открытого реестра товарных знаков
Роспатента (https://rospatent.gov.ru/opendata/7730176088-tz) и предоставляет
быстрый поиск кандидатов для дальнейшего сравнения в similarity.py.

Схема сознательно упрощена относительно полной структуры CSV Роспатента
(см. structure-20180828.csv на странице открытых данных) — при интеграции
реальных дампов сверьтесь с актуальным файлом структуры, названия колонок
там периодически меняются.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "trademarks.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trademarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reg_number TEXT,
    app_number TEXT,
    app_date TEXT,
    reg_date TEXT,
    name_text TEXT NOT NULL,
    mktu_classes TEXT NOT NULL,      -- "25,35,41"
    status TEXT NOT NULL DEFAULT 'active',  -- active | expired | terminated
    holder TEXT,
    normalized_name TEXT NOT NULL,
    phonetic_key TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_normalized_name ON trademarks(normalized_name);
CREATE INDEX IF NOT EXISTS idx_phonetic_key ON trademarks(phonetic_key);

-- Триграммный FTS5-индекс: в отличие от обычного FTS5 (токены целиком/префиксы),
-- trigram-токенизатор находит совпадения ПОДСТРОК в любом месте названия —
-- важно, т.к. запрос может быть длиннее/короче/содержать похожий кусок
-- существующего знака ("Соколёнок" должен находить "Сокол" и наоборот).
CREATE VIRTUAL TABLE IF NOT EXISTS trademarks_fts USING fts5(
    normalized_name, phonetic_key, content='trademarks', content_rowid='id',
    tokenize='trigram'
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trademarks_ai AFTER INSERT ON trademarks BEGIN
    INSERT INTO trademarks_fts(rowid, normalized_name, phonetic_key)
    VALUES (new.id, new.normalized_name, new.phonetic_key);
END;
"""


@contextmanager
def get_conn(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH):
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.executescript(TRIGGERS)
        conn.commit()


def insert_trademark(conn, record: dict):
    conn.execute(
        """
        INSERT INTO trademarks
            (reg_number, app_number, app_date, reg_date, name_text,
             mktu_classes, status, holder, normalized_name, phonetic_key)
        VALUES (:reg_number, :app_number, :app_date, :reg_date, :name_text,
                :mktu_classes, :status, :holder, :normalized_name, :phonetic_key)
        """,
        record,
    )


def _windows(s: str, size: int = 4):
    s = s.replace(" ", "")
    if len(s) <= size:
        return [s] if s else []
    return [s[i:i + size] for i in range(len(s) - size + 1)]


def candidate_search(conn, normalized_query: str, phonetic_query: str, limit: int = 500):
    """
    Первичный грубый отбор кандидатов через триграммный FTS5-индекс, чтобы
    не гонять дорогое нечёткое сравнение (similarity.py) по всей базе.

    Важно: сама по себе триграммная подстрочная схожесть асимметрична —
    короткое хранимое название может быть подстрокой длинного запроса и
    наоборот. Поэтому запрос режется на скользящие окна фиксированной
    длины и ищутся кандидаты, содержащие ХОТЯ БЫ ОДНО из окон (по названию
    или по фонетическому ключу) — это даёт широкий, но дешёвый набор
    кандидатов, точную оценку схожести потом считает similarity.py.
    """
    name_windows = _windows(normalized_query)
    phon_windows = _windows(phonetic_query)

    clauses = []
    if name_windows:
        clauses.append("normalized_name: (" + " OR ".join(f'"{w}"' for w in name_windows) + ")")
    if phon_windows:
        clauses.append("phonetic_key: (" + " OR ".join(f'"{w}"' for w in phon_windows) + ")")

    rows = []
    if clauses:
        match_expr = " OR ".join(clauses)
        try:
            rows = conn.execute(
                """
                SELECT t.* FROM trademarks t
                JOIN trademarks_fts f ON t.id = f.rowid
                WHERE trademarks_fts MATCH ?
                LIMIT ?
                """,
                (match_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    if not rows:
        # запасной путь для очень коротких запросов (< 4 символов), где
        # триграммных окон не набирается
        rows = conn.execute(
            "SELECT * FROM trademarks WHERE normalized_name LIKE ? OR phonetic_key LIKE ? LIMIT ?",
            (f"%{normalized_query}%", f"%{phonetic_query}%", limit),
        ).fetchall()

    return rows


def count_records(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM trademarks").fetchone()[0]
