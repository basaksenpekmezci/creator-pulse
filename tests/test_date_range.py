"""
Dashboard'daki tarih aralığı filtresi için testler: ay hesabı yardımcıları ve
/api/metrics?range=... endpoint'inin hem içerik listesini hem de platform
özetlerini filtrelemesi. Bellek içi SQLite kullanılır.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import crud
from app.models import ContentMetric
from app.routers import dashboard
from app.routers.dashboard import in_range, range_start, subtract_months

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def test_subtract_months_simple():
    assert subtract_months(NOW, 1) == datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    assert subtract_months(NOW, 6) == datetime(2026, 4, 1, 12, tzinfo=timezone.utc)


def test_subtract_months_crosses_year():
    moment = datetime(2026, 2, 15, tzinfo=timezone.utc)
    assert subtract_months(moment, 3) == datetime(2025, 11, 15, tzinfo=timezone.utc)


def test_subtract_months_clamps_to_month_end():
    moment = datetime(2026, 3, 31, tzinfo=timezone.utc)
    assert subtract_months(moment, 1) == datetime(2026, 2, 28, tzinfo=timezone.utc)


def test_range_start_all_has_no_limit():
    assert range_start("all", NOW) is None
    assert range_start("2m", NOW) == datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


def test_in_range():
    start = range_start("1m", NOW)
    assert in_range(datetime(2026, 9, 15, tzinfo=timezone.utc), start)
    assert not in_range(datetime(2026, 8, 31, tzinfo=timezone.utc), start)
    # SQLite'tan gelen naive tarih UTC kabul edilir.
    assert in_range(datetime(2026, 9, 15), start)
    # Yayın tarihi olmayan içerik sadece "tümü"nde görünür.
    assert not in_range(None, start)
    assert in_range(None, None)


@pytest.fixture
def api(session_factory, client, user, monkeypatch):
    # Filtrenin "şimdi"sini sabitle ki testler takvime bağlı olmasın.
    monkeypatch.setattr(dashboard, "range_start", lambda r, now=None: range_start(r, NOW))

    with session_factory() as db:
        yt = crud.get_or_create_platform_account(db, user, "youtube", "UC1", "Kanal")
        ig = crud.get_or_create_platform_account(db, user, "instagram", "IG1", "Hesap")

        def add(account, content_id, days_ago, likes, comments, views, fetched_day=1):
            db.add(
                ContentMetric(
                    account_id=account.id, content_id=content_id, title=content_id,
                    likes=likes, comments=comments, views=views,
                    published_at=None if days_ago is None else NOW - timedelta(days=days_ago),
                    fetched_at=datetime(2026, 9, fetched_day, tzinfo=timezone.utc),
                )
            )

        add(yt, "yt-10g", 10, likes=10, comments=1, views=1000)
        # Aynı içeriğin eski senkronu toplamlara karışmamalı.
        add(yt, "yt-10g", 10, likes=1, comments=0, views=100, fetched_day=1)
        add(yt, "yt-10g", 10, likes=20, comments=2, views=2000, fetched_day=2)
        add(yt, "yt-45g", 45, likes=30, comments=3, views=300)
        add(yt, "yt-100g", 100, likes=40, comments=4, views=400)
        add(yt, "yt-tarihsiz", None, likes=50, comments=5, views=500)
        add(ig, "ig-20g", 20, likes=5, comments=5, views=50)
        add(ig, "ig-300g", 300, likes=7, comments=7, views=70)
        db.commit()

    return client


def titles(body):
    return sorted(c["title"] for c in body["content"])


def test_metrics_all_range_is_default(api):
    default = api.get("/api/metrics").json()
    body = api.get("/api/metrics?range=all").json()
    assert default == body
    assert titles(body) == sorted(
        ["yt-10g", "yt-45g", "yt-100g", "yt-tarihsiz", "ig-20g", "ig-300g"]
    )
    assert body["summary_by_platform"]["youtube"] == {
        "likes": 140, "comments": 14, "views": 3200, "content_count": 4,
    }


def test_metrics_last_month_filters_table_and_summary(api):
    body = api.get("/api/metrics?range=1m").json()
    assert titles(body) == ["ig-20g", "yt-10g"]
    assert body["summary_by_platform"]["youtube"] == {
        "likes": 20, "comments": 2, "views": 2000, "content_count": 1,
    }
    assert body["summary_by_platform"]["instagram"] == {
        "likes": 5, "comments": 5, "views": 50, "content_count": 1,
    }


@pytest.mark.parametrize(
    "date_range, expected",
    [
        ("2m", ["ig-20g", "yt-10g", "yt-45g"]),
        ("3m", ["ig-20g", "yt-10g", "yt-45g"]),
        ("6m", ["ig-20g", "yt-100g", "yt-10g", "yt-45g"]),
    ],
)
def test_metrics_wider_ranges(api, date_range, expected):
    assert titles(api.get(f"/api/metrics?range={date_range}").json()) == expected


def test_platform_card_stays_with_zero_when_range_is_empty(session_factory, api):
    # Instagram'ın son 1 aydaki tek içeriğini sil: kart 0 ile kalmalı.
    with session_factory() as db:
        db.query(ContentMetric).filter(ContentMetric.content_id == "ig-20g").delete()
        db.commit()
    body = api.get("/api/metrics?range=1m").json()
    assert body["summary_by_platform"]["instagram"] == {
        "likes": 0, "comments": 0, "views": 0, "content_count": 0,
    }


def test_metrics_rejects_unknown_range(api):
    assert api.get("/api/metrics?range=5y").status_code == 422
