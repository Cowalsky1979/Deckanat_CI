"""Тесты API (Django TestCase). Требуют загруженных OCR-моделей:  cd backend && python manage.py test"""
import json
from pathlib import Path

from django.test import TestCase, override_settings

DATA = Path(__file__).resolve().parents[2] / "data"


@override_settings(DEKANAT_WARMUP=False, DEKANAT_INLINE_WORKERS=True)
class ApiTests(TestCase):
    def _upload(self, name, **form):
        with open(DATA / "documents" / name, "rb") as f:
            return self.client.post("/api/v1/documents", {"file": f, **form})

    def test_meta_endpoints(self):
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        types = self.client.get("/api/v1/doc-types").json()
        self.assertEqual({t["key"] for t in types}, {"study_certificate", "academic_leave_application", "internship_certificate"})
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
