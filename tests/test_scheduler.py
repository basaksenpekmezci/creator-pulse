"""
APScheduler job'larının (scheduler.py) testleri: hesap başına senkron,
günlük güncelleme zamanlaması ve Instagram token yenileme. Veritabanı
bellek içi SQLite, YouTube/Instagram çağrıları taklit.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app import crud, scheduler
from app.connectors import instagram, youtube
from app.models import ContentMetric, PlatformAccount
from app.security import decrypt, encrypt
from tests.conftest import make_user

SIXTY_DAYS = 60 * 24 * 3600


def get_user(db):
    return crud.get_user_by_email(db, "basak@example.com") or make_user(db)


def add_instagram_account(db, external_id, token="token", expires_in=timedelta(days=30), name=None):
    user = get_user(db)
    account = crud.get_or_create_platform_account(
        db, user, platform="instagram", external_account_id=external_id, display_name=name or external_id
    )
    account.access_token_encrypted = encrypt(token) if token else ""
    account.token_expires_at = datetime.now(timezone.utc) + expires_in if expires_in is not None else None
    db.commit()
    return account.id


def load(session_factory, account_id):
    with session_factory() as session:
        return session.get(PlatformAccount, account_id)


def as_utc(value):
    # SQLite saat dilimi bilgisini saklamıyor; karşılaştırma için UTC varsayıyoruz.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def fake_item(content_id):
    return {"content_id": content_id, "title": "", "url": "", "likes": 1, "comments": 0, "views": 3}


# --- refresh_instagram_tokens ---------------------------------------------


@pytest.fixture
def refresh_calls(monkeypatch):
    calls = []

    def fake_refresh(access_token):
        calls.append(access_token)
        return {"access_token": f"yeni-{access_token}", "token_type": "bearer", "expires_in": SIXTY_DAYS}

    monkeypatch.setattr(instagram, "refresh_long_lived_token", fake_refresh)
    return calls


def test_refresh_renews_token_close_to_expiry(db, session_factory, refresh_calls):
    account_id = add_instagram_account(db, "ig-1", token="eski", expires_in=timedelta(days=5))

    scheduler.refresh_instagram_tokens()

    assert refresh_calls == ["eski"]
    account = load(session_factory, account_id)
    assert decrypt(account.access_token_encrypted) == "yeni-eski"
    assert as_utc(account.token_expires_at) > datetime.now(timezone.utc) + timedelta(days=59)


def test_refresh_skips_tokens_outside_window(db, session_factory, refresh_calls):
    account_id = add_instagram_account(db, "ig-1", token="taze", expires_in=timedelta(days=30))

    scheduler.refresh_instagram_tokens()

    assert refresh_calls == []
    assert decrypt(load(session_factory, account_id).access_token_encrypted) == "taze"


def test_refresh_skips_accounts_without_token_or_expiry(db, refresh_calls):
    add_instagram_account(db, "tokensiz", token="", expires_in=timedelta(days=1))
    add_instagram_account(db, "suresiz", token="t", expires_in=None)

    scheduler.refresh_instagram_tokens()

    assert refresh_calls == []


def test_refresh_ignores_youtube_accounts(db, refresh_calls):
    user = get_user(db)
    account = crud.get_or_create_platform_account(db, user, platform="youtube", external_account_id="yt")
    account.access_token_encrypted = encrypt("yt-token")
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    db.commit()

    scheduler.refresh_instagram_tokens()

    assert refresh_calls == []


def test_refresh_failure_on_one_account_does_not_stop_others(db, session_factory, monkeypatch):
    bad_id = add_instagram_account(db, "ig-bad", token="bozuk", expires_in=timedelta(days=2))
    good_id = add_instagram_account(db, "ig-good", token="iyi", expires_in=timedelta(days=2))

    def fake_refresh(access_token):
        if access_token == "bozuk":
            raise httpx.HTTPStatusError(
                "400", request=httpx.Request("GET", instagram.REFRESH_TOKEN_URL), response=httpx.Response(400)
            )
        return {"access_token": "iyi-yeni", "expires_in": SIXTY_DAYS}

    monkeypatch.setattr(instagram, "refresh_long_lived_token", fake_refresh)

    scheduler.refresh_instagram_tokens()

    assert decrypt(load(session_factory, bad_id).access_token_encrypted) == "bozuk"
    assert decrypt(load(session_factory, good_id).access_token_encrypted) == "iyi-yeni"


def test_refresh_keeps_old_token_when_response_has_no_token(db, session_factory, monkeypatch):
    account_id = add_instagram_account(db, "ig-1", token="eski", expires_in=timedelta(days=5))
    before = as_utc(load(session_factory, account_id).token_expires_at)
    monkeypatch.setattr(instagram, "refresh_long_lived_token", lambda token: {})

    scheduler.refresh_instagram_tokens()

    account = load(session_factory, account_id)
    assert decrypt(account.access_token_encrypted) == "eski"
    assert as_utc(account.token_expires_at) == before


# --- sync_account / sync_due_accounts -------------------------------------


@pytest.fixture
def sync_calls(monkeypatch):
    calls = []

    def fake_sync(ig_account_id, access_token):
        calls.append((ig_account_id, access_token))
        return [fake_item(f"{ig_account_id}-post")]

    monkeypatch.setattr(instagram, "sync_account", fake_sync)
    return calls


@pytest.fixture
def youtube_calls(monkeypatch):
    calls = []

    def fake_sync(channel_id):
        calls.append(channel_id)
        return [fake_item(f"{channel_id}-video")]

    monkeypatch.setattr(youtube, "sync_channel", fake_sync)
    return calls


def add_youtube_account(db, channel_id, last_synced_at=None):
    account = crud.get_or_create_platform_account(db, get_user(db), "youtube", channel_id, channel_id)
    account.last_synced_at = last_synced_at
    db.commit()
    return account.id


def test_sync_uses_decrypted_token_and_saves_metrics(db, session_factory, sync_calls):
    account_id = add_instagram_account(db, "ig-1", token="gizli-token")

    assert scheduler.sync_account(account_id) is True

    assert sync_calls == [("ig-1", "gizli-token")]
    metric = db.scalar(select(ContentMetric))
    assert metric.content_id == "ig-1-post"
    assert metric.views == 3
    account = load(session_factory, account_id)
    assert account.sync_status == "ok"
    assert account.last_sync_error is None
    assert as_utc(account.last_synced_at) > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_sync_youtube_account(db, session_factory, youtube_calls):
    account_id = add_youtube_account(db, "UC1")

    assert scheduler.sync_account(account_id) is True

    assert youtube_calls == ["UC1"]
    assert db.scalar(select(ContentMetric)).content_id == "UC1-video"


def test_sync_skips_accounts_without_token(db, session_factory, sync_calls):
    account_id = add_instagram_account(db, "ig-1", token="")

    assert scheduler.sync_account(account_id) is False

    assert sync_calls == []
    account = load(session_factory, account_id)
    assert account.sync_status == "error"
    assert "yeniden bağla" in account.last_sync_error


def test_sync_skips_expired_tokens(db, session_factory, sync_calls):
    expired_id = add_instagram_account(db, "ig-expired", token="t", expires_in=timedelta(days=-1))
    ok_id = add_instagram_account(db, "ig-ok", token="t2", expires_in=timedelta(days=10))

    scheduler.sync_due_accounts()

    assert sync_calls == [("ig-ok", "t2")]
    assert "süresi dolmuş" in load(session_factory, expired_id).last_sync_error
    assert load(session_factory, ok_id).sync_status == "ok"


def test_sync_runs_when_expiry_unknown(db, sync_calls):
    account_id = add_instagram_account(db, "ig-1", token="t", expires_in=None)

    scheduler.sync_account(account_id)

    assert sync_calls == [("ig-1", "t")]


def test_sync_failure_on_one_account_does_not_stop_others(db, session_factory, monkeypatch):
    bad_id = add_instagram_account(db, "ig-bad", token="t1")
    add_instagram_account(db, "ig-good", token="t2")

    def fake_sync(ig_account_id, access_token):
        if ig_account_id == "ig-bad":
            raise httpx.ConnectError("ağ hatası")
        return [fake_item("iyi-post")]

    monkeypatch.setattr(instagram, "sync_account", fake_sync)

    assert scheduler.sync_due_accounts() == 1

    assert [m.content_id for m in db.scalars(select(ContentMetric))] == ["iyi-post"]
    bad = load(session_factory, bad_id)
    assert bad.sync_status == "error"
    assert bad.last_sync_error.startswith("ConnectError")
    assert bad.last_synced_at is None


def test_sync_account_ignores_missing_account(session_factory):
    assert scheduler.sync_account(999) is False


def test_due_accounts_are_never_synced_or_older_than_a_day(db, youtube_calls):
    now = datetime.now(timezone.utc)
    add_youtube_account(db, "UC-hic", last_synced_at=None)
    add_youtube_account(db, "UC-dun", last_synced_at=now - timedelta(hours=25))
    add_youtube_account(db, "UC-bugun", last_synced_at=now - timedelta(hours=3))

    assert scheduler.sync_due_accounts() == 2

    # Bugün zaten güncellenmiş hesaba tekrar API çağrısı yapılmaz.
    assert youtube_calls == ["UC-hic", "UC-dun"]


def test_account_is_synced_once_a_day(db, session_factory, youtube_calls):
    add_youtube_account(db, "UC1")

    scheduler.sync_due_accounts()
    # Saatlik kontroller aynı gün içinde hesabı yeniden çekmez...
    scheduler.sync_due_accounts()
    assert youtube_calls == ["UC1"]

    # ...ama 24 saat geçince tekrar çeker.
    tomorrow = datetime.now(timezone.utc) + scheduler.SYNC_INTERVAL + timedelta(minutes=1)
    with session_factory() as session:
        assert scheduler.due_account_ids(session, now=tomorrow) == [1]


# --- start_scheduler --------------------------------------------------------


def test_start_scheduler_registers_jobs(monkeypatch):
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self, *a, **kw: None)

    sched = scheduler.start_scheduler()

    jobs = {job.id: job for job in sched.get_jobs()}
    assert set(jobs) == {"sync_due_accounts", "refresh_instagram_tokens"}
    assert jobs["sync_due_accounts"].func is scheduler.sync_due_accounts
    # Saatte bir kontrol edilir, her hesap günde bir güncellenir.
    assert jobs["sync_due_accounts"].trigger.interval == timedelta(hours=1)
    assert scheduler.SYNC_INTERVAL == timedelta(days=1)
    # İlk kontrol sunucu açılır açılmaz yapılır (yeniden başlatma sayacı sıfırlamasın).
    assert jobs["sync_due_accounts"].next_run_time is not None
    assert jobs["refresh_instagram_tokens"].func is scheduler.refresh_instagram_tokens
    assert jobs["refresh_instagram_tokens"].trigger.interval == timedelta(hours=24)
    # Yenileme penceresi, günlük kontrol birkaç kez kaçsa bile token'ı kurtaracak kadar geniş olmalı.
    assert scheduler.REFRESH_WINDOW >= timedelta(days=2)
