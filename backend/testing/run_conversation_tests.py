from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from elevenlabs import ElevenLabs

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTING_ROOT = BACKEND_ROOT / "testing"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.chat.elevenlabs import ElevenLabsChatAgent  # noqa: E402
from agents.config import get_agent_settings  # noqa: E402
from testing.refinement.agents.critic import evaluate_artifact  # noqa: E402
from testing.refinement.agents.customer_agent import CustomerSimulator  # noqa: E402
from testing.refinement.agents.root_cause_evaluator import evaluate_root_cause  # noqa: E402
from testing.tasks import CapabilityTask, TASKS, get_task  # noqa: E402


Role = Literal["user", "agent", "user_transcript"]
BOOKING_REFERENCE_PATTERN = re.compile(r"\b[A-Z0-9]{8,12}\b")


@dataclass
class TranscriptEntry:
    role: Role
    text: str
    timestamp: str


class TranscriptRecorder:
    def __init__(self, *, live_output: bool = True, event_sink: Callable[[dict], None] | None = None) -> None:
        self.entries: list[TranscriptEntry] = []
        self._lock = Lock()
        self._agent_event = Event()
        self._last_agent_count = 0
        self._live_output = live_output
        self._event_sink = event_sink
        self._last_entry_ts = time.time()

    def add_user_message(self, text: str) -> None:
        self._append("user", text)

    def on_agent_response(self, text: str) -> None:
        self._append("agent", text)
        self._agent_event.set()

    def on_user_transcript(self, text: str) -> None:
        self._append("user_transcript", text)

    def _append(self, role: Role, text: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.entries.append(
                TranscriptEntry(
                    role=role,
                    text=text,
                    timestamp=timestamp,
                )
            )
            self._last_entry_ts = time.time()
        if self._live_output:
            print(f"{role}: {text}")
        if self._event_sink:
            self._event_sink(
                {
                    "type": "transcript_turn",
                    "role": role,
                    "text": text,
                    "timestamp": timestamp,
                }
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

    def wait_until_quiet(self, quiet_window_seconds: float, timeout_seconds: float) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            with self._lock:
                idle_for = time.time() - self._last_entry_ts
            if idle_for >= quiet_window_seconds:
                return
            time.sleep(0.1)

    def agent_count(self) -> int:
        with self._lock:
            return sum(1 for entry in self.entries if entry.role == "agent")


def _outputs_dir() -> Path:
    output_dir = TESTING_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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


def _latest_agent_message(entries: list[TranscriptEntry]) -> str | None:
    for entry in reversed(entries):
        if entry.role == "agent":
            return entry.text
    return None


def _ensure_fresh_agent_turn(
    recorder: TranscriptRecorder,
    settings,
    conversation_id: str | None,
    *,
    last_seen_agent_count: int,
    response_timeout_seconds: float,
    settle_timeout_seconds: float,
    quiet_window_seconds: float,
) -> int | None:
    current_agent_count = recorder.agent_count()
    if current_agent_count > last_seen_agent_count:
        recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)
        return current_agent_count

    if recorder.wait_for_agent_activity(response_timeout_seconds):
        recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)
        current_agent_count = recorder.agent_count()
        return current_agent_count if current_agent_count > last_seen_agent_count else None

    remote_conversation = _poll_for_remote_turn_completion(
        settings,
        conversation_id,
        baseline_agent_count=last_seen_agent_count,
        timeout_seconds=max(settle_timeout_seconds, 8.0),
    )
    current_agent_count = recorder.agent_count()
    if current_agent_count > last_seen_agent_count:
        recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)
        return current_agent_count
    if _has_meaningful_remote_agent_turn(remote_conversation, last_seen_agent_count):
        recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)
        current_agent_count = recorder.agent_count()
        return current_agent_count if current_agent_count > last_seen_agent_count else None
    return None


def _wait_for_agent_turn(
    recorder: TranscriptRecorder,
    settings,
    conversation_id: str | None,
    *,
    baseline_agent_count: int,
    timeout_seconds: float,
    settle_timeout_seconds: float,
    initial_message: str,
) -> bool:
    got_agent_response = recorder.wait_for_agent_activity(timeout_seconds)
    if not got_agent_response and recorder.agent_count() > baseline_agent_count:
        got_agent_response = True
    if got_agent_response:
        return True

    remote_conversation = _poll_for_remote_turn_completion(
        settings,
        conversation_id,
        baseline_agent_count=baseline_agent_count,
        timeout_seconds=max(settle_timeout_seconds, 8.0),
    )
    if recorder.agent_count() > baseline_agent_count:
        return True
    if not _has_meaningful_remote_agent_turn(remote_conversation, baseline_agent_count):
        return False
    return True


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
        "prompt_updated_at": datetime.fromtimestamp(prompt_path.stat().st_mtime, timezone.utc).isoformat(),
    }


def _emit_event(event_sink: Callable[[dict], None] | None, event_type: str, **payload: object) -> None:
    if not event_sink:
        return
    event_sink({"type": event_type, **payload})


def _customer_context(task: CapabilityTask) -> dict:
    if task.slug == "book_flight":
        return {
            "full_name": "Eleni Pappas",
            "first_name": "Eleni",
            "last_name": "Pappas",
            "email": "eleni.pappas@example.com",
            "phone": "+306944001122",
            "date_of_birth": "1992-04-16",
            "passenger_count": 1,
            "passenger_type": "adult",
            "extras": "No extras.",
        }
    if task.slug == "cancel_or_reschedule_booking":
        return {
            "booking_reference": "TMQ7L5N8",
            "confirm_reschedule": "Yes, move me to the best available option after my current booking date.",
            "fallback_cancel": "If nothing suitable is available after my current booking date, cancel it instead.",
        }
    if task.slug == "add_baggage_or_special_items":
        return {
            "booking_reference": "TMX4A92K",
            "extra_request": "one extra checked bag",
            "confirmation": "Yes, please add it to the booking.",
        }
    if task.slug == "retrieve_booking_by_reference":
        return {
            "booking_reference": "TMQ7L5N8",
        }
    if task.slug == "search_available_flights":
        return {
            "origin": "FCO",
            "destination": "ATH",
            "cabin": "premium economy",
            "booking_intent": "I am only comparing options right now, not booking.",
        }
    return {}


def _fetch_booking_snapshot(settings, booking_reference: str | None) -> dict | None:
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


def _fetch_flight_snapshot(settings, flight_id: int | None) -> dict | None:
    if flight_id is None or not settings.backend_public_url:
        return None
    url = f"{settings.backend_public_url.rstrip('/')}/api/flights/{flight_id}"
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"flight_id": flight_id, "verified": False, "error": str(exc), "url": url}

    return {
        "flight_id": flight_id,
        "verified": True,
        "flight_number": payload.get("flight_number"),
        "origin_airport": payload.get("origin_airport"),
        "destination_airport": payload.get("destination_airport"),
        "departure_time": payload.get("departure_time"),
        "arrival_time": payload.get("arrival_time"),
        "seat_class": payload.get("seat_class"),
        "price": payload.get("price"),
        "status": payload.get("status"),
        "url": url,
    }


def _build_backend_verification(
    task: CapabilityTask,
    *,
    verification_reference: str | None,
    before_snapshot: dict | None,
    after_snapshot: dict | None,
) -> dict | None:
    if not task.required_backend_effects:
        return None
    changed_fields: list[str] = []
    if before_snapshot and after_snapshot:
        for field in ("status", "flight_id", "seat_preferences", "extras_count"):
            if before_snapshot.get(field) != after_snapshot.get(field):
                changed_fields.append(field)

    effect_results = {
        "booking_created": bool(after_snapshot and after_snapshot.get("verified") and not before_snapshot),
        "booking_updated": bool(after_snapshot and after_snapshot.get("verified") and (changed_fields or before_snapshot)),
        "extras_updated": bool(
            before_snapshot
            and after_snapshot
            and before_snapshot.get("extras_count") != after_snapshot.get("extras_count")
        ),
    }
    return {
        "booking_reference": verification_reference,
        "required_effects": task.required_backend_effects,
        "before": before_snapshot,
        "after": after_snapshot,
        "changed_fields": changed_fields,
        "effect_results": {key: effect_results.get(key) for key in task.required_backend_effects},
    }


def run_task(
    task: CapabilityTask,
    *,
    message_delay_seconds: float,
    response_timeout_seconds: float,
    settle_timeout_seconds: float,
    quiet_window_seconds: float,
    live_output: bool,
    review_model: str,
    output_dir: Path | None = None,
    event_sink: Callable[[dict], None] | None = None,
) -> Path:
    settings = get_agent_settings()
    recorder = TranscriptRecorder(live_output=live_output, event_sink=event_sink)
    customer = CustomerSimulator(model=review_model)
    customer_context = _customer_context(task)

    # Change-booking flows need extra time because the agent now looks up the
    # existing booking first, then searches replacement options after the
    # original departure date before replying.
    if task.slug == "cancel_or_reschedule_booking":
        response_timeout_seconds = max(response_timeout_seconds, 35.0)
        settle_timeout_seconds = max(settle_timeout_seconds, 8.0)

    pre_snapshot = _fetch_booking_snapshot(settings, customer_context.get("booking_reference"))
    if task.slug == "cancel_or_reschedule_booking" and pre_snapshot and pre_snapshot.get("verified"):
        current_flight = _fetch_flight_snapshot(settings, pre_snapshot.get("flight_id"))
        if current_flight and current_flight.get("verified"):
            departure_time = current_flight.get("departure_time")
            departure_date = departure_time[:10] if isinstance(departure_time, str) and departure_time else None
            customer_context.update(
                {
                    "current_booking": pre_snapshot,
                    "current_flight": current_flight,
                    "current_booking_departure_time": departure_time,
                    "current_booking_departure_date": departure_date,
                    "current_booking_flight_number": current_flight.get("flight_number"),
                    "current_booking_origin": current_flight.get("origin_airport"),
                    "current_booking_destination": current_flight.get("destination_airport"),
                    "current_booking_seat_class": current_flight.get("seat_class"),
                }
            )
    agent = ElevenLabsChatAgent(
        settings,
        on_agent_response=recorder.on_agent_response,
        on_user_transcript=recorder.on_user_transcript,
    )

    agent.start()
    started_at = datetime.now(timezone.utc).isoformat()
    conversation_id = agent.conversation_id
    customer_reply_count = 0
    max_customer_replies = 8
    _emit_event(event_sink, "task_started", task=task.slug, conversation_id=conversation_id)

    try:
        if recorder.wait_for_agent_activity(message_delay_seconds):
            recorder.wait_until_quiet(quiet_window_seconds, settle_timeout_seconds)

        first_message = task.initial_user_intent
        _emit_event(event_sink, "user_turn", message=first_message, turn_index=1)
        baseline_agent_count = recorder.agent_count()
        recorder.add_user_message(first_message)
        agent.send(first_message)
        if not _wait_for_agent_turn(
            recorder,
            settings,
            conversation_id,
            baseline_agent_count=baseline_agent_count,
            timeout_seconds=response_timeout_seconds,
            settle_timeout_seconds=settle_timeout_seconds,
            initial_message=first_message,
        ):
            raise RuntimeError(f"Timed out waiting for the agent response after user message: {first_message}")

        processed_agent_count = 0
        while customer_reply_count < max_customer_replies:
            fresh_agent_count = _ensure_fresh_agent_turn(
                recorder,
                settings,
                conversation_id,
                last_seen_agent_count=processed_agent_count,
                response_timeout_seconds=response_timeout_seconds,
                settle_timeout_seconds=settle_timeout_seconds,
                quiet_window_seconds=quiet_window_seconds,
            )
            if fresh_agent_count is None:
                break

            latest_agent_message = _latest_agent_message(recorder.entries)
            decision = customer.decide(
                task={
                    "slug": task.slug,
                    "description": task.description,
                    "goal": task.goal,
                    "task_type": task.task_type,
                    "initial_user_intent": task.initial_user_intent,
                    "evaluation_focus": task.evaluation_focus,
                    "required_backend_effects": task.required_backend_effects,
                    "allowed_tools_hint": task.allowed_tools_hint,
                },
                customer_context=customer_context,
                transcript=[asdict(entry) for entry in recorder.entries],
                latest_assistant_message=latest_agent_message,
            )
            processed_agent_count = fresh_agent_count

            if decision.action == "done":
                break

            if decision.action == "wait":
                continue

            if decision.action == "reply":
                if decision.message is None:
                    raise RuntimeError("Customer simulator requested a reply without a message.")
                customer_reply_count += 1
                _emit_event(event_sink, "customer_reply", message=decision.message, reply_index=customer_reply_count)
                baseline_agent_count = recorder.agent_count()
                recorder.add_user_message(decision.message)
                agent.send(decision.message)
                if not _wait_for_agent_turn(
                    recorder,
                    settings,
                    conversation_id,
                    baseline_agent_count=baseline_agent_count,
                    timeout_seconds=response_timeout_seconds,
                    settle_timeout_seconds=settle_timeout_seconds,
                    initial_message=decision.message,
                ):
                    raise RuntimeError(f"Timed out waiting for the agent response after user message: {decision.message}")
                continue

            raise RuntimeError(f"Unsupported customer simulator action: {decision.action}")
    finally:
        conversation_id = agent.conversation_id or conversation_id
        agent.stop()

    finished_at = datetime.now(timezone.utc).isoformat()
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
    verification_reference = booking_reference or customer_context.get("booking_reference")
    post_snapshot = _fetch_booking_snapshot(settings, verification_reference)
    turn_metrics = _build_turn_metrics(compact_conversation, transcript)
    stats = _build_stats(transcript, tool_trace, compact_conversation)
    backend_verification = _build_backend_verification(
        task,
        verification_reference=verification_reference,
        before_snapshot=pre_snapshot if task.required_backend_effects else None,
        after_snapshot=post_snapshot if task.required_backend_effects else None,
    )

    payload = {
        "task": {
            "slug": task.slug,
            "description": task.description,
            "goal": task.goal,
            "task_type": task.task_type,
            "initial_user_intent": task.initial_user_intent,
            "evaluation_focus": task.evaluation_focus,
            "required_backend_effects": task.required_backend_effects,
            "allowed_tools_hint": task.allowed_tools_hint,
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
        "customer_context": customer_context,
        "transcript": transcript,
        "final_agent_message": final_agent_message,
        "booking_reference_detected": booking_reference,
        "tool_trace": tool_trace,
        "turn_metrics": turn_metrics,
        "stats": stats,
        "backend_verification": backend_verification,
        "elevenlabs_conversation": compact_conversation,
    }

    try:
        critique = evaluate_artifact(payload, model=review_model)
        _emit_event(event_sink, "evaluation_started", task=task.slug)
        root_cause = evaluate_root_cause(payload, critique=critique, model=review_model)
        payload["evaluator_verdict"] = critique.model_dump(mode="json")
        payload["root_cause"] = root_cause.model_dump(mode="json")
        payload["evaluation_error"] = None
        _emit_event(event_sink, "evaluation_complete", task=task.slug)
    except Exception as exc:  # pragma: no cover - runtime integration failure path
        payload["evaluator_verdict"] = None
        payload["root_cause"] = None
        payload["evaluation_error"] = str(exc)
        _emit_event(event_sink, "evaluation_error", task=task.slug, error=str(exc))

    target_output_dir = output_dir or _outputs_dir()
    target_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_output_dir / f"{_timestamp()}_{task.slug}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI-driven capability-task tests and store conversation artifacts.")
    parser.add_argument("--task", help="Capability task slug to run. If omitted, all tasks are run.")
    parser.add_argument("--scenario", help=argparse.SUPPRESS)
    parser.add_argument("--message-delay", type=float, default=1.0, help="Delay before the first user turn.")
    parser.add_argument("--response-timeout", type=float, default=20.0, help="How long to wait for agent output after each message.")
    parser.add_argument("--settle-timeout", type=float, default=6.0, help="How long to wait for final agent output after the last message.")
    parser.add_argument("--quiet-window", type=float, default=2.0, help="How long the conversation must stay idle before the current turn is considered complete.")
    parser.add_argument("--quiet", action="store_true", help="Disable live console printing while the task runs.")
    parser.add_argument("--stream-events", action="store_true", help="Emit structured JSON lines for live streaming consumers.")
    parser.add_argument("--review-model", default="openai:gpt-4o-mini", help="Model used for the customer simulator and post-run evaluation.")
    args = parser.parse_args()

    selected_task = args.task or args.scenario
    tasks = [get_task(selected_task)] if selected_task else list(TASKS)
    results: list[dict[str, str]] = []

    def emit_event(event: dict) -> None:
        if args.stream_events:
            print(json.dumps(event), flush=True)

    if args.stream_events:
        emit_event({"type": "run_started", "task_count": len(tasks), "selected_task": selected_task})

    for task in tasks:
        output_path = run_task(
            task,
            message_delay_seconds=args.message_delay,
            response_timeout_seconds=args.response_timeout,
            settle_timeout_seconds=args.settle_timeout,
            quiet_window_seconds=args.quiet_window,
            live_output=not args.quiet,
            review_model=args.review_model,
            event_sink=emit_event if args.stream_events else None,
        )
        results.append({"task": task.slug, "output": str(output_path)})

        if args.stream_events:
            emit_event({"type": "task_finished", "task": task.slug, "output": str(output_path)})

    if args.stream_events:
        emit_event({"type": "run_finished", "results": results})
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
