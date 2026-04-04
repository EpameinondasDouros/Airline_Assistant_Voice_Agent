from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from ..core.debug_output import print_agent_json

try:
    from pydantic_ai import Agent
except ImportError as exc:  # pragma: no cover - import guard for local setup
    Agent = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


CustomerAction = Literal["reply", "wait", "done"]


class CustomerReply(BaseModel):
    action: CustomerAction = Field(description="Whether the customer should reply now, wait, or finish.")
    message: str | None = Field(default=None, description="Customer message to send when action is reply.")
    reason: str = Field(description="Short explanation of the action decision.")


PROMPT = """You are a realistic airline customer simulator used for capability-task testing.

You receive:
- a capability task definition
- a customer context with grounded facts you may use
- the running conversation transcript
- the latest assistant message

Your job:
- stay in role as a real customer
- help move the task toward completion without exposing test internals
- provide realistic missing details only when the assistant asks for them
- confirm or reject actions naturally when asked
- stop once the task goal is clearly satisfied, clearly blocked, or the assistant has already given the needed answer

Rules:
- Use the customer_context facts when the assistant asks for personal details, booking references, confirmations, or preferences.
- Do not volunteer extra information unless the assistant asks for it or it is needed to unblock the task.
- For search-only tasks, do not turn the conversation into a booking unless the task explicitly requires booking.
- For change_booking tasks, the assistant should retrieve the existing booking first. If it has not done that yet, do not accept a replacement option; wait or ask it to check the booking first.
- When change_booking tasks include a current booking departure time in customer_context, treat that as the baseline and only accept replacement flights that depart after that date/time.
- If the assistant offers cancellation instead of rescheduling, confirm it only when the task context says cancellation is an acceptable fallback.
- If the assistant has already completed the task and asks whether anything else is needed, send one final closing reply such as "No, that's all, thank you." before finishing.
- If the assistant is still searching, using tools, or obviously mid-turn, usually return wait.
- Never reply twice in a row without a fresh assistant response in between.
- Keep replies short, natural, and consistent with earlier customer answers in the transcript.
"""


def _build_agent(model: str) -> Agent[None, CustomerReply]:
    if Agent is None:  # pragma: no cover - guarded at runtime
        raise RuntimeError(
            "pydantic-ai is not installed. Install it before using the customer simulator."
        ) from _IMPORT_ERROR
    return Agent(
        model,
        output_type=CustomerReply,
        system_prompt=PROMPT,
    )


class CustomerSimulator:
    def __init__(self, *, model: str = "openai:gpt-5-nano") -> None:
        self.model = model
        self._agent = _build_agent(model)

    def decide(
        self,
        *,
        task: dict,
        customer_context: dict,
        transcript: list[dict],
        latest_assistant_message: str | None,
    ) -> CustomerReply:
        prompt = {
            "task": task,
            "customer_context": customer_context,
            "transcript": transcript,
            "latest_assistant_message": latest_assistant_message,
        }
        result = self._agent.run_sync(
            "Decide the next customer action for this airline testing task.\n\n"
            + json.dumps(prompt, indent=2)
        )
        print_agent_json("customer_agent", result.output)
        return result.output
