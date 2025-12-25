from fastapi import FastAPI
from .config import settings
from .db import init_db

app = FastAPI(title="Conway GitHub Warning System (v1)")

@app.on_event("startup")
async def on_startup():
    await init_db(settings.DB_PATH)

@app.get("/health")
async def health():
    return {"ok": True}

