from __future__ import annotations

from dataclasses import dataclass

from .models import PromptVersion, RefinementFeedback
from .prompt_store import PromptStore


@dataclass(slots=True)
class RefinementResult:
    accepted: bool
    prompt_version: PromptVersion
    feedback: RefinementFeedback


class RefinementLoop:
    def __init__(self, store: PromptStore, *, min_score: float = 0.8) -> None:
        self._store = store
        self._min_score = min_score

    def evaluate(self, prompt_text: str) -> RefinementFeedback:
        issues: list[str] = []
        if "Do not invent" not in prompt_text:
            issues.append("missing anti-hallucination guardrail")
        if "ask a focused follow-up question" not in prompt_text:
            issues.append("missing clarification behavior")

        score = max(0.0, 1.0 - (0.2 * len(issues)))
        suggestion = "Add explicit guardrails and clarification rules." if issues else "Prompt is stable."
        return RefinementFeedback(score=score, issues=issues, suggestion=suggestion)

    def propose_update(self, prompt_text: str, feedback: RefinementFeedback) -> str:
        updated = prompt_text.rstrip()
        if "missing anti-hallucination guardrail" in feedback.issues:
            updated += "\n- Do not invent facts, booking references, or inventory."
        if "missing clarification behavior" in feedback.issues:
            updated += "\n- Ask one focused follow-up question when details are missing."
        return updated + "\n"

    def run_once(self) -> RefinementResult:
        current = self._store.load_current()
        feedback = self.evaluate(current.prompt_text)
        if feedback.score >= self._min_score:
            return RefinementResult(accepted=True, prompt_version=current, feedback=feedback)

        updated_text = self.propose_update(current.prompt_text, feedback)
        next_version = self._store.save_new_version(updated_text)
        return RefinementResult(accepted=False, prompt_version=next_version, feedback=feedback)

