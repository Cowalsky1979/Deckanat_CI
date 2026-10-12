#!/usr/bin/env python
"""Бенчмарк устойчивости к «плохим снимкам» (бонус): аугментации открытого набора + метрики.

Для каждой аугментации считаются те же метрики, что и в evaluate.py, плюс точность
автоопределения типа и точность подписи/печати. Результат — Markdown-таблица.

  python scripts/robustness_bench.py --out bench_out --limit 30
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "data"))

from dekanat_core import pipeline  # noqa: E402
import evaluate as ev  # noqa: E402

rng = np.random.default_rng(42)


# ---------------- аугментации ----------------
def rotate(img, angle):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, M, (nw, nh), borderValue=(120, 110, 100))


def perspective(img, strength=0.08):
    h, w = img.shape[:2]
    d = int(min(h, w) * strength)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[d, d // 2], [w - d // 2, d], [w - d, h - d // 3], [d // 3, h - d]])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w, h), borderValue=(90, 85, 80))


def shadow(img):
    h, w = img.shape[:2]
    grad = np.linspace(1.0, 0.45, w, dtype=np.float32)[None, :, None]
    diag = np.tile(np.linspace(0.9, 1.1, h, dtype=np.float32)[:, None, None], (1, w, 3))
    out = img.astype(np.float32) * grad * diag
    return np.clip(out, 0, 255).astype(np.uint8)


def glare(img):
    h, w = img.shape[:2]
    out = img.copy()
    overlay = out.copy()
    cv2.ellipse(overlay, (int(w * 0.65), int(h * 0.35)), (int(w * 0.25), int(h * 0.12)), 20, 0, 360, (255, 255, 255), -1)
    out = cv2.addWeighted(overlay, 0.85, out, 0.15, 0)
    mask = np.zeros((h, w), np.uint8)
    cv2.ellipse(mask, (int(w * 0.65), int(h * 0.35)), (int(w * 0.25), int(h * 0.12)), 20, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (151, 151), 0).astype(np.float32) / 255
    return (img * (1 - mask[..., None]) + out * mask[..., None]).astype(np.uint8)


def downscale(img, k):
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    return small


def jpeg(img, q):
    ok, buf = cv2.imencode(".jpg", img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)[:, :, ::-1]


def noise(img, sigma=12):
    n = rng.normal(0, sigma, img.shape).astype(np.float32)
    return np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8)


def blur(img, k=3):
    return cv2.GaussianBlur(img, (k * 2 + 1, k * 2 + 1), 0)


def photo_combo(img):
    """Типичное фото телефоном: перспектива + тень + наклон 7° + лёгкий шум + jpeg."""
    return jpeg(noise(rotate(shadow(perspective(img, 0.05)), 7), 6), 70)


AUGS = {
    "original": lambda x: x,
    "rot90": lambda x: np.ascontiguousarray(np.rot90(x, 1)),
    "rot180": lambda x: np.ascontiguousarray(np.rot90(x, 2)),
    "rot270": lambda x: np.ascontiguousarray(np.rot90(x, 3)),
    "rot90_photo": lambda x: np.ascontiguousarray(np.rot90(photo_combo(x), 1)),
    "rotate_5": lambda x: rotate(x, 5),
    "rotate_15": lambda x: rotate(x, -15),
    "rotate_30": lambda x: rotate(x, 30),
    "perspective": lambda x: perspective(x, 0.08),
    "shadow": shadow,
    "glare": glare,
    "downscale_0.5": lambda x: downscale(x, 0.5),
    "downscale_0.35": lambda x: downscale(x, 0.35),
    "jpeg_q30": lambda x: jpeg(x, 30),
    "noise": lambda x: noise(x, 15),
    "blur": lambda x: blur(x, 2),
    "photo_combo": photo_combo,
}


def run_one(aug_name, aug, manifest, reference, questions, out_dir: Path | None, limit: int):
    docs, type_ok, mark_ok, mark_total, t_sum = [], 0, 0, 0, 0.0
    for m in manifest[:limit]:
        # np.fromfile + imdecode: cv2.imread не читает пути с кириллицей на Windows
        raw = np.fromfile(str(ROOT / "data" / m["image"]), dtype=np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_COLOR)[:, :, ::-1]
        img = aug(np.ascontiguousarray(img))
        ok, buf = cv2.imencode(".png", np.ascontiguousarray(img[:, :, ::-1]))
        if out_dir:
            (out_dir / aug_name).mkdir(parents=True, exist_ok=True)
            buf.tofile(str(out_dir / aug_name / f"{m['document_id']}.png"))
        t0 = time.perf_counter()
        res, _ = pipeline.process_document(buf.tobytes(), "x.png", m["document_type"])
        t_sum += time.perf_counter() - t0
        auto, _ = pipeline.process_document.__globals__["classify"](pipeline.group_lines(res.ocr_lines))[:2]
        type_ok += auto == m["document_type"]
        ref = reference[m["document_id"]]
        for k, v in ref["fields"].items():
            if isinstance(v, bool):
                mark_total += 1
                mark_ok += res.fields[k].value == v
        docs.append({
            "document_id": m["document_id"], "document_type": res.doc_type, "fields": res.fields_plain(),
            "validation": {"status": res.validation.status, "missing_fields": res.validation.missing_fields,
                           "sources": res.validation.sources},
            "answers": [pipeline.answer_question(res, q["question"]).to_result(q["question_id"]) for q in questions.get(m["document_id"], [])],
        })
    ref_subset = {"documents": [reference[d["document_id"]] for d in docs]}
    rep = ev.evaluate(ref_subset, {"version": "1.0", "documents": docs})
    n = len(docs)
    return {
        "aug": aug_name, "fields": rep["field_accuracy_macro"], "validation": rep["validation_exact_match"],
        "questions": rep["question_exact_match"], "type_acc": round(type_ok / n, 3),
        "marks_acc": round(mark_ok / max(1, mark_total), 3), "sec_per_doc": round(t_sum / n, 2),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=None, help="каталог для сохранения аугментированных снимков")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--augs", default=",".join(AUGS))
    p.add_argument("--report", default="bench_report.json")
    args = p.parse_args()

    manifest = json.loads((ROOT / "data" / "documents.json").read_text(encoding="utf-8"))
    reference = {d["document_id"]: d for d in json.loads((ROOT / "data" / "reference_results.json").read_text(encoding="utf-8"))["documents"]}
    questions: dict = {}
    for q in json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8")):
        questions.setdefault(q["document_id"], []).append(q)
    out_dir = Path(args.out) if args.out else None

    rows = []
    for name in args.augs.split(","):
        row = run_one(name, AUGS[name], manifest, reference, questions, out_dir, args.limit)
        rows.append(row)
        print(f"{name:16} fields={row['fields']:.3f} validation={row['validation']:.3f} questions={row['questions']:.3f} "
              f"type={row['type_acc']:.3f} marks={row['marks_acc']:.3f} {row['sec_per_doc']}s/doc", flush=True)
    Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n| Аугментация | Поля | Проверка | Вопросы | Тип (авто) | Подпись/печать | с/док |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['aug']} | {r['fields']:.3f} | {r['validation']:.3f} | {r['questions']:.3f} | {r['type_acc']:.3f} | {r['marks_acc']:.3f} | {r['sec_per_doc']} |")


if __name__ == "__main__":
    main()
