"""
Kullanıcı verisinin ayrılması ve eski ortak kullanıcının verisinin taşınması:
her kullanıcı sadece kendi hesaplarını/metriklerini görür; kullanıcı
sisteminden önceki tek ortak kullanıcının (DEFAULT_USER) verisi kayıt
sırasında bir kullanıcıya bağlanır; eski veritabanı şeması yeni kolonlarla
güncellenir.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.pool import StaticPool

from app import crud
from app.config import get_settings
from app.connectors import instagram, youtube
from app.database import init_db
from app.models import ContentMetric, PlatformAccount, User
from app.security import encrypt
from tests.conftest import TEST_PASSWORD, login, make_user


def add_content(db, user, platform, external_id, content_id, views):
    account = crud.get_or_create_platform_account(db, user, platform, external_id, external_id)
    db.add(
        ContentMetric(
            account_id=account.id, content_id=content_id, title=content_id, views=views,
            published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    db.commit()
    return account


def register(test_client, email):
    resp = test_client.post(
        "/register",
        data={"email": email, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    return test_client


# --- her kullanıcı kendi verisini görür ------------------------------------


@pytest.fixture
def two_users(app, db, user):
    other = make_user(db, "ayse@example.com")
    add_content(db, user, "youtube", "UC-basak", "basak-video", views=100)
    add_content(db, other, "youtube", "UC-ayse", "ayse-video", views=999)
    add_content(db, other, "instagram", "IG-ayse", "ayse-post", views=5)
    return login(TestClient(app), user.email), login(TestClient(app), other.email)


def test_dashboard_shows_only_own_metrics(two_users):
    basak, ayse = two_users

    body = basak.get("/api/metrics").json()
    assert [c["title"] for c in body["content"]] == ["basak-video"]
    assert set(body["summary_by_platform"]) == {"youtube"}
    assert body["summary_by_platform"]["youtube"]["views"] == 100

    body = ayse.get("/api/metrics").json()
    assert sorted(c["title"] for c in body["content"]) == ["ayse-post", "ayse-video"]


def test_me_lists_only_own_accounts(two_users):
    basak, ayse = two_users
    me = basak.get("/api/me").json()
    assert me["email"] == "basak@example.com"
    assert [a["name"] for a in me["accounts"]] == ["UC-basak"]
    assert sorted(a["name"] for a in ayse.get("/api/me").json()["accounts"]) == ["IG-ayse", "UC-ayse"]


def test_new_user_starts_empty(app, two_users):
    newcomer = register(TestClient(app), "yeni@example.com")
    assert newcomer.get("/api/metrics").json() == {"summary_by_platform": {}, "content": []}
    assert newcomer.get("/api/me").json()["accounts"] == []


def test_manual_instagram_sync_only_touches_own_accounts(app, db, user, monkeypatch):
    other = make_user(db, "ayse@example.com")
    for owner, ig_id in ((user, "IG-basak"), (other, "IG-ayse")):
        account = crud.get_or_create_platform_account(db, owner, "instagram", ig_id, ig_id)
        account.access_token_encrypted = encrypt(f"token-{ig_id}")
    db.commit()
    calls = []
    monkeypatch.setattr(instagram, "sync_account", lambda ig_id, token: calls.append(ig_id) or [])

    resp = login(TestClient(app), user.email).post("/sync/instagram")

    assert resp.status_code == 200
    assert calls == ["IG-basak"]


def test_manual_youtube_sync_saves_to_current_user(client, db, user, monkeypatch):
    monkeypatch.setattr(youtube, "sync_channel_with_id", lambda handle: ("UC-x", []))
    assert client.post("/sync/youtube?handle=kanal").status_code == 200
    account = db.scalar(select(PlatformAccount))
    assert account.user_id == user.id


def test_same_channel_can_belong_to_two_users(db, user):
    other = make_user(db, "ayse@example.com")
    add_content(db, user, "youtube", "UC-ortak", "v1", views=1)
    add_content(db, other, "youtube", "UC-ortak", "v1", views=1)
    assert db.query(PlatformAccount).count() == 2


def test_default_user_logic_is_gone():
    assert not hasattr(crud, "get_or_create_default_user")
    assert not hasattr(crud, "DEFAULT_USER_EMAIL")


# --- eski ortak kullanıcının verisini taşıma -------------------------------


@pytest.fixture
def legacy_data(db):
    """Kullanıcı sisteminden önceki durum: her şey tek ortak kullanıcıda."""
    legacy = User(email=crud.LEGACY_USER_EMAIL)
    db.add(legacy)
    db.commit()
    add_content(db, legacy, "youtube", "UC-eski", "eski-video", views=500)
    add_content(db, legacy, "instagram", "IG-eski", "eski-post", views=50)
    return legacy.id


def test_first_registered_user_gets_legacy_data(app, db, legacy_data):
    first = register(TestClient(app), "basak@example.com")

    body = first.get("/api/metrics").json()
    assert sorted(c["title"] for c in body["content"]) == ["eski-post", "eski-video"]
    # Ortak kullanıcı silindi, metrikler kaybolmadı.
    db.expire_all()
    assert db.get(User, legacy_data) is None
    assert db.query(ContentMetric).count() == 2
    owner = crud.get_user_by_email(db, "basak@example.com")
    assert {a.user_id for a in db.query(PlatformAccount)} == {owner.id}

    # İkinci kullanıcı hiçbir şey almaz.
    second = register(TestClient(app), "ayse@example.com")
    assert second.get("/api/metrics").json()["content"] == []


def test_legacy_data_not_given_when_a_real_user_already_exists(db, user, legacy_data):
    newcomer = make_user(db, "ayse@example.com")
    assert crud.claim_legacy_data(db, newcomer) == 0
    assert db.get(User, legacy_data) is not None


def test_legacy_data_goes_to_configured_owner(app, db, legacy_data, monkeypatch):
    monkeypatch.setenv("LEGACY_DATA_OWNER_EMAIL", "Basak@Example.com")
    get_settings.cache_clear()

    # Ayarlanan e-posta dışındaki biri ilk kaydolsa bile veriyi almaz...
    first = register(TestClient(app), "ayse@example.com")
    assert first.get("/api/metrics").json()["content"] == []

    # ...veri, o e-postayla kaydolan kullanıcıya gider.
    owner = register(TestClient(app), "basak@example.com")
    assert len(owner.get("/api/metrics").json()["content"]) == 2


def test_claim_without_legacy_user_is_noop(db, user):
    assert crud.claim_legacy_data(db, user) == 0


# --- eski veritabanı şemasının güncellenmesi -------------------------------


def test_init_db_adds_new_columns_to_old_database():
    """Başak'ın yerel creator_pulse.db'si gibi, kullanıcı sisteminden önceki
    şemayla oluşturulmuş bir veritabanı: yeni kolonlar eklenir, veri korunur."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) UNIQUE, created_at DATETIME)"))
        conn.execute(text(
            "CREATE TABLE platform_accounts (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), "
            "platform VARCHAR(32), external_account_id VARCHAR(255), display_name VARCHAR(255), "
            "access_token_encrypted VARCHAR(2048), refresh_token_encrypted VARCHAR(2048), "
            "token_expires_at DATETIME, connected_at DATETIME)"
        ))
        conn.execute(text("INSERT INTO users (id, email) VALUES (1, 'me@creator-pulse.local')"))
        conn.execute(text(
            "INSERT INTO platform_accounts (id, user_id, platform, external_account_id, display_name) "
            "VALUES (1, 1, 'youtube', 'UC1', 'kanal')"
        ))

    init_db(engine)
    init_db(engine)  # ikinci açılışta tekrar eklemeye çalışmamalı

    inspector = inspect(engine)
    assert "password_hash" in {c["name"] for c in inspector.get_columns("users")}
    assert {"sync_status", "last_synced_at", "last_sync_error"} <= {
        c["name"] for c in inspector.get_columns("platform_accounts")
    }
    assert "content_metrics" in inspector.get_table_names()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT email, password_hash FROM users")).one()
        assert row == ("me@creator-pulse.local", None)
        assert conn.execute(text("SELECT display_name, last_synced_at FROM platform_accounts")).one() == ("kanal", None)
