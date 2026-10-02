"""
Toplu istatistik endpoint'i. Giriş yapan kullanıcının hesaplarına göre
platforma göre gruplanmış özet + en son çekilen içerik listesini döndürür. templates/dashboard.html bu endpoint'i
JS ile çağırıp tabloyu/kartları dolduruyor.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import ContentMetric, PlatformAccount, User

router = APIRouter(tags=["dashboard"])

# Dashboard'daki tarih aralığı filtresinin seçenekleri: anahtar -> kaç ay geriye.
# "all" filtre uygulamaz.
DATE_RANGES = {"1m": 1, "2m": 2, "3m": 3, "6m": 6, "all": None}
DateRange = Literal["1m", "2m", "3m", "6m", "all"]


def subtract_months(moment: datetime, months: int) -> datetime:
    """Takvim ayı olarak geri gider. Hedef ayda o gün yoksa (ör. 31 Mart'tan
    1 ay geri) ayın son gününe yaslanır."""
    month_index = moment.year * 12 + (moment.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def range_start(date_range: str, now: datetime | None = None) -> datetime | None:
    """Seçilen aralığın başlangıç anını döndürür; "all" için None."""
    months = DATE_RANGES[date_range]
    if months is None:
        return None
    return subtract_months(now or datetime.now(timezone.utc), months)


def in_range(published_at: datetime | None, start: datetime | None) -> bool:
    """İçerik seçilen aralıkta yayınlanmış mı? Yayın tarihi bilinmeyen içerik
    sadece "tümü" seçiliyken gösterilir, çünkü hangi aralığa düştüğü belli değil."""
    if start is None:
        return True
    if published_at is None:
        return False
    # SQLite saat dilimini saklamıyor; naive değerler UTC kabul edilir.
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return published_at >= start


@router.get("/api/metrics")
def get_metrics(
    date_range: DateRange = Query("all", alias="range"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start = range_start(date_range)

    # Her (account, content_id) çifti için en son çekilen satırı al —
    # aynı içerik zamanla birden çok kez senkronize edilmiş olabilir.
    accounts = db.scalars(
        select(PlatformAccount).where(PlatformAccount.user_id == user.id)
    ).all()

    summary = defaultdict(lambda: {"likes": 0, "comments": 0, "views": 0, "content_count": 0})
    latest_content = []

    for account in accounts:
        latest_per_content: dict[str, ContentMetric] = {}
        rows = db.scalars(
            select(ContentMetric)
            .where(ContentMetric.account_id == account.id)
            .order_by(ContentMetric.fetched_at.desc())
        ).all()
        for row in rows:
            if row.content_id not in latest_per_content:
                latest_per_content[row.content_id] = row

        # Verisi olan platformun kartı, seçilen aralıkta içerik olmasa da
        # 0 değerleriyle görünmeye devam etsin.
        if latest_per_content:
            summary[account.platform]

        for metric in latest_per_content.values():
            if not in_range(metric.published_at, start):
                continue
            summary[account.platform]["likes"] += metric.likes
            summary[account.platform]["comments"] += metric.comments
            summary[account.platform]["views"] += metric.views
            summary[account.platform]["content_count"] += 1
            latest_content.append(
                {
                    "platform": account.platform,
                    "account": account.display_name or account.external_account_id,
                    "title": metric.title,
                    "url": metric.url,
                    "likes": metric.likes,
                    "comments": metric.comments,
                    "views": metric.views,
                    "published_at": metric.published_at.isoformat() if metric.published_at else None,
                }
            )

    latest_content.sort(key=lambda x: x["views"], reverse=True)

    return {
        "summary_by_platform": summary,
        "content": latest_content[:50],
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


@router.get("/api/me")
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dashboard başlığı ve bağlı hesaplar listesi için: kim giriş yaptı,
    hangi hesapları bağlı ve her birinin senkronizasyon durumu ne."""
    accounts = db.scalars(
        select(PlatformAccount).where(PlatformAccount.user_id == user.id).order_by(PlatformAccount.id)
    ).all()
    return {
        "email": user.email,
        "accounts": [
            {
                "id": account.id,
                "platform": account.platform,
                "name": account.display_name or account.external_account_id,
                "sync_status": account.sync_status,
                "last_synced_at": _iso(account.last_synced_at),
                "last_sync_error": account.last_sync_error,
            }
            for account in accounts
        ],
    }
