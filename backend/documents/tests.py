"""Тесты API (Django TestCase). Требуют загруженных OCR-моделей:  cd backend && python manage.py test"""
import io
import json
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from . import services
from .models import ProcessingResult, Profile, UploadedDocument

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
