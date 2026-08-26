"""
Periyodik senkronizasyon job'ı (APScheduler). MVP'de basit tutuluyor:
veritabanındaki her PlatformAccount için ilgili connector'ı çağırır.
Instagram App Secret Render'a eklendiğinden ve token'lar artık veritabanına
kaydedildiğinden beri Instagram da otomatik senkronize ediliyor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app import crud
from app.connectors import instagram, youtube
from app.database import SessionLocal
from app.models import PlatformAccount
from app.security import decrypt

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


def sync_all_instagram_accounts() -> None:
    db = SessionLocal()
    try:
        accounts = db.scalars(
            select(PlatformAccount).where(PlatformAccount.platform == "instagram")
        ).all()
        for account in accounts:
            if not account.access_token_encrypted:
                continue
            if account.token_expires_at and account.token_expires_at < datetime.now(timezone.utc):
                logger.warning(
                    "Instagram token süresi dolmuş, yeniden bağlanman gerekiyor: %s", account.display_name
                )
                continue
            try:
                access_token = decrypt(account.access_token_encrypted)
                items = instagram.sync_account(account.external_account_id, access_token)
                saved = crud.upsert_metrics(db, account, items)
                logger.info("Instagram senkronize edildi: %s (%d gönderi)", account.display_name, saved)
            except Exception:  # noqa: BLE001 - bir hesaptaki hata diğerlerini durdurmasın
                logger.exception("Instagram senkronizasyon hatası: %s", account.display_name)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    # Günde 2 kez senkronize et (kota dostu, MVP için yeterli sıklık).
    scheduler.add_job(sync_all_youtube_accounts, "interval", hours=12, id="sync_youtube")
    scheduler.add_job(sync_all_instagram_accounts, "interval", hours=12, id="sync_instagram")
    scheduler.start()
    return scheduler
