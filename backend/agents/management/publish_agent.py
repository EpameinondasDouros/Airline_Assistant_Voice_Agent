from __future__ import annotations

import json

from elevenlabs import (
    AgentDeploymentPercentageStrategy,
    AgentDeploymentRequest,
    AgentDeploymentRequestItem,
    ElevenLabs,
)
from elevenlabs.core.api_error import ApiError

from agents.config import get_agent_settings


def main() -> None:
    settings = get_agent_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY is required.")
    if not settings.elevenlabs_agent_id:
        raise ValueError("ELEVENLABS_AGENT_ID is required.")

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    agent = client.conversational_ai.agents.get(settings.elevenlabs_agent_id)

    branch_id = getattr(agent, "branch_id", None) or getattr(agent, "main_branch_id", None)
    if not branch_id:
        raise ValueError("Could not determine the current agent branch id to deploy.")

    try:
        deployment = client.conversational_ai.agents.deployments.create(
            agent_id=settings.elevenlabs_agent_id,
            deployment_request=AgentDeploymentRequest(
                requests=[
                    AgentDeploymentRequestItem(
                        branch_id=branch_id,
                        deployment_strategy=AgentDeploymentPercentageStrategy(
                            traffic_percentage=100.0,
                            type="percentage",
                        ),
                    )
                ]
            ),
        )
        result = {
            "agent_id": settings.elevenlabs_agent_id,
            "branch_id": branch_id,
            "published": True,
            "deployment": getattr(deployment, "traffic_percentage_branch_id_map", None),
        }
    except ApiError as exc:
        if exc.status_code != 405:
            raise
        result = {
            "agent_id": settings.elevenlabs_agent_id,
            "branch_id": branch_id,
            "published": False,
            "reason": "deployment_api_not_available",
            "message": (
                "This ElevenLabs workspace/API does not allow publish via the deployments endpoint. "
                "The agent config can still be synced from Python; publish the draft from the ElevenLabs dashboard if needed."
            ),
        }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
