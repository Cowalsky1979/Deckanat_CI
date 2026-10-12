"""Вопросно-ответный модуль: перефразировки, ловушки, инварианты ответа."""
import pytest

from dekanat_core.config.schema import get_doc_type
from dekanat_core.models import NOT_FOUND, DocumentResult, FieldValue
from dekanat_core.qa.answer_builder import answer_question, check_document
from dekanat_core.qa.intents import classify_question
from dekanat_core.rules.validator import validate

SC = get_doc_type("study_certificate")
AL = get_doc_type("academic_leave_application")
IC = get_doc_type("internship_certificate")


def make_result(cfg, values: dict, marks: dict | None = None) -> DocumentResult:
    fields = {}
    for spec in cfg.fields:
        if spec.is_mark:
            present = (marks or {}).get(spec.key, True)
            fields[spec.key] = FieldValue(spec.key, spec.label, present, kind="mark", found=present, bbox=(0, 0, 10, 10))
        else:
            v = values.get(spec.key, "значение")
            fields[spec.key] = FieldValue(spec.key, spec.label, v, found=v != NOT_FOUND, bbox=(0, 0, 10, 10))
    return DocumentResult(cfg.key, cfg.title, 1.0, False, fields, validate(cfg, fields), "", [], (100, 100))


@pytest.mark.parametrize("q", [
    "Кто принимает окончательное решение о принятии документа?",
    "Кто принимает решение?",
    "кто решает, примут документ или нет",
    "Документ принят?",
    "Примут ли мою справку?",
])
def test_decision(q):
    r = make_result(SC, {})
    a = answer_question(r, SC, q)
    assert a.answerable and a.value == "сотрудник деканата" and a.sources == ["rule:1.3"]


@pytest.mark.parametrize("q", [
    "Содержит ли документ все обязательные сведения по Положению?",
    "Всё ли в порядке с документом?",
    "Чего не хватает в справке?",
    "Проверь документ",
    "Хватит ли этой справки для перевода на 2 курс?",
    "Подходит ли документ?",
    "Правильно ли заполнено заявление?",
])
def test_completeness(q):
    r = make_result(SC, {"issue_date": NOT_FOUND})
    a = answer_question(r, SC, q)
    assert a.answerable and a.value == "missing_fields" and a.sources == ["rule:3.1"]
    assert "дата выдачи" in a.answer
    ok = answer_question(make_result(SC, {}), SC, q)
    assert ok.value == "document_ok" and ok.sources == ["rule:3.1", "rule:3.2", "rule:3.3"]


def test_completeness_transfer_mentions_3_5():
    a = answer_question(make_result(SC, {}), SC, "Хватит ли справки для перевода на второй курс?")
    assert a.value == "document_ok" and "3.5" in a.answer and a.sources == ["rule:3.1", "rule:3.2", "rule:3.3"]


def test_check_button():
    a = check_document(make_result(AL, {}), AL)
    assert a.value == "document_ok" and a.sources == ["rule:4.1", "rule:4.2"]


@pytest.mark.parametrize("cfg,q,key", [
    (SC, "Укажи значение поля «ФИО студента».", "student_name"),
    (SC, 'Укажи значение поля "Дата выдачи".', "issue_date"),
    (SC, "Какова дата выдачи?", "issue_date"),
    (SC, "Когда выдана справка?", "issue_date"),
    (SC, "Какая форма обучения?", "study_form"),
    (SC, "Укажи значение поля «Окончание периода обучения».", "study_end"),
    (SC, "Какой номер справки?", "document_number"),
    (SC, "Какой вуз выдал справку?", "university"),
    (SC, "Как зовут студента?", "student_name"),
    (AL, "Укажи значение поля «Учебная группа».", "group"),
    (AL, "На каком курсе учится студент?", "course"),
    (AL, "Укажи значение поля «Причина отпуска».", "leave_reason"),
    (AL, "Когда начинается отпуск?", "leave_start"),
    (AL, "Укажи значение поля «Дата окончания отпуска».", "leave_end"),
    (AL, "Укажи значение поля «Дата заявления».", "application_date"),
    (IC, "Укажи значение поля «ФИО руководителя практики».", "supervisor_name"),
    (IC, "Кто руководитель практики?", "supervisor_name"),
    (IC, "Какая оценка?", "grade"),
    (IC, "Укажи значение поля «Название организации».", "organization"),
    (IC, "Где проходила практика?", "organization"),
    (IC, "Укажи значение поля «Дата начала практики».", "internship_start"),
    (IC, "Укажи значение поля «Дата окончания практики».", "internship_end"),
])
def test_field_questions(cfg, q, key):
    r = make_result(cfg, {key: "2026-01-01" if "date" in key or key.endswith(("start", "end")) else "Тест"})
    a = answer_question(r, cfg, q)
    assert a.answerable and a.sources == [f"field:{key}"] and a.value == r.fields[key].value and a.field_key == key


def test_field_missing():
    r = make_result(SC, {"issue_date": NOT_FOUND})
    a = answer_question(r, SC, "Укажи значение поля «Дата выдачи».")
    assert not a.answerable and a.value is None and a.sources == [] and "не найдено" in a.answer


def test_mark_questions():
    r = make_result(SC, {}, {"seal_present": False})
    a = answer_question(r, SC, "Есть ли печать?")
    assert a.answerable and a.value == "нет" and set(a.sources) == {"field:seal_present", "rule:3.3"}
    b = answer_question(r, SC, "Есть ли подпись?")
    assert b.value == "да" and "field:signature_present" in b.sources
    c = answer_question(make_result(AL, {}), AL, "Нужна ли печать на заявлении?")
    assert c.answerable and c.sources == ["rule:4.3"]


@pytest.mark.parametrize("q", [
    "Какова стоимость обучения за следующий семестр?",
    "Какой размер стипендии положен студенту?",
    "Какой срок рассмотрения документа деканатом?",
    "По какому номеру телефона можно связаться с деканатом?",
    "В каком кабинете принимают оригиналы документов?",
    "Сколько стоит обучение?",
    "Когда будет пересдача?",
    "Какой адрес у деканата?",
    "Дадут ли общежитие?",
])
def test_no_info(q):
    for cfg in (SC, AL, IC):
        a = answer_question(make_result(cfg, {}), cfg, q)
        assert not a.answerable and a.value is None and a.sources == [] and "нет информации" in a.answer


@pytest.mark.parametrize("q,rule", [
    ("На какой курс меня переведут?", "3.5"),
    ("Перезачтут ли дисциплины?", "3.5"),
    ("Какая максимальная длительность отпуска?", "4.4"),
    ("Как выставляется оценка за практику?", "5.5"),
])
def test_not_established(q, rule):
    a = answer_question(make_result(SC, {}), SC, q)
    assert not a.answerable and a.sources == [] and rule in a.answer


@pytest.mark.parametrize("q,rule", [
    ("Проверяется ли подлинность подписи?", "2.3"),
    ("В каком формате даты?", "2.5"),
    ("Какие поля обязательны?", "3.1"),
    ("Сколько страниц нужно?", "3.4"),
])
def test_faq(q, rule):
    a = answer_question(make_result(SC, {}), SC, q)
    assert a.answerable and f"rule:{rule}" in a.sources and a.value


def test_invariants_on_many_questions():
    """sources пусты <=> answerable False; answer непустой."""
    qs = ["привет", "?", "что ты умеешь", "Укажи значение поля «Несуществующее поле».", "дата", "печать",
          "когда", "срок обучения", "сколько длится практика", "кто подписал справку", "выдана ли справка в 2026 году"]
    for cfg in (SC, AL, IC):
        for q in qs:
            a = answer_question(make_result(cfg, {}), cfg, q)
            assert bool(a.sources) == a.answerable, (cfg.key, q, a)
            assert a.answer.strip()
            if not a.answerable:
                assert a.value is None


def test_custom_type_questions():
    tr = get_doc_type("transfer_application")
    r = make_result(tr, {"current_university": "Учебный университет «Север»", "target_program": "09.03.04 Программная инженерия"})
    a = answer_question(r, tr, "Укажи значение поля «Текущий вуз».")
    assert a.value == "Учебный университет «Север»" and a.sources == ["field:current_university"]
    b = answer_question(r, tr, "На какое направление переводится студент?")
    assert b.sources == ["field:target_program"]
    c = answer_question(r, tr, "Нужна ли печать на заявлении?")
    assert c.answerable and c.sources == ["rule:4.3"]
    d = answer_question(r, tr, "Содержит ли документ все обязательные сведения?")
    assert d.value == "document_ok" and d.sources == ["rule:4.1", "rule:4.2"]


def test_classify_returns_intent():
    assert classify_question("Кто принимает решение?", SC).kind == "decision"
    assert classify_question("Какова стоимость обучения?", SC).kind == "no_info"
