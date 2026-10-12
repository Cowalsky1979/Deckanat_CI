#!/usr/bin/env python
"""Генерирует синтетические документы со случайными значениями + манифест, вопросы и эталон.

  python scripts/synth_generate.py --n 15 --out data/synth
  python scripts/predict.py --manifest data/synth/documents.json --questions data/synth/questions.json \
      --base data/synth --out results_synth.json --reference data/synth/reference_results.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from dekanat_core.config.schema import load_doc_types  # noqa: E402
from dekanat_core.models import NOT_FOUND  # noqa: E402
from dekanat_core.rules.validator import validate  # noqa: E402
from dekanat_core.models import FieldValue  # noqa: E402

SURNAMES = ["Кузнецов", "Лебедев", "Соколова", "Морозов", "Волкова", "Зайцев", "Попова", "Новиков", "Фролова", "Егоров",
            "Белова", "Тарасов", "Громова", "Ильин", "Крылова", "Макаров", "Орлова", "Сидоров", "Жукова", "Титов"]
NAMES_M = ["Иван", "Пётр", "Сергей", "Алексей", "Дмитрий", "Николай", "Андрей", "Михаил", "Егор", "Тимур"]
NAMES_F = ["Анна", "Мария", "Елена", "Ольга", "Дарья", "Ирина", "Полина", "Ксения", "Вера", "Алина"]
PATR_M = ["Иванович", "Петрович", "Сергеевич", "Алексеевич", "Дмитриевич", "Николаевич", "Андреевич", "Олегович"]
PATR_F = ["Ивановна", "Петровна", "Сергеевна", "Алексеевна", "Дмитриевна", "Николаевна", "Андреевна", "Олеговна"]
UNIS = ["Учебный университет «Север»", "Учебная академия «Альфа»", "Учебный институт «Логос»", "Учебный университет «Эверест»"]
ORGS = ["Учебная организация «Орбита»", "Учебная компания «Квант»", "Учебное предприятие «Вектор-Плюс»", "Учебная организация «Маяк»"]
PROGRAMS = ["01.03.02 Прикладная математика и информатика", "40.03.01 Юриспруденция", "45.03.02 Лингвистика",
            "38.03.02 Менеджмент", "09.03.04 Программная инженерия"]
FORMS = ["очная", "очно-заочная", "заочная"]
REASONS = ["по состоянию здоровья", "по семейным обстоятельствам", "в связи с призывом на военную службу", "по уходу за ребёнком"]
GRADES = ["отлично", "хорошо", "удовлетворительно", "зачтено"]
GROUPS = ["ПМ-23-1", "ЮР-22-3", "ЛН-24-2", "МН-21-4", "ПИ-23-2"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

FONT_CANDIDATES = [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
BOLD_CANDIDATES = [r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def font(size, bold=False):
    for p in (BOLD_CANDIDATES if bold else FONT_CANDIDATES):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def fio(rng):
    if rng.random() < 0.5:
        return f"{rng.choice(SURNAMES)} {rng.choice(NAMES_M)} {rng.choice(PATR_M)}"
    s = rng.choice(SURNAMES)
    s = s if s.endswith("а") else s + "а"
    return f"{s} {rng.choice(NAMES_F)} {rng.choice(PATR_F)}"


def fmt_date(d: date, style: int) -> str:
    if style == 0:
        return d.strftime("%d.%m.%Y")
    if style == 1:
        return f"{d.day} {MONTHS[d.month - 1]} {d.year} года"
    return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year} г."


def gen_values(doc_type: str, rng) -> tuple[dict, dict]:
    """Возвращает значения для печати и эталон (даты в ISO)."""
    style = rng.randrange(3)
    today = date(2026, 9, 1) + timedelta(days=rng.randrange(60))
    if doc_type == "study_certificate":
        start = date(2021 + rng.randrange(4), 9, 1)
        end = date(start.year + 4, 8, 31)
        vals = {"student_name": fio(rng), "university": rng.choice(UNIS), "program": rng.choice(PROGRAMS),
                "study_form": rng.choice(FORMS), "study_start": start, "study_end": end,
                "document_number": f"ОБ-{rng.randrange(2000, 9999)}", "issue_date": today}
    elif doc_type == "academic_leave_application":
        ls = date(2026, 10 + rng.randrange(3), 1)
        vals = {"student_name": fio(rng), "group": rng.choice(GROUPS), "course": str(rng.randrange(1, 5)),
                "leave_reason": rng.choice(REASONS), "leave_start": ls, "leave_end": date(2027, 8, 31),
                "application_date": today}
    elif doc_type == "transfer_application":
        vals = {"student_name": fio(rng), "current_university": rng.choice(UNIS),
                "target_program": rng.choice(PROGRAMS), "application_date": today}
    else:
        st = date(2026, 6, 1 + rng.randrange(20))
        vals = {"student_name": fio(rng), "organization": rng.choice(ORGS), "internship_start": st,
                "internship_end": st + timedelta(days=40 + rng.randrange(20)), "supervisor_name": fio(rng),
                "grade": rng.choice(GRADES), "document_number": f"ПР-{rng.randrange(3000, 9999)}",
                "issue_date": st + timedelta(days=65)}
    printed = {k: (fmt_date(v, style) if isinstance(v, date) else v) for k, v in vals.items()}
    truth = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in vals.items()}
    return printed, truth


TITLES = {"study_certificate": ("СПРАВКА ОБ ОБУЧЕНИИ", "Сведения об обучении студента приведены ниже.",
                                "Учебный документооборот / отдел сопровождения студентов", "Подпись сотрудника:"),
          "academic_leave_application": ("ЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК", "Прошу предоставить академический отпуск на указанный период.",
                                         "В деканат учебного университета «Меридиан»", "Подпись студента:"),
          "internship_certificate": ("СПРАВКА О ПРАКТИКЕ", "Сведения о прохождении практики приведены ниже.",
                                     "Учебный документооборот / отдел сопровождения студентов", "Подпись руководителя:"),
          "transfer_application": ("ЗАЯВЛЕНИЕ О ПЕРЕВОДЕ", "Прошу перевести меня на указанное направление подготовки.",
                                   "В деканат учебного университета «Меридиан»", "Подпись студента:")}


def draw_signature(draw, x, y, rng):
    pts = []
    cx = x
    for i in range(18):
        cx += rng.randrange(5, 14)
        pts.append((cx, y + rng.randrange(-26, 12)))
    draw.line(pts, fill=(31, 58, 110), width=rng.choice([3, 4]), joint="curve")
    draw.line([(x, y + 8), (x + 240, y + 8)], fill=(150, 150, 150), width=1)


def draw_seal(draw, cx, cy):
    blue = (46, 78, 140)
    for r, w in ((82, 4), (70, 2)):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=blue, width=w)
    f = font(16, True)
    draw.text((cx, cy - 18), "УЧЕБНАЯ", fill=blue, font=f, anchor="mm")
    draw.text((cx, cy + 2), "ПЕЧАТЬ", fill=blue, font=f, anchor="mm")
    draw.text((cx, cy + 22), "МАКЕТ", fill=blue, font=font(12), anchor="mm")


def render(doc_type: str, cfg, printed: dict, missing: set[str], doc_id: str) -> Image.Image:
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    title, intro, header, sig_label = TITLES[doc_type]
    x0 = 100
    d.text((x0, 50), "СИНТЕТИЧЕСКИЙ ДОКУМЕНТ ДЛЯ ХАКАТОНА / НЕ ИМЕЕТ ЮРИДИЧЕСКОЙ СИЛЫ", fill=(120, 120, 120), font=font(16))
    d.text((x0, 130), header, fill="black", font=font(20))
    d.text((x0, 205), title, fill=(20, 30, 50), font=font(32, True))
    d.text((x0, 290), intro, fill="black", font=font(20))
    y = 365
    for spec in cfg.text_fields:
        if spec.key in missing:
            d.text((x0, y), f"{spec.label}: " + "_" * 40, fill="black", font=font(20))
        else:
            d.text((x0, y), f"{spec.label}: {printed[spec.key]}", fill="black", font=font(20))
        y += 52
    sy = 1225
    d.text((x0, sy), sig_label, fill="black", font=font(20))
    if "signature_present" not in missing:
        draw_signature(d, 440, sy + 6, random.Random(doc_id))
    else:
        d.line([(440, sy + 14), (680, sy + 14)], fill=(150, 150, 150), width=1)
    if "seal_present" in cfg.field_map:
        d.text((850, 1330), "М.П.", fill="black", font=font(18))
        if "seal_present" not in missing:
            draw_seal(d, 898, 1245)
    d.text((x0, 1485), "Все сведения вымышлены. Подпись и печать являются учебными макетами.", fill=(120, 120, 120), font=font(15))
    d.text((x0, 1510), f"Идентификатор образца: {doc_id}", fill=(120, 120, 120), font=font(15))
    return img


FIELD_Q = {k: f"Укажи значение поля «{k}»." for k in []}
NOINFO_QS = ["Какова стоимость обучения за следующий семестр?", "Какой размер стипендии положен студенту?",
             "Какой срок рассмотрения документа деканатом?", "По какому номеру телефона можно связаться с деканатом?",
             "В каком кабинете принимают оригиналы документов?"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=15)
    p.add_argument("--out", default="data/synth")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--types", default="study_certificate,academic_leave_application,internship_certificate",
                   help="ключи типов через запятую (например, transfer_application для демо нового типа)")
    p.add_argument("--prefix", default="synth", help="префикс идентификаторов документов")
    p.add_argument("--missing", default=None,
                   help="явный план пропусков через ';' по документам, например 'none;application_date;signature_present'")
    args = p.parse_args()
    rng = random.Random(args.seed)
    out = ROOT / args.out
    (out / "documents").mkdir(parents=True, exist_ok=True)
    types = load_doc_types()
    keys = [k.strip() for k in args.types.split(",") if k.strip()]
    for k in keys:
        if k not in types:
            raise SystemExit(f"Неизвестный тип {k}; доступны: {', '.join(types)}")
    plan = [s.strip() for s in args.missing.split(";")] if args.missing else None
    manifest, questions, reference = [], [], []
    for i in range(args.n):
        doc_type = keys[i % len(keys)]
        cfg = types[doc_type]
        doc_id = f"{args.prefix}-{i + 1:03d}"
        printed, truth = gen_values(doc_type, rng)
        all_keys = [f.key for f in cfg.fields]
        if plan and i < len(plan):
            missing = set() if plan[i] in ("", "none") else {k for k in plan[i].split(",") if k in all_keys}
        else:
            n_missing = rng.choice([0, 0, 1, 1, 2])
            missing = set(rng.sample(all_keys, n_missing))
        img = render(doc_type, cfg, printed, missing, doc_id)
        img.save(out / "documents" / f"{doc_id}.png")
        img.save(out / "documents" / f"{doc_id}.pdf")
        fields = {}
        fvs = {}
        for spec in cfg.fields:
            if spec.is_mark:
                fields[spec.key] = spec.key not in missing
                fvs[spec.key] = FieldValue(spec.key, spec.label, fields[spec.key], kind="mark", found=fields[spec.key])
            else:
                fields[spec.key] = NOT_FOUND if spec.key in missing else truth[spec.key]
                fvs[spec.key] = FieldValue(spec.key, spec.label, fields[spec.key], found=spec.key not in missing)
        v = validate(cfg, fvs)
        text_field = rng.choice(cfg.text_fields)
        qs = [("Q1", "Содержит ли документ все обязательные сведения по Положению?", True, v.status, v.sources),
              ("Q2", f"Укажи значение поля «{text_field.label}».",
               text_field.key not in missing, None if text_field.key in missing else truth[text_field.key],
               [] if text_field.key in missing else [f"field:{text_field.key}"]),
              ("Q3", "Кто принимает окончательное решение о принятии документа?", True, "сотрудник деканата", ["rule:1.3"]),
              ("Q4", rng.choice(NOINFO_QS), False, None, [])]
        manifest.append({"document_id": doc_id, "document_type": doc_type, "image": f"documents/{doc_id}.png", "pdf": f"documents/{doc_id}.pdf"})
        answers = []
        for qn, q, ansable, val, src in qs:
            questions.append({"question_id": f"{doc_id}-{qn}", "document_id": doc_id, "question": q})
            answers.append({"question_id": f"{doc_id}-{qn}", "answerable": ansable, "value": val, "answer": "эталон", "sources": src})
        reference.append({"document_id": doc_id, "document_type": doc_type, "fields": fields,
                          "validation": {"status": v.status, "missing_fields": v.missing_fields, "sources": v.sources},
                          "answers": answers})
    (out / "documents.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "reference_results.json").write_text(json.dumps({"version": "1.0", "documents": reference}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Создано {args.n} документов в {out}")


if __name__ == "__main__":
    main()
