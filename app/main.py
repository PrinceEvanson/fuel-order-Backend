from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import auth, client, files, review, sage

app = FastAPI(title="Fuel Order Automation")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(engine)

for r in (auth.router, client.router, review.router, files.router, sage.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}
