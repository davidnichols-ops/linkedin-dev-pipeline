"""Data models for events and drafts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Event:
    """A normalized GitHub activity event from any source."""

    id: str  # globally unique: f"{source}:{repo}#{number}:{kind}:{event_id}"
    kind: str  # pr_opened | pr_merged | pr_reviewed | issue_opened | issue_commented | opportunity | ...
    source: str  # user | own_repo | upstream | linkedin
    repo: str  # owner/repo
    number: int | None = None
    actor: str = ""
    title: str = ""
    url: str = ""
    body: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    seen_at: datetime | None = None

    def to_db(self) -> tuple:
        return (
            self.id,
            self.kind,
            self.source,
            self.repo,
            self.number,
            self.actor,
            self.title,
            self.url,
            self.body,
            json.dumps(self.payload, default=str),
            self.created_at.isoformat() if self.created_at else None,
            self.seen_at.isoformat() if self.seen_at else None,
        )

    def summary(self) -> str:
        loc = f"{self.repo}#{self.number}" if self.number else self.repo
        return f"[{self.kind}] {loc} — {self.title}"


@dataclass
class Draft:
    """A LinkedIn post draft generated from one or more events."""

    id: str
    event_ids: list[str]
    category: str
    body: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "draft"  # draft | approved | rejected | published

    def to_db(self) -> tuple:
        return (
            self.id,
            json.dumps(self.event_ids),
            self.category,
            self.body,
            self.created_at.isoformat(),
            self.status,
        )

    @classmethod
    def from_db(cls, row: tuple) -> Draft:
        id_, event_ids_json, category, body, created_at, status = row
        return cls(
            id=id_,
            event_ids=json.loads(event_ids_json),
            category=category,
            body=body,
            created_at=datetime.fromisoformat(created_at),
            status=status,
        )

    def as_dict(self) -> dict:
        return asdict(self)
