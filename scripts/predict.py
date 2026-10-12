#!/usr/bin/env python
"""Прогон документов и вопросов из манифеста, результат в results.json.

Пример:
  python scripts/predict.py --manifest data/documents.json --questions data/questions.json \
      --base data --input image --out results.json --reference data/reference_results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from dekanat_core import pipeline  # noqa: E402
from dekanat_core.config.schema import get_doc_type  # noqa: E402
from dekanat_core.models import NOT_FOUND  # noqa: E402


def empty_document(doc_id: str, doc_type: str, questions: list[dict]) -> dict:
    cfg = get_doc_type(doc_type)
    fields = {f.key: (False if f.is_mark else NOT_FOUND) for f in cfg.fields}
    missing = [f.key for f in cfg.fields]
    rules = sorted({f.rule for f in cfg.fields}, key=lambda r: tuple(map(int, r.split("."))))
    return {
        "document_id": doc_id, "document_type": doc_type, "fields": fields,
        "validation": {"status": "missing_fields", "missing_fields": missing, "sources": [f"rule:{r}" for r in rules]},
        "answers": [{"question_id": q["question_id"], "answerable": False, "value": None,
                     "answer": "Документ не удалось обработать. Обратитесь в деканат.", "sources": []} for q in questions],
    }


def run(args) -> dict:
    base = Path(args.base)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8")) if args.questions else []
    by_doc: dict[str, list[dict]] = {}
    for q in questions:
        by_doc.setdefault(q["document_id"], []).append(q)

    out_docs = []
    debug = []
    t_all = time.perf_counter()
    for i, entry in enumerate(manifest, 1):
        doc_id = entry["document_id"]
        doc_type = entry.get("document_type") or None
        rel = entry.get("pdf") if args.input == "pdf" else entry.get("image")
        if not rel:
            rel = entry.get("image") or entry.get("pdf")
        path = base / rel
        qs = by_doc.get(doc_id, [])
        t0 = time.perf_counter()
        try:
            result, ctx = pipeline.process_document(path.read_bytes(), path.name, doc_type if not args.auto_type else None,
                                                    first_page_only=True, preprocess=not args.no_preprocess)
            answers = [pipeline.answer_question(result, q["question"]).to_result(q["question_id"]) for q in qs]
            doc = {
                "document_id": doc_id,
                "document_type": result.doc_type,
                "fields": result.fields_plain(),
                "validation": {"status": result.validation.status, "missing_fields": list(result.validation.missing_fields),
                               "sources": list(result.validation.sources)},
                "answers": answers,
            }
            debug.append({"document_id": doc_id, "type_auto": result.doc_type, "type_conf": result.type_confidence,
                          "timings": result.timings, "ocr": result.quality.get("ocr"),
                          "marks": {k: v.confidence for k, v in result.fields.items() if v.kind == "mark"}})
        except Exception as exc:  # один плохой документ не должен ронять весь прогон
            logging.error("%s: %s\n%s", doc_id, exc, traceback.format_exc())
            doc = empty_document(doc_id, doc_type or "study_certificate", qs)
            debug.append({"document_id": doc_id, "error": str(exc)})
        out_docs.append(doc)
        print(f"[{i}/{len(manifest)}] {doc_id} {doc['document_type']} {doc['validation']['status']} "
              f"{time.perf_counter() - t0:.1f}s", flush=True)

    results = {"version": "1.0", "documents": out_docs}
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Сохранено {args.out}; всего {time.perf_counter() - t_all:.1f}s")
    if args.debug:
        Path(args.debug).write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")

    # проверяем по схеме организаторов, в ней только официальные типы, свои типы пропускаем
    try:
        import jsonschema

        schema = json.loads((Path(args.schema) if args.schema else ROOT / "data" / "results.schema.json").read_text(encoding="utf-8"))
        official = {opt["properties"]["document_type"]["const"] for opt in schema["properties"]["documents"]["items"]["oneOf"]}
        checked = [d for d in out_docs if d["document_type"] in official]
        skipped = len(out_docs) - len(checked)
        jsonschema.validate({"version": "1.0", "documents": checked}, schema)
        note = f" (пропущено документов пользовательских типов: {skipped})" if skipped else ""
        print(f"Схема results.schema.json: OK{note}")
    except Exception as exc:
        print(f"Схема: ОШИБКА {exc}")

    if args.reference:
        sys.path.insert(0, str(ROOT / "data"))
        import evaluate as ev  # type: ignore

        report = ev.evaluate(ev.load(args.reference), results)
        summary = {k: report[k] for k in ("field_accuracy_macro", "validation_exact_match", "question_exact_match")}
        print(json.dumps(summary, ensure_ascii=False))
        for e in report["errors"]:
            print("  ERR", json.dumps(e, ensure_ascii=False))
        if args.report:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", required=True)
    p.add_argument("--questions", default=None)
    p.add_argument("--base", default=".", help="каталог, относительно которого заданы пути в манифесте")
    p.add_argument("--input", choices=["image", "pdf"], default="image")
    p.add_argument("--out", default="results.json")
    p.add_argument("--reference", default=None, help="эталон для локальной оценки (evaluate.py)")
    p.add_argument("--report", default=None)
    p.add_argument("--debug", default=None, help="файл с отладочной информацией по документам")
    p.add_argument("--schema", default=None)
    p.add_argument("--auto-type", action="store_true", help="игнорировать тип из манифеста (проверка автоопределения)")
    p.add_argument("--no-preprocess", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    run(args)


if __name__ == "__main__":
    main()
