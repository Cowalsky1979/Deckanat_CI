"""Запросы бота к Django API. Вся обработка на бэкенде."""
from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/") + "/api/v1"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)
# токен для очереди уведомлений (если задан на бэкенде DEKANAT_ADMIN_TOKEN)
ADMIN_TOKEN = os.environ.get("DEKANAT_ADMIN_TOKEN", "")
# trust_env=False, чтобы не лезть через системный прокси (VPN на винде перехватывает даже 127.0.0.1)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


async def _handle(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        try:
            j = r.json()
            detail = j.get("detail") or (j.get("comment") and [j["comment"]][0]) or ""
            if isinstance(detail, list):
                detail = detail[0]
        except Exception:
            detail = ""
        if not detail:
            detail = f"сервис ответил ошибкой {r.status_code}"
        raise ApiError(str(detail)[:500], r.status_code)
    if r.status_code == 204:
        return None
    return r.json()


def _client(profile_id: str | None = None) -> httpx.AsyncClient:
    headers = {}
    if profile_id:
        headers["X-Profile-Id"] = profile_id   # профиль кабинета: загрузки попадают в «Мои документы»
    if ADMIN_TOKEN:
        headers["X-Admin-Token"] = ADMIN_TOKEN
    return httpx.AsyncClient(timeout=TIMEOUT, trust_env=False, headers=headers)


async def doc_types() -> list[dict]:
    async with _client() as c:
        return await _handle(await c.get(f"{API_BASE}/doc-types"))


async def rules() -> dict:
    async with _client() as c:
        return await _handle(await c.get(f"{API_BASE}/rules"))


async def upload(data: bytes, filename: str, doc_type: str, question: str = "", *, user_id: str = "",
                 wait: bool = True, profile_id: str | None = None) -> dict:
    async with _client(profile_id) as c:
        form = {"doc_type": doc_type, "source": "telegram", "telegram_user_id": user_id}
        if question:
            form["question"] = question
        if not wait:
            form["async"] = "1"
        r = await c.post(f"{API_BASE}/documents", data=form, files={"file": (filename, data)})
        return await _handle(r)


async def ask(doc_id: str, question: str) -> dict:
    async with _client() as c:
        return await _handle(await c.post(f"{API_BASE}/documents/{doc_id}/ask", json={"question": question}))


async def check(doc_id: str) -> dict:
    async with _client() as c:
        return await _handle(await c.post(f"{API_BASE}/documents/{doc_id}/check"))


async def change_type(doc_id: str, doc_type: str) -> dict:
    async with _client() as c:
        return await _handle(await c.patch(f"{API_BASE}/documents/{doc_id}", json={"doc_type": doc_type}))


async def get(doc_id: str) -> dict:
    async with _client() as c:
        return await _handle(await c.get(f"{API_BASE}/documents/{doc_id}"))


async def ocr(doc_id: str) -> dict:
    async with _client() as c:
        return await _handle(await c.get(f"{API_BASE}/documents/{doc_id}/ocr"))


async def image(doc_id: str, kind: str = "annotated", field: str | None = None) -> bytes | None:
    url = f"{API_BASE}/documents/{doc_id}/annotated.png" if kind == "annotated" else f"{API_BASE}/documents/{doc_id}/fields/{field}/crop.png"
    async with _client() as c:
        r = await c.get(url)
        return r.content if r.status_code == 200 else None


# ---------- кабинет: профиль по Telegram id, история, отправка в деканат ----------

async def ensure_profile(name: str, telegram_user_id: str) -> dict:
    """Профиль студента, привязанный к Telegram-аккаунту (создаётся один раз)."""
    async with _client() as c:
        r = await c.post(f"{API_BASE}/profiles",
                         json={"role": "student", "name": name[:120] or f"Пользователь {telegram_user_id}",
                               "telegram_user_id": telegram_user_id})
        return await _handle(r)


async def list_documents(profile_id: str, limit: int = 10) -> list[dict]:
    async with _client(profile_id) as c:
        return await _handle(await c.get(f"{API_BASE}/documents", params={"limit": limit}))


async def submit(doc_id: str, profile_id: str) -> dict:
    async with _client(profile_id) as c:
        return await _handle(await c.post(f"{API_BASE}/documents/{doc_id}/submit"))


# ---------- уведомления о решениях деканата ----------

async def pending_notifications() -> list[dict]:
    async with _client() as c:
        return await _handle(await c.get(f"{API_BASE}/notifications/pending"))


async def notification_sent(nid: int, error: str = "") -> None:
    async with _client() as c:
        await _handle(await c.post(f"{API_BASE}/notifications/{nid}/sent", json={"error": error}))
