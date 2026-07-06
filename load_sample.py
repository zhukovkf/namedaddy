"""
Загружает небольшой ДЕМОНСТРАЦИОННЫЙ набор данных (полностью вымышленные
названия, НЕ реальные записи реестра) — чтобы можно было сразу проверить
работу бота и алгоритма без скачивания полного дампа Роспатента.

Замените на реальный импорт через ingest.py, когда будет готов CSV.
"""

from db import init_db, get_conn, insert_trademark
from similarity import normalize, phonetic_key

DEMO_TRADEMARKS = [
    # (название, классы МКТУ, статус, правообладатель)
    ("Соколёнок", "29,30", "active", 'ООО "Демо-Продукт"'),
    ("Сокол", "29,32", "active", 'ООО "Пример Групп"'),
    ("СоколЪ Трейд", "35", "expired", 'ИП Демонстрационный'),
    ("Молочная Речка", "29", "active", 'ООО "Молторг"'),
    ("Молочная Речка Плюс", "35,39", "active", 'ООО "Молторг Плюс"'),
    ("ВкусноЛето", "30,43", "active", 'ООО "Лето Фудс"'),
    ("Вкусное Лето", "29", "terminated", 'ИП Иванова'),
    ("ГорныйКлюч", "32", "active", 'ООО "Напитки Плюс"'),
    ("Горный Ключъ", "32,33", "active", 'ООО "Вода Гор"'),
    ("Ромашка Дом", "35,41", "active", 'ООО "Ромашка"'),
    ("Технопарк Плюс", "42", "active", 'ООО "ТехноГрупп"'),
    ("СеверСтройМонтаж", "37", "active", 'ООО "СеверСтрой"'),
    ("АгроХолдинг Юг", "31,35", "active", 'ООО "АгроЮг"'),
    ("КотоФуд", "31", "active", 'ООО "Зоотовары Плюс"'),
    ("ЯркийДом", "20,35", "active", 'ООО "Дизайн Дом"'),
]


def main():
    init_db()
    with get_conn() as conn:
        for name, classes, status, holder in DEMO_TRADEMARKS:
            insert_trademark(conn, {
                "reg_number": f"DEMO-{abs(hash(name)) % 100000}",
                "app_number": "",
                "app_date": "",
                "reg_date": "2019-01-01",
                "name_text": name,
                "mktu_classes": classes,
                "status": status,
                "holder": holder,
                "normalized_name": normalize(name),
                "phonetic_key": phonetic_key(name),
            })
        conn.commit()
    print(f"Загружено {len(DEMO_TRADEMARKS)} демо-записей.")


if __name__ == "__main__":
    main()
