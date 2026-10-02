"""
Ortak test fikstürleri. Testler gerçek veritabanına ya da ağa dokunmaz:
her test kendi bellek içi SQLite veritabanını alır.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - tabloların Base.metadata'ya kaydolması için
from app import crud, scheduler
from app import auth
from app.auth import hash_password
from app.config import get_settings
from app.database import Base, get_db
from app.main import build_app

TEST_PASSWORD = "gizli-sifre-123"

# Testler için sabit bir Fernet anahtarı. ENCRYPTION_KEY zorunlu olduğunda da
# token şifreleme testleri gerçek .env'e ihtiyaç duymadan çalışabilsin.
TEST_ENCRYPTION_KEY = "dGVzdC1hbmFodGFyaS0zMi1iYXl0LXV6dW5sdWd1bmQ="


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    get_settings.cache_clear()
    yield TEST_ENCRYPTION_KEY
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch):
    # Gerçek maliyet faktörü (12) her hash'i ~0.25 sn yapıyor; testlerde
    # algoritma aynı, sadece tur sayısı düşük.
    monkeypatch.setattr(auth, "BCRYPT_ROUNDS", 4)


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


def make_user(db, email="basak@example.com", password=TEST_PASSWORD):
    return crud.create_user(db, email, hash_password(password))


@pytest.fixture
def app(session_factory):
    # Lifespan'sız uygulama: gerçek veritabanı ve zamanlayıcı başlamaz.
    application = build_app()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
def anon_client(app):
    """Giriş yapmamış bir tarayıcı."""
    return TestClient(app)


def login(test_client, email, password=TEST_PASSWORD):
    resp = test_client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert resp.status_code == 303, resp.text
    return test_client


@pytest.fixture
def user(db):
    return make_user(db)


@pytest.fixture
def client(app, user):
    """`user` olarak giriş yapmış bir tarayıcı."""
    return login(TestClient(app), user.email)
