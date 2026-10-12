"""Запросы бота к Django API. Вся обработка на бэкенде."""
from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/") + "/api/v1"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)
# trust_env=False, чтобы не лезть через системный прокси (VPN на винде перехватывает даже 127.0.0.1)


class ApiError(Exception):
    pass


async def _handle(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail") or ""
        except Exception:
            detail = ""
        if not detail:
            detail = f"сервис ответил ошибкой {r.status_code}"
        raise ApiError(str(detail)[:500])
    return r.json()


async def doc_types() -> list[dict]:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        return await _handle(await c.get(f"{API_BASE}/doc-types"))


async def rules() -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        return await _handle(await c.get(f"{API_BASE}/rules"))


async def upload(data: bytes, filename: str, doc_type: str, question: str = "", *, user_id: str = "",
                 wait: bool = True) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        form = {"doc_type": doc_type, "source": "telegram", "telegram_user_id": user_id}
        if question:
            form["question"] = question
        if not wait:
            form["async"] = "1"
        r = await c.post(f"{API_BASE}/documents", data=form, files={"file": (filename, data)})
        return await _handle(r)


async def ask(doc_id: str, question: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        return await _handle(await c.post(f"{API_BASE}/documents/{doc_id}/ask", json={"question": question}))


async def check(doc_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        return await _handle(await c.post(f"{API_BASE}/documents/{doc_id}/check"))


async def change_type(doc_id: str, doc_type: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        return await _handle(await c.patch(f"{API_BASE}/documents/{doc_id}", json={"doc_type": doc_type}))


async def get(doc_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        return await _handle(await c.get(f"{API_BASE}/documents/{doc_id}"))


async def ocr(doc_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        return await _handle(await c.get(f"{API_BASE}/documents/{doc_id}/ocr"))


async def image(doc_id: str, kind: str = "annotated", field: str | None = None) -> bytes | None:
    url = f"{API_BASE}/documents/{doc_id}/annotated.png" if kind == "annotated" else f"{API_BASE}/documents/{doc_id}/fields/{field}/crop.png"
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as c:
        r = await c.get(url)
        return r.content if r.status_code == 200 else None
