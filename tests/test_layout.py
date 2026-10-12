import pytest

from dekanat_core.layout.lines import is_junk_line


@pytest.mark.parametrize("text,conf", [
    ("СПРАВКА О ПРАКТИКЕ", 0.99),
    ("ФИО студента: Шестаков Олег Алексеевич", 0.98),
    ("Дата начала практики: 1 июня 2026 года", 0.97),
    ("Номер справки: ПР-2024", 0.96),
    ("38.03.01 Экономика", 0.95),
    ("Идентификатор образца: open-001", 0.9),
    ("М.П.", 0.83),
    ("01.09.2026", 0.9),
    ("Учебная организация «Спектр»", 0.95),
])
def test_keeps_document_lines(text, conf):
    assert not is_junk_line(text, conf)


@pytest.mark.parametrize("text,conf", [
    (". 5 нано Runsidiowy lak del al OE O bast eet Pinna nent a Г = sour a = craves 99 ОА ^ УФ в реет.", 0.6),
    ("-conA - VIODOWN Е наъончом — фола t i ых 20008 Хх > oe bee ae “ 3DHN0 001 e1a0n чая —1 en", 0.5),
    ("□ □4 NdLMO MJMX K3n V/ D.0 ded .udo edso xdg", 0.7),
    ("2", 0.9),
    ("MAKET", 1.0),
    ("~~~ ***", 0.9),
    ("Хорошая строка, но уверенность низкая", 0.3),
])
def test_drops_junk_lines(text, conf):
    assert is_junk_line(text, conf)
