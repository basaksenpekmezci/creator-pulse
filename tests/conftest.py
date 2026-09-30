"""
Ortak test fikstürleri. Testler gerçek veritabanına ya da ağa dokunmaz:
her test kendi bellek içi SQLite veritabanını alır.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - tabloların Base.metadata'ya kaydolması için
from app import scheduler
from app.config import get_settings
from app.database import Base, get_db
from app.routers import connect

# Testler için sabit bir Fernet anahtarı. ENCRYPTION_KEY zorunlu olduğunda da
# token şifreleme testleri gerçek .env'e ihtiyaç duymadan çalışabilsin.
TEST_ENCRYPTION_KEY = "dGVzdC1hbmFodGFyaS0zMi1iYXl0LXV6dW5sdWd1bmQ="


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    get_settings.cache_clear()
    yield TEST_ENCRYPTION_KEY
    get_settings.cache_clear()


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # scheduler.py job'ları SessionLocal'ı doğrudan çağırıyor.
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(session_factory):
    # app.main yerine sadece connect router'ını içeren bir uygulama kuruyoruz,
    # böylece lifespan içindeki gerçek scheduler başlamıyor.
    app = FastAPI()
    app.include_router(connect.router)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    connect._pending_states.clear()
    yield TestClient(app)
    connect._pending_states.clear()
