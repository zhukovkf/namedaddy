"""
Ядро сравнения названий и оценки риска.

ВАЖНО: это эвристическая модель, а не юридическая экспертиза.
Реальная оценка "сходства до степени смешения" по ст. 1483 ГК РФ
учитывает семантику, визуальное восприятие логотипа, известность бренда,
однородность товаров и практику Роспатента/Палаты по патентным спорам —
всё это выходит за рамки автоматического текстового сравнения.
Итоговый процент — ориентир для принятия решения, не гарантия.
"""

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

# --- Нормализация -----------------------------------------------------------

# Визуально неотличимые (или почти) кириллица/латиница — частый приём
# в "обходных" названиях (BAHK / БАНК, PRAVDA / PRAVDA и т.п.)
_LOOKALIKE = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к",
    "m": "м", "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
    "A": "а", "B": "в", "C": "с", "E": "е", "H": "н", "K": "к",
    "M": "м", "O": "о", "P": "р", "T": "т", "X": "х", "Y": "у",
})

_NON_ALNUM = re.compile(r"[^0-9а-яё]+")

# Частотные описательные/родовые элементы в названиях российских брендов —
# сами по себе слабо различительны и не должны сильно поднимать риск,
# если совпадает только этот кусок, а не оригинальная часть.
STOPWORDS = {
    "трейд", "трейдинг", "групп", "group", "плюс", "сервис", "маркет",
    "стандарт", "рус", "русь", "холдинг", "компания", "торговый", "дом",
    "про", "плюс", "центр", "оптима", "премиум", "престиж", "стиль",
    "юг", "запад", "восток", "север", "агро", "тех", "техно", "строй",
}


def normalize(text: str) -> str:
    text = text.strip().lower().translate(_LOOKALIKE)
    text = text.replace("ё", "е")
    text = _NON_ALNUM.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def phonetic_key(text: str) -> str:
    """
    Упрощённый фонетический ключ для русских слов: убирает мягкий/твёрдый
    знак, схлопывает часто чередующиеся безударные гласные и удвоенные
    согласные. Не претендует на лингвистическую строгость — цель дать
    совпадение для "на слух похожих" вариантов (Кока-Кола / Кока Кола,
    Малако / Молоко и т.п.)
    """
    t = normalize(text).replace(" ", "")
    t = t.replace("ъ", "").replace("ь", "")
    # безударные гласные, которые часто путают на письме/слух
    t = re.sub(r"[оа]", "a", t)
    t = re.sub(r"[еиэ]", "и", t)
    t = re.sub(r"(.)\1+", r"\1", t)  # удвоенные буквы -> одна
    # частые оглушения/озвончения согласных на конце и в стыках
    pairs = {"б": "п", "в": "ф", "г": "к", "д": "т", "ж": "ш", "з": "с"}
    t = "".join(pairs.get(ch, ch) for ch in t)
    return t


def has_common_stopword(a: str, b: str) -> bool:
    a_tokens = set(normalize(a).split())
    b_tokens = set(normalize(b).split())
    common = a_tokens & b_tokens
    return bool(common) and common.issubset(STOPWORDS)


# --- Сравнение классов МКТУ --------------------------------------------------

def parse_classes(raw: str) -> set:
    if not raw:
        return set()
    return {c.strip() for c in re.split(r"[,\s;]+", raw) if c.strip().isdigit()}


def class_overlap(classes_a: set, classes_b: set) -> float:
    if not classes_a or not classes_b:
        return 0.0
    inter = classes_a & classes_b
    union = classes_a | classes_b
    return len(inter) / len(union) if union else 0.0


# --- Композитная оценка -------------------------------------------------------

STATUS_WEIGHT = {
    "active": 1.0,
    "pending": 0.7,   # заявка на рассмотрении — тоже противопоставляется
    "expired": 0.3,   # срок действия истёк, но могло быть продление/переход
    "terminated": 0.15,
}


@dataclass
class Match:
    name: str
    reg_number: str
    mktu_classes: str
    status: str
    holder: str
    text_sim: float
    phonetic_sim: float
    class_sim: float
    conflict_score: float  # 0..1


@dataclass
class Assessment:
    query: str
    matches: list = field(default_factory=list)
    registration_probability: float = 0.0  # 0..100
    risk_label: str = ""


def score_candidate(query_name: str, query_classes: set, row) -> Match:
    q_norm = normalize(query_name)
    q_phon = phonetic_key(query_name)

    text_sim = fuzz.token_sort_ratio(q_norm, row["normalized_name"]) / 100.0
    phon_sim = fuzz.ratio(q_phon, row["phonetic_key"]) / 100.0

    cand_classes = parse_classes(row["mktu_classes"])
    cls_sim = class_overlap(query_classes, cand_classes) if query_classes else (
        1.0 if cand_classes else 0.0  # если классы не заданы — не наказываем/не поощряем
    )

    weight = STATUS_WEIGHT.get(row["status"], 0.5)

    base = 0.55 * text_sim + 0.25 * phon_sim + (0.20 * cls_sim if query_classes else 0.0)
    if has_common_stopword(query_name, row["name_text"]):
        base *= 0.6  # совпадение только по общеупотребимому слову — сильно ослабляем

    conflict = base * weight

    return Match(
        name=row["name_text"],
        reg_number=row["reg_number"],
        mktu_classes=row["mktu_classes"],
        status=row["status"],
        holder=row["holder"] or "—",
        text_sim=text_sim,
        phonetic_sim=phon_sim,
        class_sim=cls_sim,
        conflict_score=conflict,
    )


MIN_RELEVANT_SCORE = 0.45


def assess(query_name: str, query_classes_raw: str, candidate_rows) -> Assessment:
    query_classes = parse_classes(query_classes_raw)
    scored = [score_candidate(query_name, query_classes, r) for r in candidate_rows]
    relevant = sorted(
        (m for m in scored if m.conflict_score >= MIN_RELEVANT_SCORE or m.text_sim >= 0.9),
        key=lambda m: m.conflict_score,
        reverse=True,
    )[:10]

    if not relevant:
        probability = 90.0
    else:
        top = relevant[0].conflict_score
        # усиливающий эффект нескольких заметных конфликтов
        extra = sum(m.conflict_score for m in relevant[1:3]) * 0.15
        risk = min(1.0, top + extra)
        probability = round((1 - risk) * 90 + 5, 1)  # держим в диапазоне 5..95

    if probability >= 70:
        label = "хорошие шансы"
    elif probability >= 40:
        label = "средний риск — нужна доработка названия и/или юридическая проверка"
    else:
        label = "высокий риск отказа / противопоставления"

    return Assessment(
        query=query_name,
        matches=relevant,
        registration_probability=probability,
        risk_label=label,
    )
