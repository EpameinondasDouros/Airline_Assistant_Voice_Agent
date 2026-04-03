from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
from pathlib import Path
from threading import Event, Lock
from typing import Literal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.config import get_agent_settings  # noqa: E402
from agents.elevenlabs_chat import ElevenLabsChatAgent  # noqa: E402
from testing.scenarios import SCENARIOS, Scenario, get_scenario  # noqa: E402


Role = Literal["user", "agent", "user_transcript"]


@dataclass
class TranscriptEntry:
    role: Role
    text: str
    timestamp: str


class TranscriptRecorder:
    def __init__(self) -> None:
        self.entries: list[TranscriptEntry] = []
        self._lock = Lock()
        self._agent_event = Event()
        self._last_agent_count = 0

    def add_user_message(self, text: str) -> None:
        self._append("user", text)

    def on_agent_response(self, text: str) -> None:
        self._append("agent", text)
        self._agent_event.set()

    def on_user_transcript(self, text: str) -> None:
        self._append("user_transcript", text)

    def _append(self, role: Role, text: str) -> None:
        with self._lock:
            self.entries.append(
                TranscriptEntry(
                    role=role,
                    text=text,
                    timestamp=datetime.now(UTC).isoformat(),
                )
            )

    def wait_for_agent_activity(self, timeout_seconds: float) -> bool:
        with self._lock:
            current_agent_count = sum(1 for entry in self.entries if entry.role == "agent")
        if current_agent_count > self._last_agent_count:
            self._last_agent_count = current_agent_count
            self._agent_event.clear()
            return True
        triggered = self._agent_event.wait(timeout_seconds)
        with self._lock:
            self._last_agent_count = sum(1 for entry in self.entries if entry.role == "agent")
        self._agent_event.clear()
        return triggered


def _outputs_dir() -> Path:
    output_dir = PROJECT_ROOT / "testing" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_scenario(
    scenario: Scenario,
    *,
    message_delay_seconds: float,
    response_timeout_seconds: float,
    settle_timeout_seconds: float,
) -> Path:
    settings = get_agent_settings()
    recorder = TranscriptRecorder()
    agent = ElevenLabsChatAgent(
        settings,
        on_agent_response=recorder.on_agent_response,
        on_user_transcript=recorder.on_user_transcript,
    )

    agent.start()
    started_at = datetime.now(UTC).isoformat()

    try:
        for message in scenario.messages:
            recorder.add_user_message(message)
            agent.send(message)
            recorder.wait_for_agent_activity(response_timeout_seconds)
            time.sleep(message_delay_seconds)

        recorder.wait_for_agent_activity(settle_timeout_seconds)
    finally:
        agent.stop()

    finished_at = datetime.now(UTC).isoformat()
    output_path = _outputs_dir() / f"{_timestamp()}_{scenario.slug}.json"
    payload = {
        "scenario": {
            "slug": scenario.slug,
            "description": scenario.description,
            "messages": scenario.messages,
        },
        "run": {
            "started_at": started_at,
            "finished_at": finished_at,
            "agent_id": settings.elevenlabs_agent_id,
        },
        "transcript": [asdict(entry) for entry in recorder.entries],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scripted ElevenLabs conversation tests and store transcripts.")
    parser.add_argument("--scenario", help="Scenario slug to run. If omitted, all scenarios are run.")
    parser.add_argument("--message-delay", type=float, default=1.0, help="Delay between scripted user turns.")
    parser.add_argument("--response-timeout", type=float, default=8.0, help="How long to wait for agent output after each message.")
    parser.add_argument("--settle-timeout", type=float, default=3.0, help="How long to wait for final agent output after the last message.")
    args = parser.parse_args()

    scenarios = [get_scenario(args.scenario)] if args.scenario else list(SCENARIOS)
    results: list[dict[str, str]] = []
    for scenario in scenarios:
        output_path = run_scenario(
            scenario,
            message_delay_seconds=args.message_delay,
            response_timeout_seconds=args.response_timeout,
            settle_timeout_seconds=args.settle_timeout,
        )
        results.append({"scenario": scenario.slug, "output": str(output_path)})

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
