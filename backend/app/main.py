from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.admin import router as admin_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.flights import router as flights_router
from app.api.routes.knowledge import router as knowledge_router
from app.config import get_settings


settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(flights_router, prefix=settings.api_prefix)
app.include_router(bookings_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
