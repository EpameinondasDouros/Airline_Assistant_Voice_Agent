from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class ChatEvent:
    event_type: str
    payload: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
