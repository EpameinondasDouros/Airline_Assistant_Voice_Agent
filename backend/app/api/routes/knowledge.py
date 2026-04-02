from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas.knowledge import KnowledgeArticleRead
from app.services.knowledge_service import KnowledgeService


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/topics", response_model=list[str])
def list_topics(session: Session = Depends(get_db_session)) -> list[str]:
    service = KnowledgeService(session)
    return service.list_topics()


@router.get("/search", response_model=list[KnowledgeArticleRead])
def search_articles(
    q: str = Query(..., min_length=2, description="Keyword search across topic, title, and article content."),
    session: Session = Depends(get_db_session),
) -> list[KnowledgeArticleRead]:
    service = KnowledgeService(session)
    return service.search(q)


@router.get("/{topic}", response_model=list[KnowledgeArticleRead])
def get_topic_articles(topic: str, session: Session = Depends(get_db_session)) -> list[KnowledgeArticleRead]:
    service = KnowledgeService(session)
    articles = service.get_by_topic(topic)
    if not articles:
        raise HTTPException(status_code=404, detail=f"No knowledge articles found for topic '{topic}'.")
    return articles
