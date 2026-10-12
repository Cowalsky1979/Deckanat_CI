import itertools

import pytest

from dekanat_core.config.schema import get_doc_type, load_doc_types
from dekanat_core.models import NOT_FOUND, FieldValue
from dekanat_core.rules.positions import load_positions
from dekanat_core.rules.validator import validate


def test_positions_parsed():
    p = load_positions()
    assert "1.3" in p.rules and "6.5" in p.rules
    assert "сотрудник деканата" in p.text("1.3")
    assert p.rules["3.1"].section == "3"
    assert len(p.rules) >= 25


def test_doc_types_loaded():
    types = load_doc_types()
    assert set(types) >= {"study_certificate", "academic_leave_application", "internship_certificate"}
    sc = types["study_certificate"]
    assert [f.key for f in sc.fields] == ["student_name", "university", "program", "study_form", "study_start",
                                          "study_end", "document_number", "issue_date", "signature_present", "seal_present"]
    assert types["academic_leave_application"].not_required == {"seal": "4.3"}


def test_custom_type_from_config():
    """Пользовательский тип добавляется YAML-файлом без кода (config/doc_types/transfer_application.yaml)."""
    cfg = load_doc_types()["transfer_application"]
    assert cfg.title == "Заявление о переводе"
    assert [f.key for f in cfg.fields] == ["student_name", "current_university", "target_program", "application_date", "signature_present"]
    assert cfg.complete_message_rules == ["4.1", "4.2"] and cfg.not_required == {"seal": "4.3"}
    v = validate(cfg, _fields(cfg, set()))
    assert v.status == "document_ok" and v.sources == ["rule:4.1", "rule:4.2"]
    v = validate(cfg, _fields(cfg, {"application_date", "signature_present"}))
    assert set(v.missing_fields) == {"application_date", "signature_present"} and v.sources == ["rule:4.1", "rule:4.2"]


def _fields(cfg, missing: set[str]) -> dict[str, FieldValue]:
    out = {}
    for spec in cfg.fields:
        if spec.is_mark:
            out[spec.key] = FieldValue(spec.key, spec.label, spec.key not in missing, kind="mark", found=spec.key not in missing)
        else:
            v = NOT_FOUND if spec.key in missing else "x"
            out[spec.key] = FieldValue(spec.key, spec.label, v, found=v != NOT_FOUND)
    return out


def test_validate_complete():
    cfg = get_doc_type("study_certificate")
    v = validate(cfg, _fields(cfg, set()))
    assert v.status == "document_ok" and v.missing_fields == [] and v.sources == ["rule:3.1", "rule:3.2", "rule:3.3"]
    assert "3.1, 3.2, 3.3" in v.message and "сотрудник деканата" in v.message


@pytest.mark.parametrize("missing,sources", [
    ({"issue_date"}, ["rule:3.1"]),
    ({"signature_present"}, ["rule:3.2"]),
    ({"seal_present"}, ["rule:3.3"]),
    ({"student_name", "document_number"}, ["rule:3.1"]),
    ({"signature_present", "seal_present"}, ["rule:3.2", "rule:3.3"]),
    ({"issue_date", "seal_present"}, ["rule:3.1", "rule:3.3"]),
])
def test_validate_missing_study(missing, sources):
    cfg = get_doc_type("study_certificate")
    v = validate(cfg, _fields(cfg, missing))
    assert v.status == "missing_fields" and set(v.missing_fields) == missing and v.sources == sources


def test_validate_leave_and_internship():
    al = get_doc_type("academic_leave_application")
    assert validate(al, _fields(al, set())).sources == ["rule:4.1", "rule:4.2"]
    assert validate(al, _fields(al, {"group", "course"})).sources == ["rule:4.1"]
    assert validate(al, _fields(al, {"signature_present"})).sources == ["rule:4.2"]
    ic = get_doc_type("internship_certificate")
    assert validate(ic, _fields(ic, set())).sources == ["rule:5.1", "rule:5.2", "rule:5.3"]
    assert validate(ic, _fields(ic, {"supervisor_name", "grade"})).sources == ["rule:5.1"]


def test_validate_all_pair_combinations_consistent():
    """Для любой пары пропусков источники = пункты этих полей."""
    cfg = get_doc_type("internship_certificate")
    for a, b in itertools.combinations([f.key for f in cfg.fields], 2):
        v = validate(cfg, _fields(cfg, {a, b}))
        assert set(v.sources) == {f"rule:{cfg.field_map[a].rule}", f"rule:{cfg.field_map[b].rule}"}
