"""
/connect/instagram ve /connect/instagram/callback uçlarının testleri.
Instagram API çağrıları connector seviyesinde taklit edilir; veritabanı
bellek içi SQLite'tır (bkz. conftest.py).
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.connectors import instagram
from app.models import ContentMetric, PlatformAccount
from app.routers import connect
from app.security import decrypt

SIXTY_DAYS = 60 * 24 * 3600


@pytest.fixture
def valid_state():
    connect._pending_states.add("gecerli-state")
    return "gecerli-state"


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


def test_callback_success_saves_encrypted_token_and_syncs(client, db, valid_state, fake_instagram):
    before = datetime.now(timezone.utc)
    resp = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "message": "Instagram bağlantısı başarılı ve kaydedildi",
        "account": "basak.creator",
        "posts_synced": 1,
    }

    account = db.scalar(select(PlatformAccount).where(PlatformAccount.platform == "instagram"))
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


def test_callback_consumes_state(client, valid_state, fake_instagram):
    first = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})
    assert first.status_code == 200
    # Aynı state ikinci kez kullanılamamalı (replay koruması).
    second = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})
    assert second.status_code == 400


@pytest.mark.parametrize(
    "params",
    [
        {"code": "abc", "state": "bilinmeyen-state"},
        {"state": "gecerli-state"},
        {"code": "abc"},
    ],
)
def test_callback_rejects_missing_or_unknown_state(client, valid_state, fake_instagram, params):
    resp = client.get("/connect/instagram/callback", params=params)
    assert resp.status_code == 400
    assert fake_instagram["sync"] == []


def test_callback_without_short_lived_token_returns_400(client, db, valid_state, fake_instagram, monkeypatch):
    monkeypatch.setattr(instagram, "exchange_code_for_token", lambda code: {"error": "yok"})

    resp = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Token alınamadı."
    assert db.scalar(select(PlatformAccount)) is None


def test_callback_falls_back_to_short_lived_token(client, db, valid_state, fake_instagram, monkeypatch):
    # Uzun ömürlü token dönmezse kısa ömürlü token ile devam edilir, süre bilinmez.
    monkeypatch.setattr(instagram, "exchange_for_long_lived_token", lambda token: {})

    resp = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})

    assert resp.status_code == 200
    account = db.scalar(select(PlatformAccount))
    assert decrypt(account.access_token_encrypted) == "kisa-token"
    assert account.token_expires_at is None


def test_callback_without_accounts_returns_400(client, valid_state, fake_instagram, monkeypatch):
    monkeypatch.setattr(instagram, "fetch_connected_ig_accounts", lambda token: [])

    resp = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Bağlı Instagram hesabı bulunamadı."


def test_callback_connector_error_returns_400(client, valid_state, fake_instagram, monkeypatch):
    def raise_error(code):
        raise instagram.InstagramConnectorError("INSTAGRAM_APP_ID tanımlı değil")

    monkeypatch.setattr(instagram, "exchange_code_for_token", raise_error)

    resp = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})

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

    resp = client.get("/connect/instagram/callback", params={"code": "abc", "state": valid_state})

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
    assert location.params["state"] in connect._pending_states


def test_connect_without_credentials_returns_400(client, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_ID", "")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "")
    instagram.get_settings.cache_clear()
    try:
        resp = client.get("/connect/instagram", follow_redirects=False)
    finally:
        instagram.get_settings.cache_clear()

    assert resp.status_code == 400
