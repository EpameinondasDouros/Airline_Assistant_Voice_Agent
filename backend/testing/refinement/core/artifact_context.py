from __future__ import annotations

from typing import Any


def compact_elevenlabs_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    conversation = payload.get("elevenlabs_conversation") or {}
    analysis = conversation.get("analysis") or {}
    metadata = conversation.get("metadata") or {}
    return {
        "call_successful": analysis.get("call_successful"),
        "call_summary_title": analysis.get("call_summary_title"),
        "transcript_summary": analysis.get("transcript_summary"),
        "transcript": conversation.get("transcript") or [],
        "termination_reason": metadata.get("termination_reason"),
        "conversation_status": conversation.get("status"),
    }
