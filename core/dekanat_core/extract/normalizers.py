"""Нормализация значений полей (даты, курс, ФИО, номера, кавычки)."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

from rapidfuzz import fuzz, process

from ..models import NOT_FOUND
from ..settings import CONFIG_DIR

# латинские гомоглифы -> кириллица (для ФИО, групп, номеров)
_LAT2CYR = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р",
    "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к", "u": "и",
})
# похожие на цифры буквы -> цифры (только внутри числовых групп)
_LETTER2DIGIT = str.maketrans({"O": "0", "О": "0", "o": "0", "о": "0", "З": "3", "з": "3", "б": "6",
                               "I": "1", "l": "1", "|": "1", "S": "5", "s": "5", "B": "8", "В": "8",
                               "Z": "2", "q": "9", "g": "9"})
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-", "―": "-"})

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7,
    "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
_MONTH_KEYS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
               "октября", "ноября", "декабря"]
_MONTH_ABBR = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "июн": 6, "июл": 7, "авг": 8,
               "сен": 9, "сент": 9, "окт": 10, "ноя": 11, "дек": 12}

_LETTERS_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{3,}")


def clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize_quotes(s: str) -> str:
    s = s.replace("“", "«").replace("”", "»").replace("„", "«").replace("‟", "»")
    out, open_q = [], True
    for ch in s:
        if ch == '"':
            out.append("«" if open_q else "»")
            open_q = not open_q
        else:
            out.append(ch)
    return "".join(out)


def is_empty_value(s: str, pattern: str = r"^[\s_\-—–·.,:;|~]*$") -> bool:
    return not s or re.fullmatch(pattern, s) is not None


def fix_digits(s: str) -> str:
    return s.translate(_LETTER2DIGIT)


# ---------------- даты ----------------
def _month_from_word(word: str) -> Optional[int]:
    w = word.lower().strip(".,").translate(_LAT2CYR)
    if w in _MONTH_ABBR:
        return _MONTH_ABBR[w]
    for stem, num in MONTHS.items():
        if w.startswith(stem):
            return num
    if len(w) >= 3:
        best = process.extractOne(w, _MONTH_KEYS, scorer=fuzz.ratio)
        if best and best[1] >= 75:
            return _MONTH_KEYS.index(best[0]) + 1
    return None


def _valid(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _strip_noise_letters(s: str) -> str:
    """Убирает лишние буквы из числовой даты, например 01.о06.2026."""
    if not re.search(r"\d", s) or _WORD_RE.search(s):
        return s
    s = _LETTERS_RE.sub(lambda m: fix_digits(m.group(0)) if fix_digits(m.group(0)).isdigit() else "", s)
    # 01.006.2026 -> 01.06.2026
    s = re.sub(r"(?<=[./-])0(?=\d{2}(?!\d))", "", s)
    return s


def parse_date(raw: str) -> Optional[str]:
    """Парсит дату, возвращает ISO или None."""
    if not raw:
        return None
    s = clean_spaces(raw).translate(_DASHES)
    s = re.sub(r"\s*(года|год|г\.|г)\s*$", "", s).strip(" .,")
    s = _strip_noise_letters(s)
    # ISO
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", fix_digits(s))
    if m and int(m.group(2)) <= 12:
        r = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if r:
            return r
    # DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY
    m = re.search(r"([\dOОoоЗзбIl|SsBВZ]{1,2})\s*[./-]\s*([\dOОoоЗзбIl|]{1,2})\s*[./-]\s*([\dOОoоЗзбIl|SsBВZ]{2,4})", s)
    if m:
        d, mo, y = (fix_digits(g) for g in m.groups())
        if d.isdigit() and mo.isdigit() and y.isdigit():
            y_i = int(y)
            if y_i < 100:
                y_i += 2000
            r = _valid(y_i, int(mo), int(d))
            if r:
                return r
    # "1 сентября 2026", "01 сент. 2026", а еще слипшееся "05 июня2026"
    m = re.search(r"([\dOОoоЗзбIl|]{1,2})\s*([А-Яа-яA-Za-zё]{3,}?)\.?\s*([\dOОoоЗзбIl|SsBВZ]{4})(?!\d)", s)
    if m:
        d = fix_digits(m.group(1))
        y = fix_digits(m.group(3))
        mo = _month_from_word(m.group(2))
        if mo and d.isdigit() and y.isdigit():
            r = _valid(int(y), mo, int(d))
            if r:
                return r
    return None


def normalize_date(raw: str) -> str:
    r = parse_date(raw)
    return r if r else clean_spaces(raw)


# ---------------- курс ----------------
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
_WORDS = {"перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5, "шест": 6}


def normalize_int(raw: str) -> str:
    s = clean_spaces(raw).lower()
    m = re.search(r"\d+", fix_digits(s))
    if m:
        return str(int(m.group(0)))
    tok = s.replace("курс", "").strip(" -.")
    if tok in _ROMAN:
        return str(_ROMAN[tok])
    for stem, n in _WORDS.items():
        if tok.startswith(stem):
            return str(n)
    return clean_spaces(raw)


# ---------------- ФИО ----------------
# словарь имен для исправления опечаток OCR в отчестве (Левенштейн <= 1), фамилии не трогаем
def _load_names() -> dict:
    with open(CONFIG_DIR / "dictionaries" / "names.json", encoding="utf-8") as f:
        return json.load(f)


_NAMES = _load_names()
_MALE_NAMES: list[str] = _NAMES["male_names"]
_IRREGULAR: dict[str, list[str]] = _NAMES["irregular_patronymics"]
_SPECIAL: set[str] = set(_NAMES["special_patronymics"])


def _patronymics() -> set[str]:
    out: set[str] = set(_SPECIAL)
    for n in _MALE_NAMES:
        if n in _IRREGULAR:
            out.update(_IRREGULAR[n])
            continue
        if n.endswith(("й", "ь")):
            stem = n[:-1]
            out.update({stem + "евич", stem + "евна"})
            if n.endswith("ий"):
                out.update({n[:-2] + "ьевич", n[:-2] + "ьевна"})
        elif n.endswith("а"):
            continue  # Илья, Никита, Фома и т.п. лежат в _SPECIAL
        elif n[-1] in "ея":
            out.update({n + "евич", n + "евна"})
        else:
            out.update({n + "ович", n + "овна"})
    return out


_PATRONYMICS = _patronymics()
_PATRONYMIC_RE = re.compile(r"^[А-ЯЁ][а-яё]{2,}(ович|евич|ич|овна|евна|ична|инична)$")


def _lev1(a: str, b: str) -> bool:
    """Проверка, что расстояние Левенштейна <= 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(x != y for x, y in zip(a, b)) == 1
    s, l_ = (a, b) if la < lb else (b, a)
    i = j = 0
    skipped = False
    while i < len(s) and j < len(l_):
        if s[i] == l_[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


def _correct_token(tok: str, lexicon: set[str]) -> str:
    if tok in lexicon or len(tok) < 4:
        return tok
    cands = [w for w in lexicon if _lev1(tok, w)]
    return cands[0] if len(cands) == 1 else tok


def normalize_person_name(raw: str) -> str:
    s = clean_spaces(raw).translate(_LAT2CYR)
    s = re.sub(r"[^А-Яа-яЁё\-\s.]", "", s)
    # OCR иногда склеивает слова: ЖуковаПётр -> Жукова Пётр
    s = re.sub(r"([а-яё])([А-ЯЁ])", r"\1 \2", s)
    s = clean_spaces(s)
    parts = []
    for w in s.split(" "):
        if not w:
            continue
        parts.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    # отчество сверяем со словарем (Алексвевич, Андреевн и т.п.)
    # имена и фамилии не правим, там похожие варианты бывают реальными (Дина/Нина)
    if len(parts) == 3 and len(parts[2]) >= 6:
        parts[2] = _correct_token(parts[2], _PATRONYMICS)
    return " ".join(parts)


# ---------------- номера / группы ----------------
def normalize_doc_number(raw: str) -> str:
    s = clean_spaces(raw).translate(_DASHES).replace(" ", "").replace("№", "")
    m = re.match(r"^([A-Za-zА-Яа-я]{1,4})[-]?(\S+)$", s)
    if m:
        prefix = m.group(1).translate(_LAT2CYR).upper()
        num = fix_digits(m.group(2))
        return f"{prefix}-{num}"
    return s.upper()


def normalize_group(raw: str) -> str:
    s = clean_spaces(raw).translate(_DASHES).replace(" ", "")
    m = re.match(r"^([A-Za-zА-Яа-я]{1,6})[-]?(.+)$", s)
    if m:
        prefix = m.group(1).translate(_LAT2CYR).upper()
        rest = fix_digits(m.group(2)).replace("--", "-")
        return f"{prefix}-{rest}"
    return s.upper()


# ---------------- enum ----------------
def normalize_enum(raw: str, values: list[str], threshold: int = 80) -> str:
    s = clean_spaces(raw).lower().replace("ё", "е")
    if not values:
        return s
    cands = {v.lower().replace("ё", "е"): v for v in values}
    if s in cands:
        return cands[s]
    best = process.extractOne(s, list(cands), scorer=fuzz.WRatio)
    if best and best[1] >= threshold:
        return cands[best[0]]
    return clean_spaces(raw)


# ---------------- текст ----------------
_CODE_TOKEN_RE = re.compile(r"^[\dоОoOзЗбIl|.]+$")


def _fix_code_tokens(s: str) -> str:
    """Чистит буквы в числовых кодах: 09.о3.01 -> 09.03.01."""
    out = []
    for tok in s.split(" "):
        if _CODE_TOKEN_RE.match(tok) and sum(ch.isdigit() for ch in tok) >= 2:
            tok = fix_digits(tok)
        out.append(tok)
    return " ".join(out)


def normalize_text(raw: str) -> str:
    s = normalize_quotes(clean_spaces(raw)).strip(" .")
    s = _fix_code_tokens(s)
    # OCR склеивает кавычку со словом и теряет закрывающую
    s = re.sub(r"(\w)«", r"\1 «", s)
    s = re.sub(r"»(\w)", r"» \1", s)
    if s.count("«") > s.count("»"):
        s = s + "»"
    if s.count("»") > s.count("«"):
        # потеряна открывающая кавычка
        s2 = re.sub(r"([а-яёa-z])([А-ЯЁA-Z][^»]*»)", r"\1 «\2", s, count=1)
        s = s2 if s2 != s else re.sub(r"(\s|^)([^\s»]+»)", r"\1«\2", s, count=1)
    return clean_spaces(s)


def normalize(kind: str, raw: str, *, values: list[str] | None = None) -> str:
    if is_empty_value(raw):
        return NOT_FOUND
    if kind == "date":
        return normalize_date(raw)
    if kind == "int":
        return normalize_int(raw)
    if kind == "person_name":
        return normalize_person_name(raw)
    if kind == "doc_number":
        return normalize_doc_number(raw)
    if kind == "group":
        return normalize_group(raw)
    if kind == "enum":
        return normalize_enum(raw, values or [])
    return normalize_text(raw)
