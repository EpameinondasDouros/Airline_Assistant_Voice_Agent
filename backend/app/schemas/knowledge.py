from pydantic import BaseModel


class KnowledgeArticleRead(BaseModel):
    id: int
    topic: str
    title: str
    content: str
    version: int
    is_active: bool

    model_config = {"from_attributes": True}
