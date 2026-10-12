import pytest

from dekanat_core.extract import normalizers as nz
from dekanat_core.models import NOT_FOUND


@pytest.mark.parametrize("raw,expected", [
    ("01.09.2023", "2023-09-01"),
    ("1.9.2023", "2023-09-01"),
    ("01/09/2023", "2023-09-01"),
    ("2026-07-15", "2026-07-15"),
    ("1 сентября 2022 года", "2022-09-01"),
    ("31 августа 2026 года", "2026-08-31"),
    ("4 октября 2026 г.", "2026-10-04"),
    ("15 июля 2026", "2026-07-15"),
    ("01 сент. 2026", "2026-09-01"),
    ("1 сентяоря 2026 года", "2026-09-01"),   # OCR-опечатка в месяце
    ("01.о06.2026", "2026-06-01"),            # OCR-буква внутри числовой даты
    ("O1.09.2O23", "2023-09-01"),             # латинская O вместо нуля
    ("31.02.2026", None),                      # несуществующая дата
    ("сентябрь 2026", None),
    ("", None),
])
def test_parse_date(raw, expected):
    assert nz.parse_date(raw) == expected


@pytest.mark.parametrize("raw,expected", [("4", "4"), ("4 курс", "4"), ("IV", "4"), ("третий", "3"), ("З", "3")])
def test_course(raw, expected):
    assert nz.normalize_int(raw) == expected


def test_person_name_homoglyphs():
    assert nz.normalize_person_name("Пaвлов Фёдор Дмитриевич") == "Павлов Фёдор Дмитриевич"
    assert nz.normalize_person_name("  иванов   борис николаевич ") == "Иванов Борис Николаевич"
    assert nz.normalize_person_name("ЖуковаПётр Андреевич") == "Жукова Пётр Андреевич"
    # OCR-опечатки в имени/отчестве исправляются по словарю, фамилия не трогается
    assert nz.normalize_person_name("Шестаков Олег Алексвевич") == "Шестаков Олег Алексеевич"
    assert nz.normalize_person_name("Ильина Елена Андреевн") == "Ильина Елена Андреевна"
    assert nz.normalize_person_name("Кузнецова Мария Сергеевна") == "Кузнецова Мария Сергеевна"
    assert nz.normalize_person_name("Шестакав Олег Алексеевич") == "Шестакав Олег Алексеевич"  # фамилия как есть
    # правильные отчества, включая нерегулярные, не ломаются
    for ok in ["Захаров Виктор Михайлович", "Мельников Фёдор Михайлович", "Иванов Пётр Петрович", "Орлов Лев Львович",
               "Крылова Анна Ильинична", "Сидоров Иван Данилович", "Титова Ольга Яковлевна", "Жуков Олег Никитич"]:
        assert nz.normalize_person_name(ok) == ok
    # имена не «исправляются»
    assert nz.normalize_person_name("Смирнова Дина Олеговна") == "Смирнова Дина Олеговна"
    assert nz.normalize_person_name("Александров Артём Игоревич") == "Александров Артём Игоревич"
    assert nz.normalize_person_name("Петрова-Иванова Анна Олеговна") == "Петрова-Иванова Анна Олеговна"


@pytest.mark.parametrize("raw,expected", [("Об-1001", "ОБ-1001"), ("OБ-1001", "ОБ-1001"), ("ПР–2027", "ПР-2027"), ("№ ПР-2027", "ПР-2027")])
def test_doc_number(raw, expected):
    assert nz.normalize_doc_number(raw) == expected


@pytest.mark.parametrize("raw,expected", [("ЭК-24-2", "ЭК-24-2"), ("ИВТ-23-4", "ИВТ-23-4"), ("ЭK-24-2", "ЭК-24-2")])
def test_group(raw, expected):
    assert nz.normalize_group(raw) == expected


def test_enum():
    vals = ["очная", "очно-заочная", "заочная"]
    assert nz.normalize_enum("очно-заочная", vals) == "очно-заочная"
    assert nz.normalize_enum("очная", vals) == "очная"
    assert nz.normalize_enum("Очнo-заочная", vals) == "очно-заочная"


@pytest.mark.parametrize("raw,expected", [
    ("Учебная организация«Спектр»", "Учебная организация «Спектр»"),
    ("Учебная организация«Спектр", "Учебная организация «Спектр»"),
    ("Учебная организацияСпектр»", "Учебная организация «Спектр»"),
    ('Учебный университет "Меридиан"', "Учебный университет «Меридиан»"),
    ("09.о3.01 Информатика и вычислительная техника", "09.03.01 Информатика и вычислительная техника"),
    ("по семейным обстоятельствам", "по семейным обстоятельствам"),
])
def test_text(raw, expected):
    assert nz.normalize_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "____", "— ", "_ _ _", "..."])
def test_empty_values(raw):
    assert nz.normalize("text", raw) == NOT_FOUND
    assert nz.normalize("date", raw) == NOT_FOUND
