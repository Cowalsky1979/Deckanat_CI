"""Сборка ответа: value, sources и текст для пользователя."""
from __future__ import annotations

from ..config.schema import DocTypeConfig
from ..models import MISSING_EMPTY, MISSING_LABEL, NOT_FOUND, Answer, DocumentResult
from ..rules.positions import load_positions
from .intents import Intent, classify_question

NO_INFO_TEXT = "В документе и в Положении нет информации для ответа на этот вопрос. Обратитесь в деканат."
DECISION_VALUE = "сотрудник деканата"
COMPLETENESS_QUESTION = "Содержит ли документ все обязательные сведения по Положению?"


def _rules_phrase(rule_ids: list[str]) -> str:
    ids = [r.replace("rule:", "") for r in rule_ids]
    return ("пункт " if len(ids) == 1 else "пункты ") + ", ".join(ids)


def answer_question(result: DocumentResult, cfg: DocTypeConfig, question: str) -> Answer:
    intent = classify_question(question, cfg)
    return build_answer(result, cfg, question, intent)


def build_answer(result: DocumentResult, cfg: DocTypeConfig, question: str, intent: Intent) -> Answer:
    positions = load_positions()

    if intent.kind == "decision":
        return Answer(question, True, DECISION_VALUE,
                      "Окончательное решение принимает сотрудник деканата, пункт 1.3 Положения. "
                      "Сервис выполняет только предварительную проверку.",
                      ["rule:1.3"], intent="decision")

    if intent.kind == "completeness":
        v = result.validation
        text = v.message
        q = question.lower()
        extra = []
        if any(w in q for w in ("перевод", "перевест", "курс")) and cfg.key == "study_certificate":
            extra.append("Условия перевода и курс перевода настоящим Положением не установлены (пункт 3.5).")
        if any(w in q for w in ("отпуск", "причин")) and cfg.key == "academic_leave_application" and "достаточно" in q:
            extra.append("Допустимость причины и длительность отпуска Положением не оцениваются (пункт 4.4).")
        if any(w in q for w in ("зачт", "зачёт", "зачет")) and cfg.key == "internship_certificate":
            extra.append("Порядок зачёта практики настоящим Положением не установлен (пункт 5.5).")
        if extra:
            text = text + " " + " ".join(extra)
        return Answer(question, True, v.status, text, list(v.sources), intent="completeness")

    if intent.kind == "field":
        spec = cfg.field_map[intent.field_key]
        fv = result.fields.get(spec.key)
        if spec.is_mark:
            present = bool(fv and fv.value is True)
            what = "обнаружена" if present else "не обнаружена"
            rule = positions.get(spec.rule)
            text = (f"{spec.label}: {what}. Проверяется только наличие графического элемента, "
                    f"подлинность не проверяется (пункт 2.3). Требование: пункт {spec.rule} Положения.")
            return Answer(question, True, "да" if present else "нет", text,
                          [f"field:{spec.key}", f"rule:{spec.rule}"], intent="field", field_key=spec.key)
        if fv is None or fv.value == NOT_FOUND:
            reason = fv.missing_reason if fv is not None else None
            if reason == MISSING_EMPTY:
                why = (f"Поле «{spec.label}» в документе не заполнено: метка поля найдена, а значение после неё пустое. "
                       "Значение не домысливается (пункт 2.2 Положения).")
            elif reason == MISSING_LABEL:
                why = (f"Метку поля «{spec.label}» не удалось распознать на снимке, поэтому значение не найдено. "
                       "Возможно, снимок нечёткий: попробуйте переснять документ или загрузить скан.")
            else:
                why = f"Поле «{spec.label}» не найдено в документе."
            return Answer(question, False, None, f"{why} Обратитесь в деканат.",
                          [], intent="field_missing", field_key=spec.key)
        text = f"{spec.label}: {fv.value}."
        if fv.is_manual:
            ocr = fv.ocr_value if fv.ocr_value not in (None, NOT_FOUND) else "не найдено"
            text += f" Значение исправлено вручную, OCR распознал: «{ocr}»."
        return Answer(question, True, str(fv.value), text, [f"field:{spec.key}"], intent="field", field_key=spec.key)

    if intent.kind == "faq":
        faq = intent.faq or {}
        rule = faq.get("rule")
        if faq.get("id", "").startswith("not_required_"):
            mark = faq["id"].split("_", 2)[2]
            name = "Печать вуза" if mark == "seal" else "Подпись сотрудника деканата"
            text = (f"{name} для предварительной проверки этого типа документа не требуется "
                    f"(пункт {rule} Положения).")
            return Answer(question, True, "не требуется", text, [f"rule:{rule}"], intent="faq")
        sources = [f"rule:{rule}"] + [f"rule:{r}" for r in faq.get("extra_rules", [])]
        return Answer(question, True, faq.get("value"), faq.get("answer") or positions.text(rule), sources, intent="faq")

    if intent.kind == "not_established":
        note = intent.note or {}
        text = NO_INFO_TEXT
        if note.get("note"):
            text = f"{note['note']} {NO_INFO_TEXT}"
        return Answer(question, False, None, text, [], intent="not_established")

    return Answer(question, False, None, NO_INFO_TEXT, [], intent="no_info")


def check_document(result: DocumentResult, cfg: DocTypeConfig) -> Answer:
    """Проверка без вопроса (п. 6.5)."""
    return answer_question(result, cfg, COMPLETENESS_QUESTION)
