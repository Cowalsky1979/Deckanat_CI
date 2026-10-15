"""Профиль кабинета по заголовку X-Profile-Id (входа нет, демо-режим)."""
from __future__ import annotations

import uuid

from rest_framework.exceptions import PermissionDenied

from .models import Profile

HEADER = "X-Profile-Id"


def current_profile(request) -> Profile | None:
    """Профиль из заголовка (или ?profile_id= для ссылок на скачивание); неизвестный id считается анонимом."""
    if hasattr(request, "_profile"):
        return request._profile
    profile = None
    raw = request.headers.get(HEADER, "") or request.GET.get("profile_id", "")
    try:
        profile = Profile.objects.filter(pk=uuid.UUID(raw)).first() if raw else None
    except ValueError:
        profile = None
    request._profile = profile
    return profile


def require_profile(request, role: str | None = None) -> Profile:
    profile = current_profile(request)
    if profile is None:
        raise PermissionDenied("Нужен профиль кабинета: выберите роль на странице «Кабинет»")
    if role and profile.role != role:
        names = {Profile.Role.DEAN: "сотрудникам деканата", Profile.Role.STUDENT: "студентам"}
        raise PermissionDenied(f"Доступно только {names.get(role, role)}")
    return profile
