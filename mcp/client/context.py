"""Schema context loading and summarization for the MCP client."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class SchemaSection:
    name: str
    text: str


class SchemaContext:
    """Loads the OCEL schema and builds a lightweight section index.

    The schema is small, so we keep a simple section list with a cached hash to
    avoid re-reading unchanged files.
    """

    def __init__(self, schema_path: Path) -> None:
        self.schema_path = Path(schema_path)
        self._hash: str | None = None
        self.sections: List[SchemaSection] = []
        self.index_summary: str = ""
        self.full_context_block: str = ""

    def load(self) -> None:
        content = self.schema_path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if checksum == self._hash:
            return

        data = json.loads(content)
        self.sections = self._build_sections(data)
        self.index_summary = self._build_index_summary(data)
        self.full_context_block = self._render_sections(self.sections)
        self._hash = checksum

    def _build_sections(self, data: dict) -> List[SchemaSection]:
        sections: List[SchemaSection] = []
        props = data.get("properties", {}) if isinstance(data, dict) else {}
        for key in ("eventTypes", "objectTypes", "events", "objects"):
            if key in props:
                pretty = json.dumps(props[key], indent=2, ensure_ascii=False)
                sections.append(SchemaSection(name=key, text=pretty))
        if "required" in data:
            pretty = json.dumps({"required": data["required"]}, indent=2, ensure_ascii=False)
            sections.append(SchemaSection(name="required", text=pretty))
        return sections

    def _build_index_summary(self, data: dict) -> str:
        props = data.get("properties", {}) if isinstance(data, dict) else {}
        parts = []
        for key in ("eventTypes", "objectTypes", "events", "objects"):
            if key in props:
                parts.append(f"{key}: {props[key].get('type', 'n/a')}")
        required = data.get("required", []) if isinstance(data, dict) else []
        if required:
            parts.append(f"required fields: {', '.join(required)}")
        return "; ".join(parts)

    def _render_sections(self, sections: List[SchemaSection]) -> str:
        return "\n\n".join(
            f"[Section: {section.name}]\n{section.text}" for section in sections
        )

    def as_context_block(self) -> str:
        """Return the full context block to send alongside questions."""
        self.load()
        return f"Esquema OCEL (resumen): {self.index_summary}\n\n{self.full_context_block}"
