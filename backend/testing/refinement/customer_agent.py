from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .debug_output import print_agent_json

try:
    from pydantic_ai import Agent
except ImportError as exc:  # pragma: no cover - import guard for local setup
    Agent = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


CustomerAction = Literal["reply", "wait", "done"]


class CustomerReply(BaseModel):
    action: CustomerAction = Field(description="Whether the customer should reply now, wait, or finish.")
    message: str | None = Field(default=None, description="Customer message to send when action is reply.")
    reason: str = Field(description="Short explanation of the action decision.")


PROMPT = """You are a realistic airline customer simulator.

You receive:
- a scripted testing scenario
- the running conversation transcript
- the latest assistant message

Your job:
- decide whether the customer should reply now
- only reply when the assistant asks for missing information, presents options, or requests confirmation
- do not interrupt normal assistant tool use with extra customer text
- if the assistant has already answered the user request, mark the action as done
- if the assistant is still searching, waiting, or using a tool, usually wait

Rules:
- Use the scenario messages as the source of customer intent and missing details.
- If the assistant asks for contact details, provide them from the scenario.
- If the assistant asks the customer to choose an option, respond with the next selection.
- If the assistant asks a confirmation question, answer yes or no based on the scenario.
- If the assistant gives a final result and nothing else is required, mark done.
- Keep replies short and natural.
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
    def __init__(self, *, model: str = "openai:gpt-4o-mini") -> None:
        self.model = model
        self._agent = _build_agent(model)

    def decide(
        self,
        *,
        scenario: dict,
        transcript: list[dict],
        pending_messages: list[str],
        latest_assistant_message: str | None,
    ) -> CustomerReply:
        prompt = {
            "scenario": scenario,
            "transcript": transcript,
            "pending_messages": pending_messages,
            "latest_assistant_message": latest_assistant_message,
        }
        result = self._agent.run_sync(
            "Decide the next customer action for this airline conversation.\n\n"
            + json.dumps(prompt, indent=2)
        )
        print_agent_json("customer_agent", result.output)
        return result.output
