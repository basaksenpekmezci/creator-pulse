"""
/connect/instagram ve /connect/instagram/callback uçlarının testleri.
Instagram API çağrıları connector seviyesinde taklit edilir; veritabanı
bellek içi SQLite'tır (bkz. conftest.py). Akış giriş yapmış kullanıcıyla
çalışır, OAuth state'i kullanıcının oturum çerezinde tutulur.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.connectors import instagram
from app.models import ContentMetric, PlatformAccount
from app.security import decrypt
from tests.conftest import login, make_user

SIXTY_DAYS = 60 * 24 * 3600


def start_flow(test_client):
    """/connect/instagram'ı çağırıp oturuma yazılan state'i döndürür."""
    resp = test_client.get("/connect/instagram", follow_redirects=False)
    assert resp.status_code in (302, 307), resp.text
    return httpx.URL(resp.headers["location"]).params["state"]


@pytest.fixture
def authorize_url(monkeypatch):
    monkeypatch.setattr(instagram, "build_authorize_url", lambda state: f"https://ig.test/oauth?state={state}")


@pytest.fixture
def valid_state(client, authorize_url):
    return start_flow(client)


@pytest.fixture
def fake_instagram(monkeypatch):
    """Başarılı bir OAuth akışını taklit eder; testler tek tek adımları bozabilir."""
    calls: dict[str, list] = {"sync": []}

    monkeypatch.setattr(
        instagram, "exchange_code_for_token", lambda code: {"access_token": "kisa-token", "user_id": 42}
    )
    monkeypatch.setattr(
        instagram,
        "exchange_for_long_lived_token",
        lambda token: {"access_token": "uzun-token", "expires_in": SIXTY_DAYS},
    )
    monkeypatch.setattr(
        instagram,
        "fetch_connected_ig_accounts",
        lambda token: [{"page_name": "basak.creator", "ig_account_id": "1789"}],
    )

    def fake_sync(ig_account_id, access_token):
        calls["sync"].append((ig_account_id, access_token))
        return [
            {
                "content_id": "m1",
                "title": "İlk gönderi",
                "url": "https://instagram.com/p/m1",
                "likes": 5,
                "comments": 1,
                "views": 100,
                "published_at": None,
            }
        ]

    monkeypatch.setattr(instagram, "sync_account", fake_sync)
    return calls


def callback(test_client, **params):
    return test_client.get("/connect/instagram/callback", params=params, follow_redirects=False)


def test_callback_success_saves_encrypted_token_and_syncs(client, db, user, valid_state, fake_instagram):
    before = datetime.now(timezone.utc)
    resp = callback(client, code="abc", state=valid_state)

    # Kullanıcı dashboard'a döner; ilk senkron arka planda çalışır.
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/?baglandi=instagram"

    account = db.scalar(select(PlatformAccount).where(PlatformAccount.platform == "instagram"))
    assert account.user_id == user.id
    assert account.external_account_id == "1789"
    assert account.display_name == "basak.creator"
    # Token düz metin saklanmamalı, ama çözülünce uzun ömürlü token olmalı.
    assert account.access_token_encrypted != "uzun-token"
    assert decrypt(account.access_token_encrypted) == "uzun-token"
    expires_at = account.token_expires_at.replace(tzinfo=timezone.utc)
    assert before + timedelta(days=59) < expires_at < before + timedelta(days=61)

    # İlk senkron uzun ömürlü token ile yapılmalı ve metrikler kaydedilmeli.
    assert fake_instagram["sync"] == [("1789", "uzun-token")]
    assert db.scalar(select(ContentMetric)).content_id == "m1"
    assert account.sync_status == "ok"
    assert account.last_synced_at is not None


def test_callback_consumes_state(client, valid_state, fake_instagram):
    first = callback(client, code="abc", state=valid_state)
    assert first.status_code == 303
    # Aynı state ikinci kez kullanılamamalı (replay koruması).
    second = callback(client, code="abc", state=valid_state)
    assert second.status_code == 400


def test_state_from_another_session_is_rejected(app, db, client, valid_state, fake_instagram):
    # Başka bir kullanıcının oturumu, bu kullanıcının state'iyle callback'i tamamlayamaz.
    make_user(db, "diger@example.com")
    other = login(TestClient(app), "diger@example.com")

    resp = callback(other, code="abc", state=valid_state)

    assert resp.status_code == 400
    assert fake_instagram["sync"] == []


def test_connect_and_callback_require_login(anon_client, fake_instagram):
    assert anon_client.get("/connect/instagram", follow_redirects=False).status_code == 401
    assert callback(anon_client, code="abc", state="x").status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"code": "abc", "state": "bilinmeyen-state"},
        {"state": "VALID"},
        {"code": "abc"},
    ],
)
def test_callback_rejects_missing_or_unknown_state(client, valid_state, fake_instagram, params):
    params = {k: valid_state if v == "VALID" else v for k, v in params.items()}
    resp = callback(client, **params)
    assert resp.status_code == 400
    assert fake_instagram["sync"] == []


def test_callback_without_short_lived_token_returns_400(client, db, valid_state, fake_instagram, monkeypatch):
    monkeypatch.setattr(instagram, "exchange_code_for_token", lambda code: {"error": "yok"})

    resp = callback(client, code="abc", state=valid_state)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Token alınamadı."
    assert db.scalar(select(PlatformAccount)) is None


def test_callback_falls_back_to_short_lived_token(client, db, valid_state, fake_instagram, monkeypatch):
    # Uzun ömürlü token dönmezse kısa ömürlü token ile devam edilir, süre bilinmez.
    monkeypatch.setattr(instagram, "exchange_for_long_lived_token", lambda token: {})

    resp = callback(client, code="abc", state=valid_state)

    assert resp.status_code == 303
    account = db.scalar(select(PlatformAccount))
    assert decrypt(account.access_token_encrypted) == "kisa-token"
    assert account.token_expires_at is None


def test_callback_without_accounts_returns_400(client, valid_state, fake_instagram, monkeypatch):
    monkeypatch.setattr(instagram, "fetch_connected_ig_accounts", lambda token: [])

    resp = callback(client, code="abc", state=valid_state)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Bağlı Instagram hesabı bulunamadı."


def test_callback_connector_error_returns_400(client, valid_state, fake_instagram, monkeypatch):
    def raise_error(code):
        raise instagram.InstagramConnectorError("INSTAGRAM_APP_ID tanımlı değil")

    monkeypatch.setattr(instagram, "exchange_code_for_token", raise_error)

    resp = callback(client, code="abc", state=valid_state)

    assert resp.status_code == 400
    assert "INSTAGRAM_APP_ID" in resp.json()["detail"]


def test_callback_api_error_returns_500_with_reason(client, valid_state, fake_instagram, monkeypatch):
    def raise_http_error(code):
        raise httpx.HTTPStatusError(
            "400 Bad Request",
            request=httpx.Request("POST", instagram.OAUTH_TOKEN_URL),
            response=httpx.Response(400),
        )

    monkeypatch.setattr(instagram, "exchange_code_for_token", raise_http_error)

    resp = callback(client, code="abc", state=valid_state)

    assert resp.status_code == 500
    assert resp.json()["detail"].startswith("HTTPStatusError")


def test_connect_redirects_to_instagram_and_stores_state(client, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_ID", "test-app-id")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "test-app-secret")
    instagram.get_settings.cache_clear()
    try:
        resp = client.get("/connect/instagram", follow_redirects=False)
    finally:
        instagram.get_settings.cache_clear()

    assert resp.status_code in (302, 307)
    location = httpx.URL(resp.headers["location"])
    assert str(location).startswith(instagram.OAUTH_AUTHORIZE_URL)
    # State oturuma yazıldı: aynı oturumda callback kabul edilir.
    assert location.params["state"]
    assert "creator_pulse_session" in client.cookies


def test_connect_without_credentials_returns_400(client, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_ID", "")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "")
    instagram.get_settings.cache_clear()
    try:
        resp = client.get("/connect/instagram", follow_redirects=False)
    finally:
        instagram.get_settings.cache_clear()

    assert resp.status_code == 400
