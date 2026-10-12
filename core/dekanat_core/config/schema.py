"""Схема конфига типов документов."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from ..settings import CONFIG_DIR

FieldType = Literal[
    "text", "person_name", "date", "int", "enum", "doc_number", "group", "signature", "seal"
]
MARK_TYPES = {"signature", "seal"}


class FieldSpec(BaseModel):
    key: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    type: FieldType = "text"
    values: list[str] = Field(default_factory=list)     # для enum
    rule: str                                           # пункт Положения, устанавливающий поле
    anchor: Optional[str] = None                        # якорная надпись для отметок
    pattern: Optional[str] = None

    @field_validator("key")
    @classmethod
    def _key_format(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[a-z_]+", v):
            raise ValueError(f"ключ поля должен быть из [a-z_]: {v!r}")
        return v

    @field_validator("rule")
    @classmethod
    def _rule_format(cls, v: str) -> str:
        import re
        v = str(v)
        if not re.fullmatch(r"\d+\.\d+", v):
            raise ValueError(f"rule должен иметь вид N.M: {v!r}")
        return v

    @property
    def is_mark(self) -> bool:
        return self.type in MARK_TYPES

    @property
    def search_names(self) -> list[str]:
        return [self.label, *self.aliases]


class DetectSpec(BaseModel):
    title_keywords: list[str] = Field(default_factory=list)
    label_keywords: list[str] = Field(default_factory=list)


class DocTypeConfig(BaseModel):
    key: str
    title: str
    rules_section: str = ""
    detect: DetectSpec = Field(default_factory=DetectSpec)
    complete_message_rules: list[str]
    not_required: dict[str, str] = Field(default_factory=dict)
    fields: list[FieldSpec]

    @field_validator("complete_message_rules", mode="before")
    @classmethod
    def _rules_str(cls, v):
        return [str(x) for x in v]

    @field_validator("not_required", mode="before")
    @classmethod
    def _nr_str(cls, v):
        return {k: str(x) for k, x in (v or {}).items()}

    @model_validator(mode="after")
    def _unique_keys(self):
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.key}: повторяющиеся ключи полей")
        return self

    @property
    def field_map(self) -> dict[str, FieldSpec]:
        return {f.key: f for f in self.fields}

    @property
    def text_fields(self) -> list[FieldSpec]:
        return [f for f in self.fields if not f.is_mark]

    @property
    def mark_fields(self) -> list[FieldSpec]:
        return [f for f in self.fields if f.is_mark]

    def public_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "rules_section": self.rules_section,
            "complete_message_rules": self.complete_message_rules,
            "fields": [
                {"key": f.key, "label": f.label, "type": f.type, "rule": f.rule, "is_mark": f.is_mark}
                for f in self.fields
            ],
        }


def load_doc_type(path: Path) -> DocTypeConfig:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    try:
        return DocTypeConfig.model_validate(raw)
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"Ошибка в конфиге типа документа {path.name}: {exc}") from exc


@lru_cache(maxsize=1)
def load_doc_types(config_dir: Optional[Path] = None) -> dict[str, DocTypeConfig]:
    d = Path(config_dir or CONFIG_DIR) / "doc_types"
    types: dict[str, DocTypeConfig] = {}
    for path in sorted(d.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        cfg = load_doc_type(path)
        if cfg.key in types:
            raise ValueError(f"Дублирующийся тип документа {cfg.key} в {path.name}")
        types[cfg.key] = cfg
    if not types:
        raise ValueError(f"В {d} не найдено ни одного конфига типа документа")
    return types


def get_doc_type(key: str) -> DocTypeConfig:
    types = load_doc_types()
    if key not in types:
        raise KeyError(f"Неизвестный тип документа: {key}. Доступны: {', '.join(types)}")
    return types[key]
