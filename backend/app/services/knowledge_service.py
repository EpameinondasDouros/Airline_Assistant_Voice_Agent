from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.knowledge_article import KnowledgeArticle


class KnowledgeService:
    """Read-only knowledge base queries used by the agent and API layer."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_topics(self) -> list[str]:
        statement = (
            select(KnowledgeArticle.topic)
            .where(KnowledgeArticle.is_active.is_(True))
            .distinct()
            .order_by(KnowledgeArticle.topic)
        )
        return list(self.session.scalars(statement))

    def get_by_topic(self, topic: str) -> list[KnowledgeArticle]:
        statement = (
            select(KnowledgeArticle)
            .where(
                KnowledgeArticle.is_active.is_(True),
                KnowledgeArticle.topic == topic,
            )
            .order_by(KnowledgeArticle.title)
        )
        return list(self.session.scalars(statement))

    def search(self, query: str) -> list[KnowledgeArticle]:
        pattern = f"%{query.strip()}%"
        statement = (
            select(KnowledgeArticle)
            .where(
                KnowledgeArticle.is_active.is_(True),
                or_(
                    KnowledgeArticle.topic.ilike(pattern),
                    KnowledgeArticle.title.ilike(pattern),
                    KnowledgeArticle.content.ilike(pattern),
                ),
            )
            .order_by(KnowledgeArticle.topic, KnowledgeArticle.title)
        )
        return list(self.session.scalars(statement))
