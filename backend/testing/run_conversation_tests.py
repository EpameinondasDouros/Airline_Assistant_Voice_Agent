from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
from pathlib import Path
from threading import Event, Lock
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from elevenlabs import ElevenLabs

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTING_ROOT = BACKEND_ROOT / "testing"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.config import get_agent_settings  # noqa: E402
from agents.elevenlabs_chat import ElevenLabsChatAgent  # noqa: E402
from testing.scenarios import SCENARIOS, Scenario, get_scenario  # noqa: E402


Role = Literal["user", "agent", "user_transcript"]
BOOKING_REFERENCE_PATTERN = re.compile(r"\b[A-Z0-9]{8,12}\b")


@dataclass
class TranscriptEntry:
    role: Role
    text: str
    timestamp: str


class TranscriptRecorder:
    def __init__(self, *, live_output: bool = True) -> None:
        self.entries: list[TranscriptEntry] = []
        self._lock = Lock()
        self._agent_event = Event()
        self._last_agent_count = 0
        self._live_output = live_output
        self._last_entry_ts = time.time()

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
            self._last_entry_ts = time.time()
        if self._live_output:
            print(f"{role}: {text}")

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

    def wait_until_quiet(self, quiet_window_seconds: float, timeout_seconds: float) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            with self._lock:
                idle_for = time.time() - self._last_entry_ts
            if idle_for >= quiet_window_seconds:
                return
            time.sleep(0.1)

    def has_agent_entries(self) -> bool:
        with self._lock:
            return any(entry.role == "agent" for entry in self.entries)

    def agent_count(self) -> int:
        with self._lock:
            return sum(1 for entry in self.entries if entry.role == "agent")


def _outputs_dir() -> Path:
    output_dir = TESTING_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _model_to_jsonable(value: object) -> object:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _compact_tool_call(tool_call: dict) -> dict:
    tool_details = tool_call.get("tool_details") or {}
    return {
        "tool_name": tool_call.get("tool_name"),
        "params_as_json": tool_call.get("params_as_json"),
        "type": tool_call.get("type"),
        "request_id": tool_call.get("request_id"),
        "tool_has_been_called": tool_call.get("tool_has_been_called"),
        "tool_details": {
            "type": tool_details.get("type"),
            "method": tool_details.get("method"),
            "url": tool_details.get("url"),
            "path_params": tool_details.get("path_params"),
            "query_params": tool_details.get("query_params"),
        },
    }


def _compact_tool_result(tool_result: dict) -> dict:
    return {
        "tool_name": tool_result.get("tool_name"),
        "request_id": tool_result.get("request_id"),
        "tool_has_been_called": tool_result.get("tool_has_been_called"),
        "is_error": tool_result.get("is_error"),
        "tool_latency_secs": tool_result.get("tool_latency_secs"),
        "error_type": tool_result.get("error_type"),
        "result_value": tool_result.get("result_value"),
    }


def _compact_transcript_item(item: dict) -> dict:
    return {
        "role": item.get("role"),
        "message": item.get("message"),
        "original_message": item.get("original_message"),
        "time_in_call_secs": item.get("time_in_call_secs"),
        "interrupted": item.get("interrupted"),
        "tool_calls": [_compact_tool_call(tool_call) for tool_call in (item.get("tool_calls") or [])],
        "tool_results": [_compact_tool_result(tool_result) for tool_result in (item.get("tool_results") or [])],
    }


def _compact_conversation_history(conversation: dict | None) -> dict | None:
    if not conversation:
        return None

    metadata = conversation.get("metadata") or {}
    analysis = conversation.get("analysis") or {}
    return {
        "agent_id": conversation.get("agent_id"),
        "agent_name": conversation.get("agent_name"),
        "conversation_id": conversation.get("conversation_id"),
        "status": conversation.get("status"),
        "branch_id": conversation.get("branch_id"),
        "version_id": conversation.get("version_id"),
        "environment": conversation.get("environment"),
        "metadata": {
            "call_duration_secs": metadata.get("call_duration_secs"),
            "cost": metadata.get("cost"),
            "termination_reason": metadata.get("termination_reason"),
            "main_language": metadata.get("main_language"),
            "text_only": metadata.get("text_only"),
            "conversation_initiation_source": metadata.get("conversation_initiation_source"),
        },
        "analysis": {
            "call_successful": analysis.get("call_successful"),
            "call_summary_title": analysis.get("call_summary_title"),
            "transcript_summary": analysis.get("transcript_summary"),
        },
        "transcript": [_compact_transcript_item(item) for item in conversation.get("transcript", [])],
    }


def _fetch_conversation_history(settings, conversation_id: str | None) -> dict | None:
    if not conversation_id:
        return None
    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    conversation = client.conversational_ai.conversations.get(conversation_id)
    return _model_to_jsonable(conversation)


def _has_meaningful_remote_agent_turn(conversation: dict | None, baseline_agent_count: int) -> bool:
    if not conversation:
        return False
    transcript = conversation.get("transcript") or []
    agent_items = [item for item in transcript if item.get("role") == "agent"]
    if len(agent_items) <= baseline_agent_count:
        return False
    for item in agent_items[baseline_agent_count:]:
        if item.get("message") or item.get("original_message") or item.get("tool_calls") or item.get("tool_results"):
            return True
    return False


def _poll_for_remote_turn_completion(
    settings,
    conversation_id: str | None,
    *,
    baseline_agent_count: int,
    timeout_seconds: float,
    poll_interval_seconds: float = 1.0,
) -> dict | None:
    if not conversation_id:
        return None

    deadline = time.time() + timeout_seconds
    last_conversation: dict | None = None
    while time.time() < deadline:
        conversation = _fetch_conversation_history(settings, conversation_id)
        if conversation:
            last_conversation = conversation
            if _has_meaningful_remote_agent_turn(conversation, baseline_agent_count):
                return conversation
        time.sleep(poll_interval_seconds)
    return last_conversation


def _fetch_finalized_conversation_history(
    settings,
    conversation_id: str | None,
    *,
    timeout_seconds: float = 20.0,
    poll_interval_seconds: float = 1.0,
) -> dict | None:
    if not conversation_id:
        return None

    deadline = time.time() + timeout_seconds
    last_conversation: dict | None = None
    while time.time() < deadline:
        conversation = _fetch_conversation_history(settings, conversation_id)
        if conversation:
            last_conversation = conversation
            transcript = conversation.get("transcript") or []
            status = str(conversation.get("status") or "").lower()
            if status in {"done", "completed"} and transcript:
                return conversation
            if transcript and any(
                item.get("message") or item.get("original_message") or item.get("tool_calls") or item.get("tool_results")
                for item in transcript
            ) and status not in {"in-progress", "queued"}:
                return conversation
        time.sleep(poll_interval_seconds)
    return last_conversation


def _safe_json_loads(value: str | None) -> object:
    if not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _extract_tool_trace(conversation: dict | None) -> list[dict]:
    trace: list[dict] = []
    if not conversation:
        return trace
    for turn_index, item in enumerate(conversation.get("transcript", []), start=1):
        for tool_call in item.get("tool_calls") or []:
            trace.append(
                {
                    "kind": "tool_call",
                    "turn_index": turn_index,
                    "role": item.get("role"),
                    "tool_name": tool_call.get("tool_name"),
                    "request_id": tool_call.get("request_id"),
                    "params": _safe_json_loads(tool_call.get("params_as_json")),
                    "tool_has_been_called": tool_call.get("tool_has_been_called"),
                    "type": tool_call.get("type"),
                }
            )
        for tool_result in item.get("tool_results") or []:
            trace.append(
                {
                    "kind": "tool_result",
                    "turn_index": turn_index,
                    "role": item.get("role"),
                    "tool_name": tool_result.get("tool_name"),
                    "request_id": tool_result.get("request_id"),
                    "result": _safe_json_loads(tool_result.get("result_value")),
                    "is_error": tool_result.get("is_error"),
                    "error_type": tool_result.get("error_type"),
                    "tool_latency_secs": tool_result.get("tool_latency_secs"),
                    "tool_has_been_called": tool_result.get("tool_has_been_called"),
                }
            )
    return trace


def _extract_final_agent_message(conversation: dict | None, transcript: list[dict]) -> str | None:
    if conversation:
        for item in reversed(conversation.get("transcript", [])):
            if item.get("role") != "agent":
                continue
            if item.get("message"):
                return item.get("message")
            if item.get("original_message"):
                return item.get("original_message")
    for item in reversed(transcript):
        if item.get("role") == "agent":
            return item.get("text")
    return None


def _extract_booking_reference(final_agent_message: str | None, transcript: list[dict], tool_trace: list[dict]) -> str | None:
    candidates: list[str] = []
    if final_agent_message:
        candidates.extend(BOOKING_REFERENCE_PATTERN.findall(final_agent_message))
    for item in transcript:
        if item.get("role") == "agent":
            candidates.extend(BOOKING_REFERENCE_PATTERN.findall(item.get("text", "")))
    for item in tool_trace:
        if item.get("kind") == "tool_result":
            result = item.get("result")
            if isinstance(result, dict):
                for value in result.values():
                    if isinstance(value, str):
                        candidates.extend(BOOKING_REFERENCE_PATTERN.findall(value))
    for candidate in candidates:
        if candidate.startswith("TM") or len(candidate) >= 8:
            return candidate
    return None


def _build_turn_metrics(conversation: dict | None, transcript: list[dict]) -> list[dict]:
    if not conversation:
        return [
            {
                "turn_index": index,
                "role": item.get("role"),
                "message": item.get("text"),
                "has_tool_activity": False,
                "interrupted": False,
                "time_in_call_secs": None,
            }
            for index, item in enumerate(transcript, start=1)
        ]

    metrics: list[dict] = []
    for index, item in enumerate(conversation.get("transcript", []), start=1):
        metrics.append(
            {
                "turn_index": index,
                "role": item.get("role"),
                "message": item.get("message") or item.get("original_message"),
                "has_tool_activity": bool(item.get("tool_calls") or item.get("tool_results")),
                "tool_call_count": len(item.get("tool_calls") or []),
                "tool_result_count": len(item.get("tool_results") or []),
                "interrupted": item.get("interrupted"),
                "time_in_call_secs": item.get("time_in_call_secs"),
            }
        )
    return metrics


def _build_stats(transcript: list[dict], tool_trace: list[dict], conversation: dict | None) -> dict:
    agent_turns = sum(1 for item in transcript if item.get("role") == "agent")
    user_turns = sum(1 for item in transcript if item.get("role") == "user")
    tool_calls = [item for item in tool_trace if item["kind"] == "tool_call"]
    tool_results = [item for item in tool_trace if item["kind"] == "tool_result"]
    interrupted_count = 0
    total_duration = None
    if conversation:
        interrupted_count = sum(1 for item in conversation.get("transcript", []) if item.get("interrupted"))
        total_duration = ((conversation.get("metadata") or {}).get("call_duration_secs"))
    return {
        "user_turn_count": user_turns,
        "agent_turn_count": agent_turns,
        "tool_call_count": len(tool_calls),
        "tool_result_count": len(tool_results),
        "interruption_count": interrupted_count,
        "total_duration_secs": total_duration,
    }


def _contains_keywords(final_agent_message: str | None, keywords: list[str]) -> bool:
    if not final_agent_message:
        return False
    haystack = final_agent_message.lower()
    return all(keyword.lower() in haystack for keyword in keywords)


def _build_assertions(
    scenario: Scenario,
    transcript: list[dict],
    final_agent_message: str | None,
    tool_trace: list[dict],
    booking_reference: str | None,
) -> dict:
    called_tool_names = [item["tool_name"] for item in tool_trace if item["kind"] == "tool_call" and item.get("tool_name")]
    expected_tools_used = all(tool in called_tool_names for tool in scenario.expected_tools)
    return {
        "used_expected_tools": expected_tools_used,
        "called_tools": called_tool_names,
        "tool_call_count": len(called_tool_names),
        "agent_replied_after_user_message": any(item.get("role") == "agent" for item in transcript),
        "final_agent_message_present": bool(final_agent_message),
        "final_message_contains_expected_keywords": _contains_keywords(final_agent_message, scenario.expected_keywords),
        "booking_reference_detected": bool(booking_reference),
        "follow_up_question_detected": bool(final_agent_message and "?" in final_agent_message),
    }


def _fetch_backend_verification(settings, booking_reference: str | None) -> dict | None:
    if not booking_reference or not settings.backend_public_url:
        return None
    url = f"{settings.backend_public_url.rstrip('/')}/api/bookings/{booking_reference}"
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"booking_reference": booking_reference, "verified": False, "error": str(exc), "url": url}

    return {
        "booking_reference": booking_reference,
        "verified": True,
        "status": payload.get("status"),
        "flight_id": payload.get("flight_id"),
        "seat_preferences": [passenger.get("seat_preference") for passenger in payload.get("passengers", [])],
        "extras_count": len(payload.get("extras", [])),
        "url": url,
    }


def _git_commit_hash() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=BACKEND_ROOT,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            .strip()
        )
    except Exception:
        return None


def _prompt_metadata() -> dict:
    prompt_path = BACKEND_ROOT / "agents" / "prompts" / "flight_booking_agent.md"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    return {
        "prompt_path": str(prompt_path),
        "prompt_length_chars": len(prompt_text),
        "prompt_updated_at": datetime.fromtimestamp(prompt_path.stat().st_mtime, UTC).isoformat(),
    }


def run_scenario(
    scenario: Scenario,
    *,
    message_delay_seconds: float,
    response_timeout_seconds: float,
    settle_timeout_seconds: float,
    quiet_window_seconds: float,
    live_output: bool,
) -> Path:
    settings = get_agent_settings()
    recorder = TranscriptRecorder(live_output=live_output)
    agent = ElevenLabsChatAgent(
        settings,
        on_agent_response=recorder.on_agent_response,
        on_user_transcript=recorder.on_user_transcript,
    )

    agent.start()
    started_at = datetime.now(UTC).isoformat()
    conversation_id = agent.conversation_id

    try:
        if recorder.wait_for_agent_activity(message_delay_seconds):
            recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)

        for message in scenario.messages:
            baseline_agent_count = recorder.agent_count()
            recorder.add_user_message(message)
            agent.send(message)
            got_agent_response = recorder.wait_for_agent_activity(response_timeout_seconds)
            if not got_agent_response and recorder.agent_count() > baseline_agent_count:
                got_agent_response = True
            if not got_agent_response:
                remote_conversation = _poll_for_remote_turn_completion(
                    settings,
                    conversation_id,
                    baseline_agent_count=baseline_agent_count,
                    timeout_seconds=max(settle_timeout_seconds, 8.0),
                )
                if recorder.agent_count() > baseline_agent_count:
                    got_agent_response = True
                elif not _has_meaningful_remote_agent_turn(remote_conversation, baseline_agent_count):
                    raise RuntimeError(
                        f"Timed out waiting for the agent response after user message: {message}"
                    )
                else:
                    got_agent_response = True

            recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)
            time.sleep(message_delay_seconds)

        if recorder.has_agent_entries():
            recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)
    finally:
        conversation_id = agent.conversation_id or conversation_id
        agent.stop()

    finished_at = datetime.now(UTC).isoformat()
    conversation_data = _fetch_finalized_conversation_history(
        settings,
        conversation_id,
        timeout_seconds=max(response_timeout_seconds + settle_timeout_seconds + 5.0, 15.0),
    )
    compact_conversation = _compact_conversation_history(conversation_data)
    transcript = [asdict(entry) for entry in recorder.entries]
    tool_trace = _extract_tool_trace(compact_conversation)
    final_agent_message = _extract_final_agent_message(compact_conversation, transcript)
    booking_reference = _extract_booking_reference(final_agent_message, transcript, tool_trace)
    turn_metrics = _build_turn_metrics(compact_conversation, transcript)
    stats = _build_stats(transcript, tool_trace, compact_conversation)
    assertions = _build_assertions(scenario, transcript, final_agent_message, tool_trace, booking_reference)
    backend_verification = _fetch_backend_verification(settings, booking_reference) if scenario.mutation_expected else None
    output_path = _outputs_dir() / f"{_timestamp()}_{scenario.slug}.json"
    payload = {
        "scenario": {
            "slug": scenario.slug,
            "description": scenario.description,
            "messages": scenario.messages,
            "expected_tools": scenario.expected_tools,
            "expected_outcome": scenario.expected_outcome,
            "expected_keywords": scenario.expected_keywords,
            "mutation_expected": scenario.mutation_expected,
            "booking_reference_expected": scenario.booking_reference_expected,
            "follow_up_question_expected": scenario.follow_up_question_expected,
        },
        "run": {
            "started_at": started_at,
            "finished_at": finished_at,
            "agent_id": settings.elevenlabs_agent_id,
            "branch_id": settings.elevenlabs_branch_id,
            "conversation_id": conversation_id,
            "git_commit_hash": _git_commit_hash(),
            "prompt_metadata": _prompt_metadata(),
        },
        "transcript": transcript,
        "final_agent_message": final_agent_message,
        "booking_reference_detected": booking_reference,
        "tool_trace": tool_trace,
        "turn_metrics": turn_metrics,
        "stats": stats,
        "assertions": assertions,
        "backend_verification": backend_verification,
        "elevenlabs_conversation": compact_conversation,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scripted ElevenLabs conversation tests and store transcripts.")
    parser.add_argument("--scenario", help="Scenario slug to run. If omitted, all scenarios are run.")
    parser.add_argument("--message-delay", type=float, default=1.0, help="Delay between scripted user turns.")
    parser.add_argument("--response-timeout", type=float, default=20.0, help="How long to wait for agent output after each message.")
    parser.add_argument("--settle-timeout", type=float, default=6.0, help="How long to wait for final agent output after the last message.")
    parser.add_argument("--quiet-window", type=float, default=2.0, help="How long the conversation must stay idle before the current turn is considered complete.")
    parser.add_argument("--quiet", action="store_true", help="Disable live console printing while the scenario runs.")
    args = parser.parse_args()

    scenarios = [get_scenario(args.scenario)] if args.scenario else list(SCENARIOS)
    results: list[dict[str, str]] = []
    for scenario in scenarios:
        output_path = run_scenario(
            scenario,
            message_delay_seconds=args.message_delay,
            response_timeout_seconds=args.response_timeout,
            settle_timeout_seconds=args.settle_timeout,
            quiet_window_seconds=args.quiet_window,
            live_output=not args.quiet,
        )
        results.append({"scenario": scenario.slug, "output": str(output_path)})

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
