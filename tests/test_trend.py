"""
Trend grafiği verisini üreten `build_trend` fonksiyonu ve /api/metrics/trend
endpoint'i için testler. Endpoint testi bellek içi SQLite kullanır, gerçek
veritabanı dosyasına dokunmaz.
"""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud
from app.database import Base, get_db
from app.models import ContentMetric
from app.routers import dashboard
from app.routers.dashboard import build_trend


def metric(content_id, day, likes=0, comments=0, views=0, hour=12):
    return ContentMetric(
        content_id=content_id,
        likes=likes,
        comments=comments,
        views=views,
        fetched_at=datetime(2026, 9, day, hour, tzinfo=timezone.utc),
    )


def test_build_trend_empty():
    assert build_trend([]) == {"dates": [], "total": [], "by_platform": {}}


def test_build_trend_uses_latest_snapshot_per_day():
    rows = [
        ("youtube", 1, metric("v1", 1, likes=10, comments=1, views=100, hour=8)),
        # Aynı gün ikinci senkron: önceki değerin üstüne eklenmemeli, yerini almalı.
        ("youtube", 1, metric("v1", 1, likes=15, comments=2, views=150, hour=20)),
        ("youtube", 1, metric("v1", 2, likes=20, comments=3, views=200)),
    ]
    trend = build_trend(rows)
    assert trend["dates"] == ["2026-09-01", "2026-09-02"]
    assert trend["total"] == [
        {"likes": 15, "comments": 2, "views": 150},
        {"likes": 20, "comments": 3, "views": 200},
    ]


def test_build_trend_carries_forward_unsynced_content():
    rows = [
        ("youtube", 1, metric("v1", 1, views=100)),
        ("instagram", 2, metric("p1", 1, views=50)),
        # 2. gün sadece YouTube senkronlandı; Instagram gönderisi düşmemeli.
        ("youtube", 1, metric("v1", 2, views=130)),
    ]
    trend = build_trend(rows)
    assert [p["views"] for p in trend["total"]] == [150, 180]
    assert [p["views"] for p in trend["by_platform"]["youtube"]] == [100, 130]
    assert [p["views"] for p in trend["by_platform"]["instagram"]] == [50, 50]


def test_build_trend_pads_platform_that_appears_later():
    rows = [
        ("youtube", 1, metric("v1", 1, likes=5)),
        ("instagram", 2, metric("p1", 3, likes=7)),
    ]
    trend = build_trend(rows)
    assert trend["dates"] == ["2026-09-01", "2026-09-03"]
    assert [p["likes"] for p in trend["by_platform"]["instagram"]] == [0, 7]
    assert [p["likes"] for p in trend["by_platform"]["youtube"]] == [5, 5]
    assert [p["likes"] for p in trend["total"]] == [5, 12]


def test_trend_endpoint_returns_series_from_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    with TestingSession() as db:
        user = crud.get_or_create_default_user(db)
        account = crud.get_or_create_platform_account(db, user, "youtube", "UC123", "Kanal")
        db.add_all(
            [
                ContentMetric(
                    account_id=account.id, content_id="v1", likes=1, comments=0, views=10,
                    fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                ),
                ContentMetric(
                    account_id=account.id, content_id="v1", likes=3, comments=1, views=40,
                    fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
                ),
            ]
        )
        db.commit()

    def override_get_db():
        with TestingSession() as db:
            yield db

    app = FastAPI()
    app.include_router(dashboard.router)
    app.dependency_overrides[get_db] = override_get_db

    res = TestClient(app).get("/api/metrics/trend")
    assert res.status_code == 200
    body = res.json()
    assert body["dates"] == ["2026-09-01", "2026-09-02"]
    assert [p["views"] for p in body["total"]] == [10, 40]
    assert [p["likes"] for p in body["by_platform"]["youtube"]] == [1, 3]
