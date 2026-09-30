"""
APScheduler job'larının (scheduler.py) testleri: Instagram senkronu ve
token yenileme. Veritabanı bellek içi SQLite, Instagram çağrıları taklit.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app import crud, scheduler
from app.connectors import instagram
from app.models import ContentMetric, PlatformAccount
from app.security import decrypt, encrypt

SIXTY_DAYS = 60 * 24 * 3600


def add_instagram_account(db, external_id, token="token", expires_in=timedelta(days=30), name=None):
    user = crud.get_or_create_default_user(db)
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
    user = crud.get_or_create_default_user(db)
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


# --- sync_all_instagram_accounts ------------------------------------------


@pytest.fixture
def sync_calls(monkeypatch):
    calls = []

    def fake_sync(ig_account_id, access_token):
        calls.append((ig_account_id, access_token))
        return [fake_item(f"{ig_account_id}-post")]

    monkeypatch.setattr(instagram, "sync_account", fake_sync)
    return calls


def test_sync_uses_decrypted_token_and_saves_metrics(db, sync_calls):
    add_instagram_account(db, "ig-1", token="gizli-token")

    scheduler.sync_all_instagram_accounts()

    assert sync_calls == [("ig-1", "gizli-token")]
    metric = db.scalar(select(ContentMetric))
    assert metric.content_id == "ig-1-post"
    assert metric.views == 3


def test_sync_skips_accounts_without_token(db, sync_calls):
    add_instagram_account(db, "ig-1", token="")

    scheduler.sync_all_instagram_accounts()

    assert sync_calls == []


def test_sync_skips_expired_tokens(db, sync_calls):
    add_instagram_account(db, "ig-expired", token="t", expires_in=timedelta(days=-1))
    add_instagram_account(db, "ig-ok", token="t2", expires_in=timedelta(days=10))

    scheduler.sync_all_instagram_accounts()

    assert sync_calls == [("ig-ok", "t2")]


def test_sync_runs_when_expiry_unknown(db, sync_calls):
    add_instagram_account(db, "ig-1", token="t", expires_in=None)

    scheduler.sync_all_instagram_accounts()

    assert sync_calls == [("ig-1", "t")]


def test_sync_failure_on_one_account_does_not_stop_others(db, monkeypatch):
    add_instagram_account(db, "ig-bad", token="t1")
    add_instagram_account(db, "ig-good", token="t2")

    def fake_sync(ig_account_id, access_token):
        if ig_account_id == "ig-bad":
            raise httpx.ConnectError("ağ hatası")
        return [fake_item("iyi-post")]

    monkeypatch.setattr(instagram, "sync_account", fake_sync)

    scheduler.sync_all_instagram_accounts()

    assert [m.content_id for m in db.scalars(select(ContentMetric))] == ["iyi-post"]


# --- start_scheduler --------------------------------------------------------


def test_start_scheduler_registers_jobs(monkeypatch):
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self, *a, **kw: None)

    sched = scheduler.start_scheduler()

    jobs = {job.id: job for job in sched.get_jobs()}
    assert set(jobs) == {"sync_youtube", "sync_instagram", "refresh_instagram_tokens"}
    assert jobs["sync_instagram"].func is scheduler.sync_all_instagram_accounts
    assert jobs["sync_instagram"].trigger.interval == timedelta(hours=12)
    assert jobs["sync_youtube"].trigger.interval == timedelta(hours=12)
    assert jobs["refresh_instagram_tokens"].func is scheduler.refresh_instagram_tokens
    assert jobs["refresh_instagram_tokens"].trigger.interval == timedelta(hours=24)
    # Yenileme penceresi, günlük kontrol birkaç kez kaçsa bile token'ı kurtaracak kadar geniş olmalı.
    assert scheduler.REFRESH_WINDOW >= timedelta(days=2)
