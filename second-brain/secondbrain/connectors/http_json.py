"""Generic JSON REST API connector.

Pulls records from any API that returns JSON (CRM notes, Notion/Confluence/Jira
exports, ticketing systems, internal services) without writing code:

    [[sources]]
    name = "crm-notes"
    type = "http_json"
    url = "https://api.example.com/v1/notes?limit=500"
    headers = { Authorization = "Bearer ${CRM_TOKEN}" }
    items_path = "data"          # dot path to the list of records
    id_field = "id"
    title_field = "title"
    text_fields = ["body", "summary"]
    updated_field = "updated_at"
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterator

from . import Item
from .web import fetch


def dig(obj: Any, path: str) -> Any:
    for part in [p for p in path.split(".") if p]:
        obj = obj[int(part)] if isinstance(obj, list) else obj.get(part) if isinstance(obj, dict) else None
        if obj is None:
            return None
    return obj


def _as_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class HttpJsonConnector:
    def __init__(self, name: str, options: dict[str, Any]):
        self.name = name
        self.url: str = options["url"]
        self.headers: dict[str, str] = options.get("headers", {})
        self.items_path: str = options.get("items_path", "")
        self.id_field: str = options.get("id_field", "id")
        self.title_field: str = options.get("title_field", "title")
        self.text_fields: list[str] = options.get("text_fields", [options.get("text_field", "text")])
        self.updated_field: str | None = options.get("updated_field")

    def items(self) -> Iterator[Item]:
        body, _ = fetch(self.url, headers=self.headers)
        records = dig(json.loads(body), self.items_path) if self.items_path else json.loads(body)
        if not isinstance(records, list):
            raise ValueError(f"{self.name}: items_path '{self.items_path}' did not resolve to a list")
        for rec in records:
            rid = dig(rec, self.id_field)
            title = str(dig(rec, self.title_field) or rid)
            parts = [f"# {title}"] + [str(v) for f in self.text_fields if (v := dig(rec, f))]
            text = "\n\n".join(parts).encode("utf-8")
            updated = _as_timestamp(dig(rec, self.updated_field)) if self.updated_field else None
            yield Item(uri=f"{self.name}:{rid}", title=title, ext=".md", modified=updated,
                       load=lambda t=text: t)
