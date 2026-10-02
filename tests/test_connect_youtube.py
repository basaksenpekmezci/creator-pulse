"""
Dashboard'daki "YouTube bağla" butonunun ucu (POST /connect/youtube):
kanal hemen doğrulanır, hesap giriş yapan kullanıcıya bağlanır ve ilk
senkronizasyon arka planda çalışır. YouTube API çağrıları taklit edilir.
"""
import pytest
from sqlalchemy import select

from app.connectors import youtube
from app.models import ContentMetric, PlatformAccount


@pytest.fixture
def fake_youtube(monkeypatch):
    calls = {"sync": []}

    def resolve(handle):
        if handle == "@yok":
            raise youtube.YouTubeConnectorError("Kanal bulunamadı: @yok")
        return "UC-basak"

    def sync(channel_id):
        calls["sync"].append(channel_id)
        return [{"content_id": "v1", "title": "İlk video", "url": "", "likes": 3, "comments": 1, "views": 42}]

    monkeypatch.setattr(youtube, "resolve_channel_id", resolve)
    monkeypatch.setattr(youtube, "sync_channel", sync)
    return calls


def test_connect_youtube_creates_account_and_syncs_in_background(client, db, user, fake_youtube):
    resp = client.post("/connect/youtube", json={"handle": "  @basakkanal "})

    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "syncing"
    assert resp.json()["channel"] == "@basakkanal"

    account = db.scalar(select(PlatformAccount))
    assert (account.user_id, account.platform, account.external_account_id) == (user.id, "youtube", "UC-basak")
    # Arka plan görevi yanıt döndükten sonra çalıştı ve veriyi kaydetti.
    assert fake_youtube["sync"] == ["UC-basak"]
    assert db.scalar(select(ContentMetric)).views == 42
    assert account.sync_status == "ok"

    me = client.get("/api/me").json()
    assert me["accounts"][0]["sync_status"] == "ok"
    assert me["accounts"][0]["last_synced_at"]
    assert client.get("/api/metrics").json()["summary_by_platform"]["youtube"]["views"] == 42


def test_connect_youtube_twice_does_not_duplicate_account(client, db, fake_youtube):
    client.post("/connect/youtube", json={"handle": "@basakkanal"})
    client.post("/connect/youtube", json={"handle": "@basakkanal"})
    assert db.query(PlatformAccount).count() == 1
    assert fake_youtube["sync"] == ["UC-basak", "UC-basak"]


def test_connect_youtube_unknown_channel_returns_error_immediately(client, db, fake_youtube):
    resp = client.post("/connect/youtube", json={"handle": "@yok"})
    assert resp.status_code == 400
    assert "Kanal bulunamadı" in resp.json()["detail"]
    assert db.query(PlatformAccount).count() == 0
    assert fake_youtube["sync"] == []


def test_connect_youtube_empty_handle(client, fake_youtube):
    assert client.post("/connect/youtube", json={"handle": "  "}).status_code == 400


def test_background_sync_error_is_shown_on_account(client, db, fake_youtube, monkeypatch):
    def broken(channel_id):
        raise youtube.YouTubeConnectorError("YouTube API hata döndürdü (HTTP 403): kota")

    monkeypatch.setattr(youtube, "sync_channel", broken)

    assert client.post("/connect/youtube", json={"handle": "@basakkanal"}).status_code == 202

    account = client.get("/api/me").json()["accounts"][0]
    assert account["sync_status"] == "error"
    assert "kota" in account["last_sync_error"]


def test_connect_youtube_requires_login(anon_client, fake_youtube):
    assert anon_client.post("/connect/youtube", json={"handle": "@x"}).status_code == 401
