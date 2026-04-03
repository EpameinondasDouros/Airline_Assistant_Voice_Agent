from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import PromptVersion


@dataclass(slots=True)
class PromptStore:
    prompt_path: Path
    _versions: list[PromptVersion] = field(default_factory=list, init=False)

    def load_current(self) -> PromptVersion:
        if self._versions:
            return self._versions[-1]

        prompt_text = self.prompt_path.read_text(encoding="utf-8")
        current = PromptVersion(version=1, prompt_text=prompt_text)
        self._versions.append(current)
        return current

    def save_new_version(self, prompt_text: str) -> PromptVersion:
        parent_version = self._versions[-1].version if self._versions else None
        version = len(self._versions) + 1
        next_version = PromptVersion(
            version=version,
            prompt_text=prompt_text,
            parent_version=parent_version,
        )
        self.prompt_path.write_text(prompt_text, encoding="utf-8")
        self._versions.append(next_version)
        return next_version

    def versions(self) -> list[PromptVersion]:
        return list(self._versions)
