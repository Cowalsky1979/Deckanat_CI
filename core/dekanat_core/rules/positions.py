"""Парсит rules.md в словарь {"3.1": "текст"}."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..settings import rules_path

_ITEM_RE = re.compile(r"^(\d+\.\d+)\.\s+(.*)$")
_SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.*)$")


@dataclass
class Rule:
    id: str
    text: str
    section: str
    section_title: str

    @property
    def ref(self) -> str:
        return f"rule:{self.id}"


@dataclass
class Positions:
    title: str
    rules: dict[str, Rule]
    sections: dict[str, str]

    def get(self, rule_id: str) -> Rule | None:
        return self.rules.get(rule_id.replace("rule:", ""))

    def text(self, rule_id: str) -> str:
        r = self.get(rule_id)
        return r.text if r else ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sections": [{"id": sid, "title": t, "rules": [
                {"id": r.id, "text": r.text} for r in self.rules.values() if r.section == sid
            ]} for sid, t in self.sections.items()],
        }


def parse(markdown: str) -> Positions:
    title = ""
    rules: dict[str, Rule] = {}
    sections: dict[str, str] = {}
    cur_section, cur_title = "", ""
    for line in markdown.splitlines():
        line = line.rstrip()
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        m = _SECTION_RE.match(line)
        if m:
            cur_section, cur_title = m.group(1), m.group(2).strip()
            sections[cur_section] = cur_title
            continue
        m = _ITEM_RE.match(line)
        if m:
            rid, text = m.group(1), m.group(2).strip()
            rules[rid] = Rule(id=rid, text=text, section=cur_section, section_title=cur_title)
    return Positions(title=title, rules=rules, sections=sections)


@lru_cache(maxsize=1)
def load_positions() -> Positions:
    return parse(rules_path().read_text(encoding="utf-8"))
