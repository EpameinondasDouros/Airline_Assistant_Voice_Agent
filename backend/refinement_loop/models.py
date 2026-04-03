from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class RefinementFeedback:
    score: float
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class PromptVersion:
    version: int
    prompt_text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parent_version: int | None = None

