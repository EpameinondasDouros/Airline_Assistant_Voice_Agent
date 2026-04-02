from __future__ import annotations

import json

from elevenlabs import (
    AgentDeploymentPercentageStrategy,
    AgentDeploymentRequest,
    AgentDeploymentRequestItem,
    ElevenLabs,
)

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

    deployment = client.conversational_ai.agents.deployments.create(
        agent_id=settings.elevenlabs_agent_id,
        deployment_request=AgentDeploymentRequest(
            requests=[
                AgentDeploymentRequestItem(
                    branch_id=branch_id,
                    deployment_strategy=AgentDeploymentPercentageStrategy(
                        traffic_percentage=1.0,
                        type="percentage",
                    ),
                )
            ]
        ),
    )

    print(
        json.dumps(
            {
                "agent_id": settings.elevenlabs_agent_id,
                "branch_id": branch_id,
                "deployment": getattr(deployment, "traffic_percentage_branch_id_map", None),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
