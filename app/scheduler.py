"""
Otomatik senkronizasyon (APScheduler).

Her bağlı hesap günde bir kez güncellenir. Bunu "24 saatte bir çalışan job"
yerine "saatte bir bakıp son senkronu 24 saatten eski hesapları güncelleyen
job" olarak kuruyoruz: sunucu yeniden başlasa ya da (Render'daki gibi)
uykuya dalıp uyansa bile sayaç sıfırlanmıyor, açılışta da hemen bir kontrol
yapılıyor. Böylece kullanıcı giriş yaptığında verisi en fazla bir günlük oluyor.

sync_account aynı zamanda dashboard'dan hesap bağlanınca arka planda çalışan
ilk senkronizasyonun da kendisi (bkz. app/routers/connect.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import or_, select

from app import crud
from app.connectors import instagram, youtube
from app.database import SessionLocal
from app.models import PlatformAccount
from app.security import decrypt, encrypt

# Bir hesabın verisi bu süreden eskiyse zamanlayıcı onu yeniden çeker.
SYNC_INTERVAL = timedelta(days=1)
# Zamanlayıcının "güncellemesi gelen hesap var mı" diye bakma sıklığı.
DUE_CHECK_INTERVAL = timedelta(hours=1)

# Instagram uzun ömürlü token'lar 60 gün geçerli. Süresi dolmadan yeterince
# önce yenilemeye çalışıyoruz ki bir günlük gecikme/aksama yüzünden fırsatı
# kaçırmayalım.
REFRESH_WINDOW = timedelta(days=10)

logger = logging.getLogger("creator_pulse.scheduler")


class SyncSkipped(Exception):
    """Hesap şu an senkronize edilemiyor (ör. token yok/süresi dolmuş)."""


def _as_utc(value: datetime) -> datetime:
    """SQLite DateTime(timezone=True) kolonlarını saat dilimi bilgisi olmadan
    (naive) geri döndürüyor; aware bir datetime ile karşılaştırınca TypeError
    fırlıyor ve job'ın tamamı çöküyordu. Kaydederken UTC yazdığımız için
    naive değerleri UTC kabul ediyoruz."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _fetch_items(account: PlatformAccount) -> list[dict]:
    if account.platform == "youtube":
        return youtube.sync_channel(account.external_account_id)
    if account.platform == "instagram":
        if not account.access_token_encrypted:
            raise SyncSkipped("Instagram token'ı yok, hesabı yeniden bağla.")
        if account.token_expires_at and _as_utc(account.token_expires_at) < datetime.now(timezone.utc):
            raise SyncSkipped("Instagram bağlantısının süresi dolmuş, hesabı yeniden bağla.")
        access_token = decrypt(account.access_token_encrypted)
        return instagram.sync_account(account.external_account_id, access_token)
    raise SyncSkipped(f"Desteklenmeyen platform: {account.platform}")


def sync_account(account_id: int) -> bool:
    """Tek bir hesabı senkronize eder ve sonucu hesabın sync_* alanlarına
    yazar. Hata fırlatmaz (arka plan görevi ve zamanlayıcı için); başarılıysa
    True döner."""
    db = SessionLocal()
    try:
        account = db.get(PlatformAccount, account_id)
        if account is None:
            return False
        name = account.display_name or account.external_account_id
        account.sync_status = "syncing"
        db.commit()
        try:
            items = _fetch_items(account)
            saved = crud.upsert_metrics(db, account, items)
        except Exception as exc:  # noqa: BLE001 - bir hesaptaki hata diğerlerini durdurmasın
            db.rollback()
            if isinstance(exc, SyncSkipped):
                logger.warning("%s senkronize edilemedi (%s): %s", account.platform, name, exc)
                message = str(exc)
            else:
                logger.exception("%s senkronizasyon hatası: %s", account.platform, name)
                message = f"{type(exc).__name__}: {exc}"
            account.sync_status = "error"
            account.last_sync_error = message[:500]
            db.commit()
            return False
        account.sync_status = "ok"
        account.last_sync_error = None
        account.last_synced_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("%s senkronize edildi: %s (%d içerik)", account.platform, name, saved)
        return True
    finally:
        db.close()


def due_account_ids(db, now: datetime | None = None) -> list[int]:
    """Son başarılı senkronu SYNC_INTERVAL'dan eski (ya da hiç olmamış)
    hesapların id'leri."""
    cutoff = (now or datetime.now(timezone.utc)) - SYNC_INTERVAL
    return list(
        db.scalars(
            select(PlatformAccount.id)
            .where(or_(PlatformAccount.last_synced_at.is_(None), PlatformAccount.last_synced_at <= cutoff))
            .order_by(PlatformAccount.id)
        )
    )


def sync_due_accounts() -> int:
    """Zamanlayıcı job'ı: günlük güncellemesi gelen her hesabı senkronize eder.
    Başarıyla senkronize edilen hesap sayısını döndürür."""
    db = SessionLocal()
    try:
        account_ids = due_account_ids(db)
    finally:
        db.close()
    return sum(sync_account(account_id) for account_id in account_ids)


def refresh_instagram_tokens() -> None:
    """Süresi dolmaya yaklaşan Instagram token'larını otomatik yeniler.
    Bu çalışmazsa 60 gün sonra Instagram senkronizasyonu sessizce durur ve
    kullanıcının dashboard'daki "Instagram bağla" ile yeniden bağlanması gerekir."""
    db = SessionLocal()
    try:
        accounts = db.scalars(
            select(PlatformAccount).where(PlatformAccount.platform == "instagram")
        ).all()
        now = datetime.now(timezone.utc)
        for account in accounts:
            if not account.access_token_encrypted or not account.token_expires_at:
                continue
            if _as_utc(account.token_expires_at) - now > REFRESH_WINDOW:
                continue  # henüz yenileme zamanı gelmedi
            try:
                access_token = decrypt(account.access_token_encrypted)
                refreshed = instagram.refresh_long_lived_token(access_token)
                new_token = refreshed.get("access_token")
                expires_in = refreshed.get("expires_in")
                if not new_token:
                    continue
                account.access_token_encrypted = encrypt(new_token)
                if expires_in:
                    account.token_expires_at = now + timedelta(seconds=int(expires_in))
                db.commit()
                logger.info("Instagram token yenilendi: %s", account.display_name)
            except Exception:  # noqa: BLE001 - bir hesaptaki hata diğerlerini durdurmasın
                # Token süresi zaten dolmuşsa yenileme başarısız olur — bu
                # durumda kullanıcının yeniden /connect/instagram yapması gerekir.
                logger.exception(
                    "Instagram token yenileme hatası (%s) — yeniden bağlanman gerekebilir.",
                    account.display_name,
                )
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    # Her hesap günde bir güncellenir; saatlik kontrol sadece sırası gelenleri
    # çeker. İlk kontrol sunucu açılır açılmaz yapılır.
    scheduler.add_job(
        sync_due_accounts,
        "interval",
        seconds=DUE_CHECK_INTERVAL.total_seconds(),
        id="sync_due_accounts",
        next_run_time=datetime.now(timezone.utc),
    )
    # Token yenilemeyi günde 1 kez kontrol etmek yeterli (10 günlük pencere var).
    scheduler.add_job(refresh_instagram_tokens, "interval", hours=24, id="refresh_instagram_tokens")
    scheduler.start()
    return scheduler
