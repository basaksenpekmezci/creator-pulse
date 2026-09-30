"""
Instagram connector'ının token uçlarına doğru istekleri attığını ve
yanıtları doğru işlediğini doğrulayan testler. Gerçek ağ çağrısı yapmaz —
httpx.MockTransport ile Instagram API taklit edilir.
"""
from datetime import datetime, timezone

import httpx
import pytest

from app.connectors import instagram


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_ID", "test-app-id")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "test-app-secret")
    instagram.get_settings.cache_clear()
    yield
    instagram.get_settings.cache_clear()


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_ID", "")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "")
    instagram.get_settings.cache_clear()
    yield
    instagram.get_settings.cache_clear()


def mock_instagram_api(monkeypatch, handler):
    """instagram.py içindeki httpx.Client'ı sahte bir transport'a yönlendirir
    ve yapılan istekleri döndürür."""
    requests: list[httpx.Request] = []
    real_client = httpx.Client

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def fake_client(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(recording_handler), **kwargs)

    monkeypatch.setattr(instagram.httpx, "Client", fake_client)
    return requests


def test_refresh_long_lived_token_calls_refresh_endpoint(monkeypatch):
    requests = mock_instagram_api(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"access_token": "yeni-token", "token_type": "bearer", "expires_in": 5184000}
        ),
    )

    result = instagram.refresh_long_lived_token("eski-token")

    assert result["access_token"] == "yeni-token"
    assert result["expires_in"] == 5184000
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET"
    assert str(req.url).startswith(instagram.REFRESH_TOKEN_URL)
    assert req.url.params["grant_type"] == "ig_refresh_token"
    assert req.url.params["access_token"] == "eski-token"
    # Yenileme app secret istemez; secret URL'e sızmamalı.
    assert "client_secret" not in req.url.params


def test_refresh_long_lived_token_raises_on_expired_token(monkeypatch):
    mock_instagram_api(
        monkeypatch,
        lambda req: httpx.Response(400, json={"error": {"message": "Session has expired"}}),
    )

    with pytest.raises(httpx.HTTPStatusError):
        instagram.refresh_long_lived_token("suresi-dolmus-token")


def test_exchange_code_for_token_posts_form(monkeypatch, credentials):
    requests = mock_instagram_api(
        monkeypatch,
        lambda req: httpx.Response(200, json={"access_token": "kisa-token", "user_id": 42}),
    )

    result = instagram.exchange_code_for_token("auth-code")

    assert result["access_token"] == "kisa-token"
    req = requests[0]
    assert req.method == "POST"
    assert str(req.url) == instagram.OAUTH_TOKEN_URL
    body = dict(httpx.QueryParams(req.content.decode()))
    assert body["code"] == "auth-code"
    assert body["grant_type"] == "authorization_code"
    assert body["client_id"] == "test-app-id"
    assert body["client_secret"] == "test-app-secret"


def test_exchange_for_long_lived_token(monkeypatch, credentials):
    requests = mock_instagram_api(
        monkeypatch,
        lambda req: httpx.Response(200, json={"access_token": "uzun-token", "expires_in": 5184000}),
    )

    result = instagram.exchange_for_long_lived_token("kisa-token")

    assert result == {"access_token": "uzun-token", "expires_in": 5184000}
    params = requests[0].url.params
    assert params["grant_type"] == "ig_exchange_token"
    assert params["access_token"] == "kisa-token"
    assert params["client_secret"] == "test-app-secret"


def test_exchange_code_without_credentials_raises(no_credentials):
    with pytest.raises(instagram.InstagramConnectorError):
        instagram.exchange_code_for_token("auth-code")


def test_build_authorize_url_contains_state_and_scopes(credentials):
    url = httpx.URL(instagram.build_authorize_url("rastgele-state"))

    assert str(url).startswith(instagram.OAUTH_AUTHORIZE_URL)
    assert url.params["state"] == "rastgele-state"
    assert url.params["client_id"] == "test-app-id"
    assert url.params["response_type"] == "code"
    assert url.params["scope"] == ",".join(instagram.SCOPES)


def test_parse_datetime_handles_instagram_format():
    parsed = instagram._parse_datetime("2024-05-01T12:00:00+0000")
    assert parsed == datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
    assert instagram._parse_datetime(None) is None
    assert instagram._parse_datetime("gecersiz") is None


def test_sync_account_normalizes_media_and_tolerates_insights_error(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/media"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "m1",
                            "caption": "Karusel",
                            "permalink": "https://instagram.com/p/m1",
                            "like_count": 10,
                            "comments_count": 2,
                            "timestamp": "2024-05-01T12:00:00+0000",
                        },
                        {"id": "m2"},
                    ]
                },
            )
        if req.url.path.endswith("/m1/insights"):
            return httpx.Response(200, json={"data": [{"values": [{"value": 321}]}]})
        return httpx.Response(400, json={"error": {"message": "desteklenmiyor"}})

    mock_instagram_api(monkeypatch, handler)

    results = instagram.sync_account("ig-1", "token")

    assert [r["content_id"] for r in results] == ["m1", "m2"]
    assert results[0]["views"] == 321
    assert results[0]["likes"] == 10
    assert results[0]["published_at"] == datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
    # İkinci gönderinin insights çağrısı hata verdi: senkron durmamalı, 0'a düşmeli.
    assert results[1]["views"] == 0
    assert results[1]["title"] == ""
    assert results[1]["published_at"] is None
