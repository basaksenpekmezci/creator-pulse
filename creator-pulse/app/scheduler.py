"""
Periyodik senkronizasyon job'ı (APScheduler). MVP'de basit tutuluyor:
veritabanındaki her PlatformAccount için ilgili connector'ı çağırır.
Şu an sadece YouTube otomatik senkronize ediliyor çünkü Instagram token
saklama/yenileme akışı henüz tamamlanmadı (Meta onayı bekleniyor).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app import crud
from app.connectors import youtube
from app.database import SessionLocal
from app.models import PlatformAccount

logger = logging.getLogger("creator_pulse.scheduler")


def sync_all_youtube_accounts() -> None:
    db = SessionLocal()
    try:
        accounts = db.scalars(
            select(PlatformAccount).where(PlatformAccount.platform == "youtube")
        ).all()
        for account in accounts:
            try:
                items = youtube.sync_channel(account.external_account_id)
                saved = crud.upsert_metrics(db, account, items)
                logger.info("YouTube senkronize edildi: %s (%d video)", account.display_name, saved)
            except Exception:  # noqa: BLE001 - bir hesaptaki hata diğerlerini durdurmasın
                logger.exception("YouTube senkronizasyon hatası: %s", account.display_name)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    # Günde 2 kez senkronize et (kota dostu, MVP için yeterli sıklık).
    scheduler.add_job(sync_all_youtube_accounts, "interval", hours=12, id="sync_youtube")
    scheduler.start()
    return scheduler
