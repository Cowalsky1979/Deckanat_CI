"""Проверка комплектности документа (п. 2.6, 6.1, 6.2)."""
from __future__ import annotations

from ..config.schema import DocTypeConfig
from ..models import NOT_FOUND, FieldValue, Validation


def _sort_rules(rules: set[str]) -> list[str]:
    return sorted(rules, key=lambda r: tuple(int(x) for x in r.split(".")))


def human_label(label: str) -> str:
    """Метка с маленькой буквы для текста ответа."""
    return label[:1].lower() + label[1:] if not label.isupper() and not label.startswith("ФИО") else label


def validate(cfg: DocTypeConfig, fields: dict[str, FieldValue]) -> Validation:
    missing: list[str] = []
    for spec in cfg.fields:
        fv = fields.get(spec.key)
        if fv is None:
            missing.append(spec.key)
            continue
        if spec.is_mark:
            if fv.value is not True:
                missing.append(spec.key)
        elif not isinstance(fv.value, str) or fv.value == NOT_FOUND:
            missing.append(spec.key)

    if not missing:
        rules = _sort_rules(set(cfg.complete_message_rules))
        msg = (f"Документ содержит все обязательные сведения по пунктам {', '.join(rules)} Положения. "
               "Окончательное решение примет сотрудник деканата.")
        return Validation(status="document_ok", missing_fields=[], sources=[f"rule:{r}" for r in rules], message=msg)

    rules = _sort_rules({cfg.field_map[k].rule for k in missing})
    labels = ", ".join(human_label(cfg.field_map[k].label) for k in missing)
    word = "пункт" if len(rules) == 1 else "пункты"
    msg = (f"Не хватает обязательных сведений: {labels}. "
           f"Основание: {word} {', '.join(rules)} Положения. Окончательное решение примет сотрудник деканата.")
    return Validation(status="missing_fields", missing_fields=missing, sources=[f"rule:{r}" for r in rules], message=msg)
