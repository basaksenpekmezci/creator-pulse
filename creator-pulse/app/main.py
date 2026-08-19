"""
FastAPI giriş noktası. Çalıştırmak için:
    uvicorn app.main:app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.database import init_db
from app.routers import connect, dashboard, sync
from app.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Creator Pulse", lifespan=lifespan)

app.include_router(sync.router)
app.include_router(connect.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def serve_dashboard():
    return FileResponse("templates/dashboard.html")
