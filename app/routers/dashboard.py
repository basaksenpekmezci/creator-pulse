"""
Toplu istatistik endpoint'i. Platforma göre gruplanmış özet + en son
çekilen içerik listesini döndürür. templates/dashboard.html bu endpoint'i
JS ile çağırıp tabloyu/kartları dolduruyor.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.models import ContentMetric, PlatformAccount

router = APIRouter(tags=["dashboard"])


def build_trend(rows: list[tuple[str, int, ContentMetric]]) -> dict:
    """(platform, account_id, metric) satırlarından günlük trend serisi üretir.

    Her senkronizasyon gününün sonunda, o güne kadar bilinen her içeriğin en
    son değerini toplar. Bir içerik o gün senkronize edilmediyse önceki
    değeri geçerli sayılır; böylece eksik bir senkron grafikte yapay bir
    düşüş gibi görünmez. Hem genel toplam hem platform bazında seri döner.
    """
    rows = sorted(rows, key=lambda r: r[2].fetched_at)

    latest: dict[tuple[int, str], tuple[str, ContentMetric]] = {}
    days: list[date] = []
    totals: list[dict] = []
    by_platform: dict[str, list[dict]] = defaultdict(list)

    def snapshot(day: date) -> None:
        overall = {"likes": 0, "comments": 0, "views": 0}
        per_platform: dict[str, dict] = defaultdict(lambda: {"likes": 0, "comments": 0, "views": 0})
        for platform, metric in latest.values():
            for key in overall:
                value = getattr(metric, key)
                overall[key] += value
                per_platform[platform][key] += value
        days.append(day)
        totals.append(overall)
        # Henüz verisi olmayan platform için o günü 0 ile doldur ki
        # tüm seriler aynı uzunlukta olsun.
        for platform in set(by_platform) | set(per_platform):
            series = by_platform[platform]
            while len(series) < len(days) - 1:
                series.append({"likes": 0, "comments": 0, "views": 0})
            series.append(per_platform.get(platform, {"likes": 0, "comments": 0, "views": 0}))

    current_day: date | None = None
    for platform, account_id, metric in rows:
        day = metric.fetched_at.date()
        if current_day is not None and day != current_day:
            snapshot(current_day)
        current_day = day
        latest[(account_id, metric.content_id)] = (platform, metric)
    if current_day is not None:
        snapshot(current_day)

    return {
        "dates": [d.isoformat() for d in days],
        "total": totals,
        "by_platform": dict(by_platform),
    }


@router.get("/api/metrics/trend")
def get_metrics_trend(db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    rows = db.execute(
        select(PlatformAccount.platform, PlatformAccount.id, ContentMetric)
        .join(ContentMetric, ContentMetric.account_id == PlatformAccount.id)
        .where(PlatformAccount.user_id == user.id)
    ).all()
    return build_trend([tuple(r) for r in rows])


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
