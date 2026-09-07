"""
Toplu istatistik endpoint'i. Platforma göre gruplanmış özet + en son
çekilen içerik listesini döndürür. templates/dashboard.html bu endpoint'i
JS ile çağırıp tabloyu/kartları dolduruyor.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.models import ContentMetric, PlatformAccount

router = APIRouter(tags=["dashboard"])


@router.get("/api/metrics")
def get_metrics(db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)

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

        for metric in latest_per_content.values():
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
