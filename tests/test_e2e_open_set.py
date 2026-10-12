"""E2E: полный конвейер на открытом наборе должен давать 1.0 по всем метрикам (медленно: OCR)."""
import json
import sys

import pytest

from dekanat_core import pipeline

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def reference(data_dir):
    return {d["document_id"]: d for d in json.loads((data_dir / "reference_results.json").read_text(encoding="utf-8"))["documents"]}


@pytest.fixture(scope="module")
def questions(data_dir):
    by_doc = {}
    for q in json.loads((data_dir / "questions.json").read_text(encoding="utf-8")):
        by_doc.setdefault(q["document_id"], []).append(q)
    return by_doc


@pytest.mark.parametrize("kind", ["image", "pdf"])
def test_open_set_metrics(data_dir, reference, questions, kind):
    sys.path.insert(0, str(data_dir))
    import evaluate as ev  # type: ignore

    manifest = json.loads((data_dir / "documents.json").read_text(encoding="utf-8"))
    docs = []
    for m in manifest:
        path = data_dir / m[kind]
        result, _ = pipeline.process_document(path.read_bytes(), path.name, m["document_type"])
        docs.append({
            "document_id": m["document_id"], "document_type": result.doc_type, "fields": result.fields_plain(),
            "validation": {"status": result.validation.status, "missing_fields": result.validation.missing_fields,
                           "sources": result.validation.sources},
            "answers": [pipeline.answer_question(result, q["question"]).to_result(q["question_id"]) for q in questions[m["document_id"]]],
        })
    report = ev.evaluate({"documents": list(reference.values())}, {"version": "1.0", "documents": docs})
    assert report["field_accuracy_macro"] == 1.0, report["errors"]
    assert report["validation_exact_match"] == 1.0, report["errors"]
    assert report["question_exact_match"] == 1.0, report["errors"]


def test_auto_type_detection(data_dir):
    manifest = json.loads((data_dir / "documents.json").read_text(encoding="utf-8"))
    correct = 0
    for m in manifest:
        path = data_dir / m["image"]
        result, _ = pipeline.process_document(path.read_bytes(), path.name, None)
        correct += result.doc_type == m["document_type"]
    assert correct == len(manifest)
