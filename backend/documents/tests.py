"""Тесты API (Django TestCase). Требуют загруженных OCR-моделей:  cd backend && python manage.py test"""
import io
import json
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from . import services
from .models import DocumentReview, ProcessingResult, Profile, UploadedDocument

DATA = Path(__file__).resolve().parents[2] / "data"


@override_settings(DEKANAT_WARMUP=False, DEKANAT_INLINE_WORKERS=True)
class ApiTests(TestCase):
    def _upload(self, name, **form):
        with open(DATA / "documents" / name, "rb") as f:
            return self.client.post("/api/v1/documents", {"file": f, **form})

    def test_meta_endpoints(self):
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        types = self.client.get("/api/v1/doc-types").json()
        self.assertEqual({t["key"] for t in types},
                         {"study_certificate", "academic_leave_application", "internship_certificate", "transfer_application"})
        rules = self.client.get("/api/v1/rules").json()
        self.assertTrue(any(r["id"] == "1.3" for s in rules["sections"] for r in s["rules"]))

    def test_bad_file(self):
        r = self.client.post("/api/v1/documents", {"file": open(DATA / "rules.md", "rb")})
        self.assertEqual(r.status_code, 422)

    def test_full_flow(self):
        r = self._upload("open-002.png", doc_type="auto", question="Какова дата выдачи?")
        self.assertEqual(r.status_code, 201, r.content[:300])
        d = r.json()
        self.assertEqual(d["doc_type"], "study_certificate")
        self.assertEqual(d["result"]["validation"], {**d["result"]["validation"], "status": "missing_fields", "missing_fields": ["issue_date"], "sources": ["rule:3.1"]})
        self.assertFalse(d["answer"]["answerable"])
        self.assertEqual(d["result"]["fields"]["student_name"]["value"], "Мельников Денис Игоревич")
        did = d["id"]
        a = self.client.post(f"/api/v1/documents/{did}/ask", json.dumps({"question": "Кто принимает решение?"}), content_type="application/json").json()
        self.assertEqual((a["value"], a["sources"]), ("сотрудник деканата", ["rule:1.3"]))
        c = self.client.post(f"/api/v1/documents/{did}/check").json()
        self.assertEqual(c["value"], "missing_fields")
        self.assertEqual(self.client.get(f"/api/v1/documents/{did}/fields/student_name/crop.png")["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get(f"/api/v1/documents/{did}/image?variant=preview")["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get(f"/api/v1/documents/{did}/annotated.png").status_code, 200)
        self.assertEqual(len(self.client.get(f"/api/v1/documents/{did}/boxes").json()), 10)
        p = self.client.patch(f"/api/v1/documents/{did}", json.dumps({"doc_type": "internship_certificate"}), content_type="application/json").json()
        self.assertEqual(p["doc_type"], "internship_certificate")
        e = self.client.get(f"/api/v1/documents/{did}/export.json").json()
        self.assertEqual(set(e), {"document_id", "document_type", "fields", "validation", "answers"})

    def test_async_mode_with_question(self):
        import time

        r = self._upload("open-002.png", doc_type="auto", question="Какова дата выдачи?", **{"async": "1"})
        self.assertEqual(r.status_code, 202)
        did = r.json()["id"]
        self.assertEqual(r.json()["status"], "processing")
        for _ in range(60):
            d = self.client.get(f"/api/v1/documents/{did}").json()
            if d["status"] != "processing":
                break
            time.sleep(0.5)
        self.assertEqual(d["status"], "done", d.get("error"))
        self.assertEqual(d["doc_type"], "study_certificate")
        self.assertEqual(len(d["questions"]), 1)
        self.assertFalse(d["questions"][0]["answerable"])  # дата выдачи отсутствует в open-002

    def test_wrong_type_is_reported(self):
        r = self._upload("open-001.png", doc_type="academic_leave_application")
        self.assertEqual(r.status_code, 201)
        mm = r.json()["result"]["type_mismatch"]
        self.assertIsNotNone(mm)
        self.assertEqual(mm["detected"], "study_certificate")
        self.assertTrue(any("неправильный тип" in w for w in r.json()["result"]["warnings"]))

    def test_pdf_with_check(self):
        r = self._upload("open-013.pdf", doc_type="academic_leave_application", check="true")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["answer"]["sources"], ["rule:4.2"])

    def test_upload_with_profile_sets_owner(self):
        pid = self.client.post("/api/v1/profiles", json.dumps({"role": "student", "name": "Иван"}),
                               content_type="application/json").json()["id"]
        with open(DATA / "documents" / "open-013.pdf", "rb") as f:
            r = self.client.post("/api/v1/documents", {"file": f, "doc_type": "academic_leave_application"},
                                 headers={"X-Profile-Id": pid})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["owner"]["name"], "Иван")
        self.assertIsNotNone(r.json()["ai_summary"])


@override_settings(DEKANAT_WARMUP=False, DEKANAT_INLINE_WORKERS=True)
class CabinetTests(TestCase):
    """Кабинеты студента и деканата. OCR не нужен: документы создаются напрямую."""

    def _profile(self, role, name, tg=""):
        r = self.client.post("/api/v1/profiles", json.dumps({"role": role, "name": name, "telegram_user_id": tg}),
                             content_type="application/json")
        self.assertIn(r.status_code, (200, 201), r.content)
        return r.json()["id"]

    @staticmethod
    def _h(pid):
        return {"headers": {"X-Profile-Id": pid}} if pid else {}

    @staticmethod
    def _mk_doc(owner=None, status="done", missing=("issue_date",), low_quality=False, mismatch=None, tg=""):
        if isinstance(owner, str):
            owner = Profile.objects.get(pk=owner)
        doc = UploadedDocument(original_name="x.png", mime="image/png", size=1, selected_type="study_certificate",
                               doc_type="study_certificate", status=status, owner=owner, telegram_user_id=tg)
        doc.file.save("x.png", ContentFile(b"x"), save=False)
        doc.save()
        if status == "done":
            fields = {"student_name": {"key": "student_name", "label": "ФИО", "value": "Иванов", "found": True, "kind": "text"},
                      "issue_date": {"key": "issue_date", "label": "Дата выдачи", "value": "", "found": False, "kind": "text"}}
            if missing:
                validation = {"status": "missing_fields", "missing_fields": list(missing), "sources": ["rule:3.1"],
                              "message": "Не хватает полей"}
            else:
                validation = {"status": "document_ok", "missing_fields": [], "sources": ["rule:3.1", "rule:3.2"], "message": "OK"}
            ProcessingResult.objects.create(document=doc, result={
                "doc_type": "study_certificate", "doc_type_title": "Справка об обучении", "fields": fields,
                "validation": validation, "quality": {"readability": {"low_quality": low_quality}},
                "warnings": [], "type_mismatch": mismatch})
        return doc

    def test_create_profile_and_me(self):
        pid = self._profile("student", "  Иван ")
        me = self.client.get("/api/v1/profiles/me", **self._h(pid))
        self.assertEqual((me.status_code, me.json()["name"], me.json()["role"]), (200, "Иван", "student"))
        self.assertEqual(self.client.get("/api/v1/profiles/me").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/profiles/me", headers={"X-Profile-Id": "not-a-uuid"}).status_code, 404)
        r = self.client.post("/api/v1/profiles", json.dumps({"role": "dean", "name": "  "}), content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_same_name_reopens_cabinet(self):
        a = self._profile("student", "Иван Петров")
        doc = self._mk_doc(owner=a)
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        # то же имя (регистр и пробелы не важны) - тот же кабинет с историей
        again = self.client.post("/api/v1/profiles", json.dumps({"role": "student", "name": "  иван   петров "}),
                                 content_type="application/json")
        self.assertEqual((again.status_code, again.json()["id"]), (200, a))
        self.assertEqual(len(self.client.get("/api/v1/documents", **self._h(a)).json()), 1)
        # другая роль с тем же именем - отдельный профиль
        self.assertNotEqual(self._profile("dean", "Иван Петров"), a)
        # профиль с Telegram id и тем же именем привязывается к профилю с сайта
        self.assertEqual(self._profile("student", "Иван Петров", tg="555"), a)
        self.assertEqual(self.client.get("/api/v1/profiles/me", **self._h(a)).json()["telegram_user_id"], "555")

    def test_profile_by_telegram_id_updates_role_and_backfills_owner(self):
        doc = self._mk_doc(tg="42")
        pid = self._profile("student", "Петя", tg="42")
        doc.refresh_from_db()
        self.assertEqual(str(doc.owner_id), pid)
        pid2 = self._profile("dean", "Петя (деканат)", tg="42")
        self.assertEqual(pid, pid2)
        self.assertEqual(self.client.get("/api/v1/profiles/me", **self._h(pid)).json()["role"], "dean")
        # два профиля без Telegram не конфликтуют по unique
        self.assertNotEqual(self._profile("student", "А"), self._profile("student", "Б"))

    def test_owner_for_resolves_header_then_telegram(self):
        pid = self._profile("student", "Вася", tg="7")
        self.assertEqual(str(services.owner_for(pid, "").id), pid)
        self.assertEqual(str(services.owner_for(None, "7").id), pid)
        self.assertEqual(str(services.owner_for("bad-id", "7").id), pid)
        self.assertIsNone(services.owner_for(None, "8"))

    def test_student_list_only_own(self):
        a, b = self._profile("student", "А"), self._profile("student", "Б")
        self._mk_doc(owner=a)
        self._mk_doc(owner=a, missing=())
        self._mk_doc(owner=b)
        rows = self.client.get("/api/v1/documents", **self._h(a)).json()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["validation_status"] for r in rows}, {"missing_fields", "document_ok"})
        self.assertEqual(rows[0]["doc_type_title"], "Справка об обучении")
        self.assertIsNone(rows[0]["review"])
        self.assertEqual(self.client.get("/api/v1/documents").status_code, 403)

    def test_submit_pending_then_409(self):
        a = self._profile("student", "А")
        doc = self._mk_doc(owner=a)
        r = self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        self.assertEqual((r.status_code, r.json()["status"]), (201, "pending"))
        self.assertEqual(self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a)).status_code, 409)
        proc = self._mk_doc(owner=a, status="processing")
        self.assertEqual(self.client.post(f"/api/v1/documents/{proc.id}/submit", **self._h(a)).status_code, 409)
        # документ без владельца (загружен до выбора роли) забирается при отправке
        orphan = self._mk_doc()
        self.assertEqual(self.client.post(f"/api/v1/documents/{orphan.id}/submit", **self._h(a)).status_code, 201)
        orphan.refresh_from_db()
        self.assertEqual(str(orphan.owner_id), a)
        # чужой документ отправить нельзя
        b = self._profile("student", "Б")
        other = self._mk_doc(owner=b)
        self.assertEqual(self.client.post(f"/api/v1/documents/{other.id}/submit", **self._h(a)).status_code, 403)

    def test_dean_endpoints_require_dean(self):
        a = self._profile("student", "А")
        doc = self._mk_doc(owner=a)
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        for pid in (a, None):
            self.assertEqual(self.client.get("/api/v1/reviews/summary", **self._h(pid)).status_code, 403)
            self.assertEqual(self.client.post(f"/api/v1/documents/{doc.id}/review/seen", **self._h(pid)).status_code, 403)
            self.assertEqual(self.client.post(f"/api/v1/documents/{doc.id}/review/decide", json.dumps({"status": "accepted"}),
                                              content_type="application/json", **self._h(pid)).status_code, 403)
        d = self._profile("dean", "Д")
        self.assertEqual(self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(d)).status_code, 403)

    def test_dean_summary_seen_decide_accept(self):
        a, d = self._profile("student", "А"), self._profile("dean", "Декан")
        doc = self._mk_doc(owner=a)
        self._mk_doc(owner=a)  # не отправлен, деканат его не видит
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        self.assertEqual(self.client.get("/api/v1/reviews/summary", **self._h(d)).json(), {"pending": 1, "unseen": 1})
        rows = self.client.get("/api/v1/documents", **self._h(d)).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["owner"]["name"], "А")
        self.assertIn("дата выдачи", rows[0]["ai_summary"]["headline"].lower())
        self.assertFalse(rows[0]["review"]["seen_by_dean"])

        self.assertTrue(self.client.post(f"/api/v1/documents/{doc.id}/review/seen", **self._h(d)).json()["seen_by_dean"])
        self.assertEqual(self.client.get("/api/v1/reviews/summary", **self._h(d)).json(), {"pending": 1, "unseen": 0})

        r = self.client.post(f"/api/v1/documents/{doc.id}/review/decide", json.dumps({"status": "accepted", "comment": "ок"}),
                             content_type="application/json", **self._h(d))
        self.assertEqual(r.status_code, 200, r.content)
        rev = r.json()["review"]
        self.assertEqual((rev["status"], rev["reviewer"]["name"], rev["comment"]), ("accepted", "Декан", "ок"))
        self.assertIsNotNone(rev["decided_at"])
        self.assertEqual(self.client.get("/api/v1/reviews/summary", **self._h(d)).json(), {"pending": 0, "unseen": 0})
        self.assertEqual(len(self.client.get("/api/v1/documents", **self._h(d)).json()), 0)
        self.assertEqual(len(self.client.get("/api/v1/documents?review=decided", **self._h(d)).json()), 1)
        # студент видит решение
        mine = {r["id"]: r for r in self.client.get("/api/v1/documents", **self._h(a)).json()}
        self.assertEqual(mine[str(doc.id)]["review"]["status"], "accepted")

    def test_reject_requires_comment_and_stores_ai_reason(self):
        a, d = self._profile("student", "А"), self._profile("dean", "Декан")
        doc = self._mk_doc(owner=a)
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        url = f"/api/v1/documents/{doc.id}/review/decide"
        r = self.client.post(url, json.dumps({"status": "rejected"}), content_type="application/json", **self._h(d))
        self.assertEqual(r.status_code, 400)
        self.assertIn("comment", r.json())
        reason = self.client.get(f"/api/v1/documents/{doc.id}", **self._h(d)).json()["ai_summary"]["suggested_reasons"][0]
        r = self.client.post(url, json.dumps({"status": "rejected", "comment": reason, "reason_source": "ai"}),
                             content_type="application/json", **self._h(d))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["review"]["reason_source"], r.json()["review"]["comment"]), ("ai", reason))
        # решение можно изменить
        r = self.client.post(url, json.dumps({"status": "accepted"}), content_type="application/json", **self._h(d))
        self.assertEqual(r.json()["review"]["status"], "accepted")

    def test_review_summary_reasons(self):
        doc = self._mk_doc(low_quality=True,
                           mismatch={"detected": "internship_certificate", "detected_title": "Справка о практике", "score": 0.9})
        s = services.review_summary(doc)
        self.assertEqual(len(s["suggested_reasons"]), 3)
        self.assertIn("«Дата выдачи» (п. 3.1 Положения)", s["suggested_reasons"][0])
        self.assertIn("низкого качества", s["suggested_reasons"][1])
        self.assertIn("Справка о практике", s["suggested_reasons"][2])
        self.assertEqual(s["missing"][0]["rule"], "3.1")
        self.assertTrue(s["headline"].startswith("Снимок низкого качества"))
        ok = services.review_summary(self._mk_doc(missing=()))
        self.assertEqual((ok["suggested_reasons"], ok["validation_status"]), ([], "document_ok"))
        self.assertIn("3.1, 3.2", ok["headline"])
        self.assertIsNone(services.review_summary(self._mk_doc(status="processing")))

    def test_cleanup_keeps_owned_or_reviewed(self):
        a = self._profile("student", "А")
        anon = self._mk_doc()
        owned = self._mk_doc(owner=a)
        reviewed = self._mk_doc()
        self.client.post(f"/api/v1/documents/{reviewed.id}/submit", **self._h(a))
        reviewed.owner = None
        reviewed.save(update_fields=["owner"])
        call_command("cleanup_uploads", days=0, stdout=io.StringIO())
        left = set(UploadedDocument.objects.values_list("id", flat=True))
        self.assertEqual(left, {owned.id, reviewed.id})
        self.assertNotIn(anon.id, left)



@override_settings(DEKANAT_WARMUP=False, DEKANAT_INLINE_WORKERS=True)
class RevisionAndNotificationTests(TestCase):
    """Ручная правка полей, «нужно исправить», исправленные версии, уведомления, CSV. OCR не нужен."""

    def _profile(self, role, name, tg=""):
        r = self.client.post("/api/v1/profiles", json.dumps({"role": role, "name": name, "telegram_user_id": tg}),
                             content_type="application/json")
        self.assertIn(r.status_code, (200, 201), r.content)
        return r.json()["id"]

    @staticmethod
    def _h(pid):
        return {"headers": {"X-Profile-Id": pid}} if pid else {}

    def _full_doc(self, owner=None, missing=("issue_date",), tg="", parent=None, reasons=None):
        """Документ со всеми полями справки об обучении (как после OCR)."""
        from dekanat_core.config.schema import get_doc_type
        from dekanat_core.models import MISSING_ANCHOR, MISSING_EMPTY, FieldValue
        from dekanat_core.rules.validator import validate

        if isinstance(owner, str):
            owner = Profile.objects.get(pk=owner)
        cfg = get_doc_type("study_certificate")
        fields = {}
        for spec in cfg.fields:
            gone = spec.key in missing
            if spec.is_mark:
                fields[spec.key] = FieldValue(spec.key, spec.label, not gone, kind="mark", found=not gone, bbox=(0, 0, 5, 5),
                                              missing_reason=MISSING_ANCHOR if gone else None)
            else:
                v = "не найдено" if gone else ("2026-01-10" if spec.type == "date" else "Иванов Иван Иванович" if spec.key == "student_name" else "очная" if spec.key == "study_form" else "x")
                fields[spec.key] = FieldValue(spec.key, spec.label, v, raw=v, found=not gone, bbox=(0, 0, 5, 5), label_bbox=(0, 0, 2, 2),
                                              confidence=0.9, missing_reason=(reasons or {}).get(spec.key, MISSING_EMPTY) if gone else None)
        doc = UploadedDocument(original_name="x.png", mime="image/png", size=1, selected_type="study_certificate",
                               doc_type="study_certificate", status="done", owner=owner, telegram_user_id=tg, parent=parent)
        doc.file.save("x.png", ContentFile(b"x"), save=False)
        doc.save()
        validation = validate(cfg, fields)
        ProcessingResult.objects.create(document=doc, result={
            "doc_type": "study_certificate", "doc_type_title": "Справка об обучении",
            "fields": {k: v.to_dict() for k, v in fields.items()},
            "validation": validation.to_dict(), "ocr_text": "", "ocr_lines": [], "image_size": [100, 100],
            "quality": {"readability": {"low_quality": False}}, "warnings": [], "type_mismatch": None})
        return doc

    def _patch_field(self, doc, key, value, pid=None):
        return self.client.patch(f"/api/v1/documents/{doc.id}/fields/{key}", json.dumps({"value": value}),
                                 content_type="application/json", **self._h(pid))

    # ---------- ручная правка ----------

    def test_manual_edit_keeps_ocr_and_revalidates(self):
        a = self._profile("student", "А")
        doc = self._full_doc(owner=a)
        r = self._patch_field(doc, "issue_date", "15.03.2026", a)
        self.assertEqual(r.status_code, 200, r.content)
        f = r.json()["result"]["fields"]["issue_date"]
        self.assertEqual((f["value"], f["source"], f["ocr_value"], f["found"]), ("2026-03-15", "manual", "не найдено", True))
        self.assertEqual(r.json()["result"]["validation"]["status"], "document_ok")
        # анализ для деканата видит ручную правку
        s = r.json()["ai_summary"]
        self.assertEqual(s["manual_fields"][0]["key"], "issue_date")
        self.assertTrue(any("вручную" in x for x in s["suggested_reasons"]))
        # ответ на вопрос честно говорит про правку, а выгрузка results.json берёт только OCR
        a1 = self.client.post(f"/api/v1/documents/{doc.id}/ask", json.dumps({"question": "Укажи значение поля «Дата выдачи»."}),
                              content_type="application/json").json()
        self.assertEqual(a1["value"], "2026-03-15")
        self.assertIn("исправлено вручную", a1["answer"])
        e = self.client.get(f"/api/v1/documents/{doc.id}/export.json").json()
        self.assertEqual((e["fields"]["issue_date"], e["validation"]["status"]), ("не найдено", "missing_fields"))
        # пустое значение возвращает OCR
        r = self._patch_field(doc, "issue_date", "", a)
        f = r.json()["result"]["fields"]["issue_date"]
        self.assertEqual((f["value"], f["source"], f["found"], f["missing_reason"]), ("не найдено", "ocr", False, "empty_value"))
        self.assertEqual(r.json()["result"]["validation"]["status"], "missing_fields")

    def test_manual_edit_restrictions(self):
        a, b, d = self._profile("student", "А"), self._profile("student", "Б"), self._profile("dean", "Д")
        doc = self._full_doc(owner=a)
        self.assertEqual(self._patch_field(doc, "issue_date", "01.01.2026", d).status_code, 409)       # деканат не правит
        self.assertEqual(self._patch_field(doc, "issue_date", "01.01.2026", b).status_code, 409)       # чужой документ
        self.assertEqual(self._patch_field(doc, "seal_present", "да", a).status_code, 409)             # отметки нельзя
        self.assertEqual(self._patch_field(doc, "nope", "x", a).status_code, 409)                      # нет такого поля
        self.assertEqual(self._patch_field(doc, "issue_date", "когда-то", a).status_code, 409)         # не дата
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        self.assertEqual(self._patch_field(doc, "issue_date", "01.01.2026", a).status_code, 409)       # на рассмотрении
        # после «нужно исправить» править снова можно
        self.client.post(f"/api/v1/documents/{doc.id}/review/decide", json.dumps({"status": "needs_fix", "comment": "нет даты"}),
                         content_type="application/json", **self._h(d))
        self.assertEqual(self._patch_field(doc, "issue_date", "01.01.2026", a).status_code, 200)

    # ---------- причины «не найдено» ----------

    def test_missing_reason_in_summary_and_answer(self):
        from dekanat_core.models import MISSING_LABEL

        doc = self._full_doc(missing=("issue_date", "university", "seal_present"), reasons={"university": MISSING_LABEL})
        s = services.review_summary(doc)
        by_key = {m["key"]: m for m in s["missing"]}
        self.assertEqual(by_key["issue_date"]["reason"], "empty_value")
        self.assertEqual(by_key["university"]["reason"], "label_not_found")
        self.assertEqual(by_key["seal_present"]["reason"], "anchor_not_found")
        self.assertTrue(any("не заполнено" in r for r in s["suggested_reasons"]))
        ask = lambda q: self.client.post(f"/api/v1/documents/{doc.id}/ask", json.dumps({"question": q}),
                                         content_type="application/json").json()
        a1 = ask("Укажи значение поля «Дата выдачи».")
        self.assertFalse(a1["answerable"]) ; self.assertIsNone(a1["value"]) ; self.assertEqual(a1["sources"], [])
        self.assertIn("не заполнено", a1["answer"])
        a2 = ask("Укажи значение поля «Название вуза».")
        self.assertFalse(a2["answerable"])
        self.assertIn("не удалось распознать", a2["answer"])

    # ---------- нужно исправить, версии, diff ----------

    def test_needs_fix_revision_autosubmit_and_diff(self):
        a, d = self._profile("student", "А", tg="100"), self._profile("dean", "Декан")
        doc = self._full_doc(owner=a)
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        url = f"/api/v1/documents/{doc.id}/review/decide"
        # без причины нельзя
        self.assertEqual(self.client.post(url, json.dumps({"status": "needs_fix"}), content_type="application/json", **self._h(d)).status_code, 400)
        r = self.client.post(url, json.dumps({"status": "needs_fix", "comment": "Допечатайте дату выдачи"}),
                             content_type="application/json", **self._h(d))
        self.assertEqual((r.status_code, r.json()["review"]["status"]), (200, "needs_fix"))
        # уведомление студенту в Telegram поставлено в очередь
        n = self.client.get("/api/v1/notifications/pending").json()
        self.assertEqual(len(n), 1)
        self.assertEqual(n[0]["telegram_user_id"], "100")
        self.assertIn("просит исправить", n[0]["text"])
        self.assertIn("Допечатайте", n[0]["text"])
        self.assertEqual(self.client.post(f"/api/v1/notifications/{n[0]['id']}/sent").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/notifications/pending").json(), [])
        # в обработанных заявках деканата, у студента со статусом
        self.assertEqual(len(self.client.get("/api/v1/documents?review=decided", **self._h(d)).json()), 1)
        mine = self.client.get("/api/v1/documents", **self._h(a)).json()
        self.assertEqual(mine[0]["review"]["status"], "needs_fix")

        # исправленная версия: проверяем ограничение и связь
        self.assertEqual(services.parent_for_revision(doc.id, Profile.objects.get(pk=a)).id, doc.id)
        with self.assertRaises(services.ProcessingError):
            services.parent_for_revision(doc.id, Profile.objects.get(pk=d))
        fresh = self._full_doc(owner=a)
        with self.assertRaises(services.ProcessingError):  # не возвращался деканатом
            services.parent_for_revision(fresh.id, Profile.objects.get(pk=a))
        rev = self._full_doc(owner=a, missing=(), parent=doc)
        self.assertEqual(self.client.post(f"/api/v1/documents/{rev.id}/submit", **self._h(a)).status_code, 201)
        full = self.client.get(f"/api/v1/documents/{rev.id}", **self._h(d)).json()
        self.assertEqual(full["parent"]["id"], str(doc.id))
        self.assertEqual(full["parent"]["review_status"], "needs_fix")
        self.assertTrue(full["ai_summary"]["is_revision"])
        parent_full = self.client.get(f"/api/v1/documents/{doc.id}", **self._h(a)).json()
        self.assertEqual(parent_full["revisions"][0]["id"], str(rev.id))
        diff = self.client.get(f"/api/v1/documents/{rev.id}/diff").json()
        self.assertEqual((diff["before_status"], diff["after_status"], diff["before_missing"]), ("missing_fields", "document_ok", ["issue_date"]))
        row = next(x for x in diff["rows"] if x["key"] == "issue_date")
        self.assertEqual((row["before"], row["after"], row["changed"], row["fixed"]), ("не найдено", "2026-01-10", True, True))
        self.assertEqual(diff["changed_count"], 1)
        self.assertEqual(self.client.get(f"/api/v1/documents/{doc.id}/diff").status_code, 404)

    def test_revision_upload_autosubmits_after_processing(self):
        """process_upload с parent: владелец и тип берутся из прежней версии, после обработки заявка создаётся сама."""
        a, d = self._profile("student", "А"), self._profile("dean", "Декан")
        doc = self._full_doc(owner=a)
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        self.client.post(f"/api/v1/documents/{doc.id}/review/decide", json.dumps({"status": "rejected", "comment": "нет"}),
                         content_type="application/json", **self._h(d))
        # без OCR сам конвейер не запускаем: проверяем сборку документа и авто-отправку отдельно
        new = UploadedDocument(original_name="fix.png", mime="image/png", size=1, selected_type="study_certificate",
                               doc_type="study_certificate", status="processing", owner=Profile.objects.get(pk=a), parent=doc)
        new.file.save("fix.png", ContentFile(b"x"), save=False)
        new.save()
        # имитируем завершение обработки
        ProcessingResult.objects.create(document=new, result=doc.result.result)
        new.status = "done"
        new.save()
        self.assertIsNotNone(services.autosubmit_revision(UploadedDocument.objects.get(pk=new.pk)))
        self.assertIsNone(services.autosubmit_revision(UploadedDocument.objects.get(pk=new.pk)))   # второй раз не создаёт
        self.assertEqual(DocumentReview.objects.filter(document=new).count(), 1)
        self.assertEqual(self.client.get("/api/v1/reviews/summary", **self._h(d)).json()["pending"], 1)
        rows = self.client.get("/api/v1/documents", **self._h(d)).json()
        self.assertEqual(rows[0]["parent"]["id"], str(doc.id))

    def test_decision_notifications_and_csv(self):
        a, d = self._profile("student", "А", tg="7"), self._profile("dean", "Декан")
        doc = self._full_doc(owner=a)
        self.client.post(f"/api/v1/documents/{doc.id}/submit", **self._h(a))
        self.client.post(f"/api/v1/documents/{doc.id}/review/decide", json.dumps({"status": "accepted"}),
                         content_type="application/json", **self._h(d))
        n = self.client.get("/api/v1/notifications/pending").json()
        self.assertEqual(len(n), 1)
        self.assertIn("принял", n[0]["text"])
        # документ без Telegram не порождает уведомлений
        b = self._profile("student", "Б")
        doc2 = self._full_doc(owner=b, missing=())
        self.client.post(f"/api/v1/documents/{doc2.id}/submit", **self._h(b))
        self.client.post(f"/api/v1/documents/{doc2.id}/review/decide", json.dumps({"status": "rejected", "comment": "плохо"}),
                         content_type="application/json", **self._h(d))
        self.assertEqual(len(self.client.get("/api/v1/notifications/pending").json()), 1)
        # CSV: только деканату, можно по ?profile_id= (ссылка на скачивание)
        self.assertEqual(self.client.get("/api/v1/reviews/export.csv").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/reviews/export.csv", **self._h(a)).status_code, 403)
        r = self.client.get(f"/api/v1/reviews/export.csv?profile_id={d}")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        self.assertTrue(body.startswith("﻿ID документа;Студент;"))
        lines = body.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("принято", body)
        self.assertIn("отклонено", body)
        self.assertIn("дата выдачи", body.lower())
        r = self.client.get("/api/v1/reviews/export.csv?review=pending", **self._h(d))
        self.assertEqual(len(r.content.decode("utf-8").strip().splitlines()), 1)

    @override_settings(DEKANAT_ADMIN_TOKEN="secret")
    def test_notifications_require_token_when_set(self):
        self.assertEqual(self.client.get("/api/v1/notifications/pending").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/notifications/pending", headers={"X-Admin-Token": "secret"}).status_code, 200)

    def test_bot_profile_history_flow(self):
        """Сценарий бота: профиль по Telegram id, загрузки с X-Profile-Id, список своих документов."""
        pid = self._profile("student", "Тг Пользователь", tg="900")
        self._full_doc(owner=pid, tg="900")
        rows = self.client.get("/api/v1/documents?limit=10", **self._h(pid)).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doc_type_title"], "Справка об обучении")
