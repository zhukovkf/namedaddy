"""
Загрузка открытых данных Роспатента (реестр товарных знаков РФ) в SQLite.

Источник: https://rospatent.gov.ru/opendata/7730176088-tz
Файл структуры (сверяйте перед каждым запуском — колонки/версии меняются):
https://rospatent.gov.ru/opendata/7730176088-tz/structure-20180828.csv

ВНИМАНИЕ: реальный дамп реестра — это несколько гигабайт и ~1-2 млн строк.
Скрипт читает файл чанками, чтобы не упасть по памяти.

Т.к. точные названия колонок периодически меняются, ниже задан COLUMN_MAP —
после скачивания актуального structure-*.csv откройте его и поправьте
значения (ключи слева менять не нужно, справа — реальные заголовки CSV).
"""

import argparse
import csv
import re
import sys
from datetime import datetime, date
from pathlib import Path

from db import init_db, get_conn, insert_trademark, DB_PATH
from similarity import normalize, phonetic_key

# Поправьте под актуальный structure-*.csv с opendata-страницы Роспатента
COLUMN_MAP = {
    "reg_number": "Номер регистрации",
    "app_number": "Номер заявки",
    "app_date": "Дата подачи заявки",
    "reg_date": "Дата регистрации",
    "name_text": "Словесный элемент",       # или "Наименование" в некоторых версиях
    "mktu_classes": "Классы МКТУ",           # обычно строка вида "09, 25, 35"
    "holder": "Правообладатель",
}

TM_TERM_YEARS = 10  # стандартный срок охраны товарного знака в РФ (продлеваем при наличии данных)


def _parse_date(raw: str):
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def infer_status(reg_date_raw: str) -> str:
    d = _parse_date(reg_date_raw)
    if not d:
        return "active"
    expiry = date(d.year + TM_TERM_YEARS, d.month, d.day)
    return "active" if expiry >= date.today() else "expired"


def clean_classes(raw: str) -> str:
    if not raw:
        return ""
    nums = re.findall(r"\d{1,2}", raw)
    return ",".join(sorted({n.zfill(2) for n in nums}, key=int))


def rows_from_csv(path: Path, delimiter: str, encoding: str):
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for raw in reader:
            name = raw.get(COLUMN_MAP["name_text"], "").strip()
            if not name:
                continue
            yield {
                "reg_number": raw.get(COLUMN_MAP["reg_number"], "").strip(),
                "app_number": raw.get(COLUMN_MAP["app_number"], "").strip(),
                "app_date": raw.get(COLUMN_MAP["app_date"], "").strip(),
                "reg_date": raw.get(COLUMN_MAP["reg_date"], "").strip(),
                "name_text": name,
                "mktu_classes": clean_classes(raw.get(COLUMN_MAP["mktu_classes"], "")),
                "status": infer_status(raw.get(COLUMN_MAP["reg_date"], "")),
                "holder": raw.get(COLUMN_MAP["holder"], "").strip(),
                "normalized_name": normalize(name),
                "phonetic_key": phonetic_key(name),
            }


def run(path: Path, delimiter: str = ";", encoding: str = "utf-8", batch_size: int = 5000):
    init_db()
    total = 0
    with get_conn() as conn:
        batch = []
        for record in rows_from_csv(path, delimiter, encoding):
            batch.append(record)
            if len(batch) >= batch_size:
                for r in batch:
                    insert_trademark(conn, r)
                conn.commit()
                total += len(batch)
                print(f"...загружено {total} записей", file=sys.stderr)
                batch.clear()
        if batch:
            for r in batch:
                insert_trademark(conn, r)
            conn.commit()
            total += len(batch)
    print(f"Готово. Всего загружено записей: {total}. БД: {DB_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Импорт открытых данных Роспатента в SQLite")
    parser.add_argument("csv_path", type=Path, help="Путь к скачанному CSV реестра товарных знаков")
    parser.add_argument("--delimiter", default=";")
    parser.add_argument("--encoding", default="utf-8")
    args = parser.parse_args()
    run(args.csv_path, args.delimiter, args.encoding)
